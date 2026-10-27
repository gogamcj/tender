"""규칙 선택과 평가.

- 공고일(announcement_date) 기준으로 유효기간을 판정한다. 최신 규칙을 과거 공고에 소급하지 않는다.
- 조건이 하나라도 확인되지 않으면 "판단 불가"로 남기고 임의로 맞다고 보지 않는다.
- 미검증 규칙으로 계산한 결과는 definitive=False 이며, block_unverified=True 면 계산 자체를 막는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..calc import (
    CalcResult,
    PriceStatus,
    RateBasis,
    RateUnit,
    RoundingMode,
    RoundingRule,
    lower_limit_amount,
    lower_limit_amount_with_a_value,
)
from ..calc.errors import CalcInputError
from .schema import ANY, NoticeContext, RuleDefinition, VerificationStatus


class MatchOutcome(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNDETERMINED = "undetermined"  # 공고 정보가 부족해 판단할 수 없음


@dataclass(frozen=True)
class RuleMatch:
    rule: RuleDefinition
    outcome: MatchOutcome
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RuleSelection:
    matches: tuple[RuleMatch, ...]
    undetermined: tuple[RuleMatch, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def selected(self) -> RuleDefinition | None:
        """정확히 하나만 일치하고 판단 불가 후보가 없을 때만 자동 선택한다."""
        if len(self.matches) == 1 and not self.undetermined:
            return self.matches[0].rule
        return None


def _match_field(rule_value: str, notice_value: str | None, label: str, reasons: list[str]) -> MatchOutcome:
    if rule_value == ANY:
        return MatchOutcome.MATCH
    if notice_value is None:
        reasons.append(f"{label} 미확인(규칙: {rule_value})")
        return MatchOutcome.UNDETERMINED
    if rule_value != notice_value:
        reasons.append(f"{label} 불일치(규칙: {rule_value}, 공고: {notice_value})")
        return MatchOutcome.NO_MATCH
    reasons.append(f"{label} 일치({rule_value})")
    return MatchOutcome.MATCH


def match_rule(rule: RuleDefinition, ctx: NoticeContext) -> RuleMatch:
    reasons: list[str] = []
    outcomes: list[MatchOutcome] = []

    if rule.verification_status is VerificationStatus.RETIRED:
        return RuleMatch(rule, MatchOutcome.NO_MATCH, ("사용 중지된 규칙",))

    if ctx.announcement_date is None:
        reasons.append("공고일 미확인: 유효기간을 판정할 수 없음")
        outcomes.append(MatchOutcome.UNDETERMINED)
    elif ctx.announcement_date < rule.effective_from or (
        rule.effective_until is not None and ctx.announcement_date > rule.effective_until
    ):
        reasons.append(
            f"유효기간 밖(공고일 {ctx.announcement_date}, 규칙 {rule.effective_from}~{rule.effective_until or '현재'})"
        )
        outcomes.append(MatchOutcome.NO_MATCH)
    else:
        reasons.append(f"유효기간 내(규칙 {rule.effective_from}~{rule.effective_until or '현재'})")

    outcomes.append(_match_field(rule.procurement_type, ctx.procurement_type, "입찰 대분류", reasons))
    outcomes.append(_match_field(rule.issuing_authority_type, ctx.issuing_authority_type, "발주기관 유형", reasons))
    outcomes.append(_match_field(rule.contract_method, ctx.contract_method, "계약방법", reasons))
    outcomes.append(_match_field(rule.award_method, ctx.award_method, "낙찰자 결정방식", reasons))

    app = rule.applicability
    if app.amount_basis is not None:
        amount = ctx.amount_for(app.amount_basis)
        if amount is None:
            reasons.append(f"금액 구간 판정용 {app.amount_basis.value} 미확인")
            outcomes.append(MatchOutcome.UNDETERMINED)
        elif (app.amount_min is not None and amount < app.amount_min) or (
            app.amount_max_exclusive is not None and amount >= app.amount_max_exclusive
        ):
            reasons.append(f"금액 구간 밖({app.amount_basis.value}={amount})")
            outcomes.append(MatchOutcome.NO_MATCH)
        else:
            reasons.append(f"금액 구간 내({app.amount_basis.value}={amount})")
    if app.region_codes is not None:
        if ctx.region_code is None:
            reasons.append("지역 미확인")
            outcomes.append(MatchOutcome.UNDETERMINED)
        elif ctx.region_code not in app.region_codes:
            reasons.append(f"지역 불일치({ctx.region_code})")
            outcomes.append(MatchOutcome.NO_MATCH)
    if app.industry_codes is not None:
        if ctx.industry_code is None:
            reasons.append("업종 미확인")
            outcomes.append(MatchOutcome.UNDETERMINED)
        elif ctx.industry_code not in app.industry_codes:
            reasons.append(f"업종 불일치({ctx.industry_code})")
            outcomes.append(MatchOutcome.NO_MATCH)

    if MatchOutcome.NO_MATCH in outcomes:
        outcome = MatchOutcome.NO_MATCH
    elif MatchOutcome.UNDETERMINED in outcomes:
        outcome = MatchOutcome.UNDETERMINED
    else:
        outcome = MatchOutcome.MATCH
    return RuleMatch(rule, outcome, tuple(reasons))


def select_rules(rules: Iterable[RuleDefinition], ctx: NoticeContext) -> RuleSelection:
    results = [match_rule(r, ctx) for r in rules]
    matches = tuple(m for m in results if m.outcome is MatchOutcome.MATCH)
    undetermined = tuple(m for m in results if m.outcome is MatchOutcome.UNDETERMINED)
    warnings: list[str] = []
    if not matches and not undetermined:
        warnings.append("NO_RULE: 이 공고에 적용할 수 있는 등록 규칙이 없습니다.")
    if len(matches) > 1:
        warnings.append("AMBIGUOUS_RULE: 여러 규칙이 동시에 일치합니다. 사용자가 적용 규칙을 직접 지정해야 합니다.")
    if undetermined:
        warnings.append("UNDETERMINED_RULE: 공고 정보가 부족해 적용 여부를 판단할 수 없는 규칙이 있습니다.")
    return RuleSelection(matches, undetermined, tuple(warnings))


# ---------------------------------------------------------------- 평가


class RuleBlockedError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuleEvaluation:
    rule_code: str
    rule_version: str
    verification_status: VerificationStatus
    result: CalcResult
    definitive: bool
    flags: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "rule_code": self.rule_code,
            "rule_version": self.rule_version,
            "verification_status": self.verification_status.value,
            "result": self.result.to_dict(),
            "definitive": self.definitive,
            "flags": list(self.flags),
        }


def _rounding(rule: RuleDefinition) -> RoundingRule | None:
    if rule.rounding_rule is None:
        return None
    rr = rule.rounding_rule
    return RoundingRule(mode=RoundingMode(rr.mode), unit=rr.unit, source=rr.source)


def _simple_lower_limit(rule: RuleDefinition, inputs: dict[str, Any]) -> CalcResult:
    """낙찰하한금액 = 기준가격 × 낙찰하한율 (단순 하한율 방식)

    params: lower_limit_rate_pct(필수), reference("estimated_price" 또는 "base_amount")
    inputs: reference_price, price_status
    """
    params = rule.formula_definition.params
    if "lower_limit_rate_pct" not in params:
        raise CalcInputError("formula_definition.params.lower_limit_rate_pct", "규칙에 낙찰하한율이 없습니다.")
    basis = RateBasis(params.get("reference", RateBasis.ESTIMATED_PRICE.value))
    if "price_status" not in inputs:
        raise CalcInputError("price_status", "기준가격의 확정 여부(price_status)를 지정해야 합니다.")
    return lower_limit_amount(
        inputs.get("reference_price"),
        str(params["lower_limit_rate_pct"]),
        rate_unit=RateUnit.PERCENT,
        reference_basis=basis,
        price_status=PriceStatus(inputs["price_status"]),
        rounding=_rounding(rule),
    )


def _a_value_lower_limit(rule: RuleDefinition, inputs: dict[str, Any]) -> CalcResult:
    """낙찰하한금액 = A값 + (예정가격 − A값) × 낙찰하한율

    params: lower_limit_rate_pct(필수)
    inputs: reference_price(예정가격), a_value(공고 명시 A값, 필수), price_status
    """
    params = rule.formula_definition.params
    if "lower_limit_rate_pct" not in params:
        raise CalcInputError("formula_definition.params.lower_limit_rate_pct", "규칙에 낙찰하한율이 없습니다.")
    if "price_status" not in inputs:
        raise CalcInputError("price_status", "기준가격의 확정 여부(price_status)를 지정해야 합니다.")
    if inputs.get("a_value") is None:
        raise CalcInputError("a_value", "A값 적용 규칙입니다. 공고문에 명시된 A값을 입력해야 합니다.")
    return lower_limit_amount_with_a_value(
        inputs.get("reference_price"),
        str(params["lower_limit_rate_pct"]),
        inputs["a_value"],
        price_status=PriceStatus(inputs["price_status"]),
        rounding=_rounding(rule),
    )


FORMULA_MODULES: dict[str, Callable[[RuleDefinition, dict[str, Any]], CalcResult]] = {
    "simple_lower_limit": _simple_lower_limit,
    "a_value_lower_limit": _a_value_lower_limit,
}


def evaluate_rule(rule: RuleDefinition, inputs: dict[str, Any], *, block_unverified: bool = False) -> RuleEvaluation:
    if rule.verification_status is VerificationStatus.RETIRED:
        raise RuleBlockedError(f"사용 중지된 규칙입니다: {rule.rule_code}")
    if rule.verification_status is not VerificationStatus.VERIFIED and block_unverified:
        raise RuleBlockedError(f"미검증 규칙은 사용할 수 없도록 설정되어 있습니다: {rule.rule_code}")
    module = FORMULA_MODULES.get(rule.formula_definition.module)
    if module is None:
        raise CalcInputError("formula_definition.module", f"등록되지 않은 산식 모듈: {rule.formula_definition.module}")

    result = module(rule, inputs)
    flags: list[str] = []
    if rule.verification_status is not VerificationStatus.VERIFIED:
        flags.append("UNVERIFIED_RULE: 원문 규정과 대조 확인되지 않은 규칙으로 계산했습니다. 확정 결과로 사용하지 마세요.")
    if rule.rounding_rule is None:
        flags.append("ROUNDING_RULE_UNKNOWN: 규칙에 금액 처리 방식이 등록되어 있지 않습니다.")
    if result.assumption_based:
        flags.append("ASSUMPTION_BASED: 기준가격이 확정값이 아닙니다.")
    definitive = (
        rule.verification_status is VerificationStatus.VERIFIED
        and not result.assumption_based
        and rule.rounding_rule is not None
    )
    return RuleEvaluation(rule.rule_code, rule.source_version, rule.verification_status, result, definitive, tuple(flags))

