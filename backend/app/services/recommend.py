"""투찰 시나리오 서비스: 공고 → 하한 산식 결정 → 같은 조건 과거 사정률 → 시나리오 계산."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CompanyCost, ProcurementNotice
from app.engines.calc import CalcInputError, RoundingMode, RoundingRule
from app.engines.recommend import COST_ITEMS, CostSheet, LowerLimitSpec
from app.engines.rules import NoticeContext, RuleBlockedError, VerificationStatus, select_rules
from app.engines.stats import Record
from app.engines.stats.descriptive import stratum_of
from app.services.analysis import Filters, load_records
from app.services.rules import list_rules, to_definition

SUPPORTED_MODULES = {"simple_lower_limit", "a_value_lower_limit"}


@dataclass
class LowerLimitOverride:
    rate_pct: Decimal | None = None  # 사용자가 공고문에서 확인한 하한율(가정값으로 표시)
    a_value: Decimal | None = None  # 공고문에 명시된 A값


def notice_context(n: ProcurementNotice) -> NoticeContext:
    return NoticeContext(
        announcement_date=n.announcement_date, procurement_type=n.procurement_type,
        issuing_authority_type=n.issuing_authority_type, contract_method=n.contract_method, award_method=n.award_method,
        presumed_price=n.presumed_price, base_amount=n.base_amount, region_code=n.region_code, industry_code=n.industry_code,
    )


def resolve_lower_limit(session: Session, n: ProcurementNotice, override: LowerLimitOverride) -> tuple[LowerLimitSpec, dict[str, Any]]:
    """하한 산식 결정 순서: 사용자 입력 > 공고에 맞는 등록 규칙(하나만 일치할 때) > 공고에 기재된 하한율."""
    selection = select_rules([to_definition(r) for r in list_rules(session)], notice_context(n))
    info: dict[str, Any] = {
        "rule_selection_warnings": list(selection.warnings),
        "matched_rules": [m.rule.rule_code for m in selection.matches],
        "undetermined_rules": [m.rule.rule_code for m in selection.undetermined],
    }
    if override.rate_pct is not None:
        return LowerLimitSpec(rate_pct=override.rate_pct, source="user_assumed", a_value=override.a_value), info
    rule = selection.selected
    if rule is not None and rule.formula_definition.module in SUPPORTED_MODULES:
        if rule.verification_status is not VerificationStatus.VERIFIED and get_settings().block_unverified_rules:
            raise RuleBlockedError(f"미검증 규칙은 사용할 수 없도록 설정되어 있습니다: {rule.rule_code}")
        params = rule.formula_definition.params
        if rule.formula_definition.module == "simple_lower_limit" and params.get("reference", "estimated_price") != "estimated_price":
            raise CalcInputError("rule", "예정가격 기준이 아닌 하한 규칙은 시나리오 계산에 쓸 수 없습니다.")
        a_value = None
        if rule.formula_definition.module == "a_value_lower_limit":
            if override.a_value is None:
                raise CalcInputError("a_value", f"규칙 {rule.rule_code} 는 A값 적용 산식입니다. 공고문에 명시된 A값을 입력하세요.")
            a_value = override.a_value
        rr = rule.rounding_rule
        rounding = RoundingRule(mode=RoundingMode(rr.mode), unit=rr.unit, source=rr.source) if rr else None
        return LowerLimitSpec(
            rate_pct=Decimal(str(params["lower_limit_rate_pct"])), source="rule", a_value=a_value, rounding=rounding,
            rule_code=rule.rule_code, rule_version=rule.source_version, verified=rule.verification_status is VerificationStatus.VERIFIED,
        ), info
    if n.lower_limit_rate is not None:
        return LowerLimitSpec(rate_pct=n.lower_limit_rate, source="notice", a_value=override.a_value), info
    raise CalcInputError("lower_limit_rate", "낙찰하한율을 확인할 수 없습니다. 적용 규칙을 등록하거나 공고문의 하한율을 입력하세요.")


def history_for(session: Session, n: ProcurementNotice, *, period: str | None, extra: dict[str, Any]) -> tuple[list[Record], list[Decimal], Filters]:
    """같은 조건(대분류·기관 유형·계약방법·결정방식·공고 하한율)의 과거 사정률. 대상 공고의 입찰마감 이전 개찰 건만 쓴다."""
    missing = [k for k in ("procurement_type", "issuing_authority_type", "contract_method", "award_method") if getattr(n, k) is None]
    if missing:
        raise CalcInputError("notice", f"공고 조건이 확인되지 않아 같은 조건의 과거 자료를 고를 수 없습니다: {missing}")
    f = Filters(period=period, as_of=n.bid_deadline or n.opening_date or datetime.now(UTC),
                procurement_type=n.procurement_type, issuing_authority_type=n.issuing_authority_type,
                contract_method=n.contract_method, award_method=n.award_method, **extra)
    f.resolved_period()
    records = [r for r in load_records(session, f) if r.notice_id != n.id]
    target_key = stratum_of(_as_record(n), "sajeong_rate")
    same = [r for r in records if stratum_of(r, "sajeong_rate") == target_key]
    return same, [r.sajeong_rate for r in same if r.sajeong_rate is not None], f


def _as_record(n: ProcurementNotice) -> Record:
    return Record(
        notice_id=n.id, opening_date=None, announcement_date=None, procurement_type=n.procurement_type,
        issuing_authority_type=n.issuing_authority_type, contract_method=n.contract_method, award_method=n.award_method,
        agency_name=None, demand_agency_name=None, industry_name=None, region_name=None, base_amount=None, presumed_price=None,
        estimated_price=None, sajeong_rate=None, winning_rate=None, rate_basis=None, bid_count=None,
        lower_limit_rate=n.lower_limit_rate, source_name="",
    )


def cost_sheet_from_row(row: CompanyCost) -> CostSheet:
    return CostSheet(items={k: getattr(row, k) for k in COST_ITEMS}, vat_treatment=row.vat_treatment,
                     target_profit=row.target_profit, target_profit_rate=row.target_profit_rate)
