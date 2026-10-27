"""투찰 시나리오(보수·중립·공격·사용자 정의).

방법
- 예정가격은 개찰 전에는 알 수 없다. 그래서 같은 조건(대분류·발주기관 유형·계약방법·결정방식·하한율)의
  과거 사정률 분포에서 백분위수를 골라 '가정 예정가격'을 만들고, 그 가정에서의 낙찰하한금액 이상이 되도록
  후보 투찰금액을 계산한다. 모든 시나리오 결과는 가정 기반 분석이다.
  - 보수: 사정률 상위(기본 80 백분위) 가정 → 실제 예정가격이 높게 나와도 하한 미달 위험이 낮은 쪽
  - 중립: 중앙값(50 백분위)
  - 공격: 사정률 하위(기본 20 백분위) 가정 → 금액은 낮지만 하한 미달 위험이 큰 쪽
- 후보금액마다 '과거 사정률 n건을 이 공고 기초금액에 적용하면 하한 미달 몇 건, 예정가격 초과 몇 건'을 센다.
  이는 과거 관측의 재적용 건수이며 낙찰 확률이 아니다. 다른 업체의 투찰과 적격심사 점수는 반영하지 않는다.
- 표본이 MIN_SAMPLES 미만이면 백분위 시나리오를 만들지 않는다(사용자 정의 시나리오만 평가).
- 원 미만은 올림한다. 가정 하한금액보다 낮아지지 않게 하려는 처리이며 법정 단수처리 규칙이 아니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Any

from ..calc import ASSUMPTION_LABEL, RoundingRule, apply_rounding, to_decimal
from ..calc.errors import CalcInputError
from ..calc.money import require_positive
from ..stats import summarize
from .cost import CostSheet, evaluate_profit

MIN_SAMPLES = 10
SCENARIO_PRESETS = {"conservative": Decimal(80), "moderate": Decimal(50), "aggressive": Decimal(20)}
SCENARIO_LABELS = {"conservative": "보수", "moderate": "중립", "aggressive": "공격", "custom": "사용자 정의"}
Q6 = Decimal("0.000001")

DISCLAIMER = (
    "가정 기반 분석입니다. 예정가격은 개찰 전에 알 수 없으며, 이 결과는 낙찰을 보장하거나 낙찰 확률을 뜻하지 않습니다. "
    "다른 업체의 투찰, 적격심사 점수, 공고별 특수 조건은 반영되지 않았습니다. 투찰은 사용자가 직접 판단해 제출하세요."
)


@dataclass(frozen=True)
class LowerLimitSpec:
    """낙찰하한 산식. source: rule(등록 규칙) / notice(공고 명시) / user_assumed(사용자 입력)."""

    rate_pct: Decimal
    source: str
    a_value: Decimal | None = None
    rounding: RoundingRule | None = None
    rule_code: str | None = None
    rule_version: str | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        if not (Decimal(0) < self.rate_pct <= Decimal(100)):
            raise CalcInputError("lower_limit_rate", f"낙찰하한율은 0% 초과 100% 이하여야 합니다: {self.rate_pct}%")
        if self.a_value is not None and self.a_value < 0:
            raise CalcInputError("a_value", "A값은 음수일 수 없습니다.")

    @property
    def formula(self) -> str:
        return "A값 + (예정가격 − A값) × 낙찰하한율" if self.a_value is not None else "예정가격 × 낙찰하한율"

    def amount(self, estimated_price: Decimal) -> Decimal:
        a = self.a_value or Decimal(0)
        raw = a + (estimated_price - a) * self.rate_pct / 100
        if self.rounding is None:
            return raw
        value, _ = apply_rounding(raw, self.rounding)
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate_pct": str(self.rate_pct), "source": self.source, "a_value": str(self.a_value) if self.a_value is not None else None,
            "formula": self.formula, "rounding": self.rounding.to_dict() if self.rounding else None,
            "rule_code": self.rule_code, "rule_version": self.rule_version, "verified": self.verified,
        }


@dataclass
class CustomScenario:
    name: str = "custom"
    sajeong_rate_pct: Decimal | None = None  # 가정 사정률로 후보금액 계산
    percentile: Decimal | None = None  # 과거 사정률 백분위로 후보금액 계산
    bid_amount: Decimal | None = None  # 직접 정한 금액을 평가만


@dataclass
class ScenarioRequest:
    base_amount: Decimal
    lower_limit: LowerLimitSpec
    sajeong_samples: Sequence[Decimal]
    presets: dict[str, Decimal] = field(default_factory=lambda: dict(SCENARIO_PRESETS))
    custom: list[CustomScenario] = field(default_factory=list)
    cost: CostSheet | None = None
    bid_vat_included: bool | None = None


def percentile(sorted_values: Sequence[Decimal], p: Decimal) -> Decimal:
    """선형 보간 백분위수(numpy 기본 방식과 같음). Decimal 로 정확히 계산한다."""
    if not sorted_values:
        raise ValueError("빈 표본")
    if not (Decimal(0) <= p <= Decimal(100)):
        raise CalcInputError("percentile", "백분위는 0~100 사이여야 합니다.")
    pos = (len(sorted_values) - 1) * p / 100
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return (sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac).quantize(Q6)


def assumed_estimated_price(base_amount: Decimal, sajeong_pct: Decimal) -> Decimal:
    return base_amount * (1 + sajeong_pct / 100)


def historical_check(amount: Decimal, base_amount: Decimal, spec: LowerLimitSpec, samples: Sequence[Decimal]) -> dict[str, Any]:
    below = above = 0
    for s in samples:
        est = assumed_estimated_price(base_amount, s)
        if amount < spec.amount(est):
            below += 1
        elif amount > est:
            above += 1
    n = len(samples)
    return {
        "n": n,
        "below_lower_limit": below,
        "above_estimated_price": above,
        "within_range": n - below - above,
        "meaning": f"과거 사정률 {n}건을 이 공고 기초금액에 적용했을 때의 건수입니다. 낙찰 확률이 아닙니다.",
    }


def _ceil_won(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_CEILING)


def _scenario(name: str, label: str, method: str, req: ScenarioRequest, samples: Sequence[Decimal], *,
              sajeong: Decimal | None, amount: Decimal | None) -> dict[str, Any]:
    spec = req.lower_limit
    flags: list[str] = []
    out: dict[str, Any] = {"name": name, "label": label, "method": method, "price_status": "scenario"}
    if amount is None:
        assert sajeong is not None
        est = assumed_estimated_price(req.base_amount, sajeong)
        ll = spec.amount(est)
        amount = _ceil_won(ll)
        out.update(assumed_sajeong_rate=str(sajeong), assumed_estimated_price=str(est), assumed_lower_limit=str(ll))
        out["explanation"] = {
            "steps": [
                f"가정 예정가격 = 기초금액 × (1 + 사정률/100) = {req.base_amount} × (1 + {sajeong}/100) = {est}",
                f"가정 하한금액 = {spec.formula} = {ll}",
                f"후보 투찰금액 = 가정 하한금액의 원 미만 올림 = {amount}",
            ],
        }
    else:
        out["explanation"] = {"steps": [f"사용자가 정한 금액 {amount} 를 평가했습니다."]}
    out["candidate_amount"] = str(amount)
    out["bid_rate_vs_base_amount"] = str((amount / req.base_amount * 100).quantize(Q6))
    check = historical_check(amount, req.base_amount, spec, samples)
    out["historical_check"] = check
    if check["n"] and check["below_lower_limit"]:
        flags.append(f"BELOW_LOWER_LIMIT_IN_HISTORY: 과거 사정률 {check['n']}건 중 {check['below_lower_limit']}건에서 하한 미달")
    if check["n"] and check["above_estimated_price"]:
        flags.append(f"ABOVE_ESTIMATED_IN_HISTORY: 과거 사정률 {check['n']}건 중 {check['above_estimated_price']}건에서 예정가격 초과")
    if req.cost is not None:
        profit = evaluate_profit(amount, req.cost, bid_vat_included=req.bid_vat_included)
        out["profit"] = profit
        flags.extend(profit.get("flags", []))
    out["risk_flags"] = flags
    return out


def build_scenarios(req: ScenarioRequest) -> dict[str, Any]:
    base = require_positive(to_decimal(req.base_amount, "base_amount"), "base_amount")
    req.base_amount = base
    samples = sorted(to_decimal(s, "sajeong_samples") for s in req.sajeong_samples)
    warnings: list[str] = [f"ASSUMPTION_BASED: 모든 시나리오는 {ASSUMPTION_LABEL}입니다."]
    spec = req.lower_limit
    if spec.source == "user_assumed":
        warnings.append("ASSUMED_LOWER_LIMIT: 낙찰하한율을 사용자가 입력했습니다. 공고문과 대조하세요.")
    elif spec.source == "notice":
        warnings.append("LOWER_LIMIT_FROM_NOTICE: 공고에 기재된 하한율을 썼습니다. 적용 산식(A값 등)은 공고문과 대조하세요.")
    elif not spec.verified:
        warnings.append("UNVERIFIED_RULE: 원문 규정과 대조 확인되지 않은 규칙의 하한율을 썼습니다.")
    if spec.rounding is None:
        warnings.append("ROUNDING_RULE_UNKNOWN: 하한금액 단수처리 규칙이 없어 원 미만을 그대로 계산했습니다.")

    status = "assumption_based"
    scenarios: list[dict[str, Any]] = []
    if len(samples) < MIN_SAMPLES:
        status = "insufficient_data"
        warnings.append(
            f"INSUFFICIENT_DATA: 같은 조건의 과거 사정률이 {len(samples)}건뿐이라(기준 {MIN_SAMPLES}건) 보수·중립·공격 시나리오를 만들지 않았습니다."
        )
    else:
        for name, p in req.presets.items():
            s = percentile(samples, Decimal(p))
            scenarios.append(_scenario(name, SCENARIO_LABELS.get(name, name), f"과거 사정률 {p} 백분위({s}%) 가정",
                                       req, samples, sajeong=s, amount=None))
    for c in req.custom:
        given = [x is not None for x in (c.sajeong_rate_pct, c.percentile, c.bid_amount)]
        if sum(given) != 1:
            raise CalcInputError("custom", "사용자 정의 시나리오는 사정률·백분위·금액 중 하나만 지정합니다.")
        if c.bid_amount is not None:
            amt = require_positive(to_decimal(c.bid_amount, "custom.bid_amount"), "custom.bid_amount")
            if amt != amt.to_integral_value():
                raise CalcInputError("custom.bid_amount", "투찰금액은 원 단위 정수여야 합니다.")
            scenarios.append(_scenario(c.name, SCENARIO_LABELS["custom"], "사용자 지정 금액 평가", req, samples, sajeong=None, amount=amt))
        elif c.percentile is not None:
            if len(samples) < MIN_SAMPLES:
                raise CalcInputError("custom.percentile", "과거 표본이 부족해 백분위 시나리오를 만들 수 없습니다.")
            s = percentile(samples, to_decimal(c.percentile, "custom.percentile"))
            scenarios.append(_scenario(c.name, SCENARIO_LABELS["custom"], f"과거 사정률 {c.percentile} 백분위({s}%) 가정",
                                       req, samples, sajeong=s, amount=None))
        else:
            s = to_decimal(c.sajeong_rate_pct, "custom.sajeong_rate_pct")
            scenarios.append(_scenario(c.name, SCENARIO_LABELS["custom"], f"사용자 가정 사정률 {s}%", req, samples, sajeong=s, amount=None))

    summary = summarize(samples).to_dict() if samples else {"n": 0}
    return {
        "status": status,
        "label": ASSUMPTION_LABEL,
        "base_amount": str(base),
        "lower_limit": spec.to_dict(),
        "sample": {"n": len(samples), "sajeong_summary": summary},
        "scenarios": scenarios,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
