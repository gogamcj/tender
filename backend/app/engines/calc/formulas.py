"""법정 계산 엔진의 기본 산식.

화면·DB·HTTP 에 의존하지 않는 순수 함수들이다. 각 함수는 CalcResult 를 돌려주며,
결과에는 사용한 산식, 입력값, 경고, 기준 가격의 확정 여부가 함께 담겨 재현할 수 있다.

내부 정의
- 사정률(%) = (예정가격 − 기초금액) ÷ 기초금액 × 100
- 낙찰하한금액 = 기준가격 × 낙찰하한율
- 투찰률(%) = 투찰금액 ÷ 기준금액 × 100  (기준금액이 예정가격인지 기초금액인지 명시)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from .errors import CalcInputError
from .money import (
    RateUnit,
    RoundingRule,
    apply_rounding,
    require_non_negative,
    require_positive,
    to_decimal,
    to_percent,
)

# 비율의 내부 저장 정밀도(소수 6자리). 법정 처리 규칙이 아니라 저장 형식이다.
RATE_QUANTUM = Decimal("0.000001")


class PriceStatus(StrEnum):
    """기준 가격(주로 예정가격)의 성격."""

    ACTUAL = "actual"  # 개찰 후 확정된 실제 예정가격
    USER_ASSUMED = "user_assumed"  # 사용자가 입력한 가정값
    HISTORICAL_ESTIMATE = "historical_estimate"  # 과거 데이터 기반 예상값
    SCENARIO = "scenario"  # 통계적 시나리오 값
    UNKNOWN = "unknown"


class RateBasis(StrEnum):
    """비율을 계산한 기준 금액."""

    ESTIMATED_PRICE = "estimated_price"  # 예정가격
    BASE_AMOUNT = "base_amount"  # 기초금액
    PRESUMED_PRICE = "presumed_price"  # 추정가격


RATE_BASIS_LABEL = {
    RateBasis.ESTIMATED_PRICE: "예정가격",
    RateBasis.BASE_AMOUNT: "기초금액",
    RateBasis.PRESUMED_PRICE: "추정가격",
}

ASSUMPTION_LABEL = "가정 기반 분석"


@dataclass(frozen=True)
class CalcResult:
    name: str
    value: Decimal
    unit: str  # "KRW" 또는 "%"
    formula: str
    inputs: dict[str, object]
    price_status: PriceStatus = PriceStatus.ACTUAL
    warnings: tuple[str, ...] = field(default_factory=tuple)
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def assumption_based(self) -> bool:
        return self.price_status is not PriceStatus.ACTUAL

    @property
    def status_label(self) -> str:
        return ASSUMPTION_LABEL if self.assumption_based else "확정값 기반"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": str(self.value),
            "unit": self.unit,
            "formula": self.formula,
            "inputs": dict(self.inputs),
            "price_status": self.price_status.value,
            "assumption_based": self.assumption_based,
            "status_label": self.status_label,
            "warnings": list(self.warnings),
            "extra": dict(self.extra),
        }


def _quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_EVEN)


def sajeong_rate(base_amount: object, estimated_price: object, *, price_status: PriceStatus = PriceStatus.ACTUAL) -> CalcResult:
    """사정률(%) = (예정가격 − 기초금액) ÷ 기초금액 × 100"""
    base = require_positive(to_decimal(base_amount, "base_amount"), "base_amount")
    price = require_positive(to_decimal(estimated_price, "estimated_price"), "estimated_price")
    rate = _quantize_rate((price - base) / base * 100)
    return CalcResult(
        name="sajeong_rate",
        value=rate,
        unit="%",
        formula="(예정가격 − 기초금액) ÷ 기초금액 × 100",
        inputs={"base_amount": str(base), "estimated_price": str(price)},
        price_status=price_status,
    )


def estimated_price_from_sajeong(
    base_amount: object,
    sajeong_rate_value: object,
    *,
    rate_unit: RateUnit = RateUnit.PERCENT,
    rounding: RoundingRule | None = None,
    price_status: PriceStatus = PriceStatus.SCENARIO,
) -> CalcResult:
    """가정 예정가격 = 기초금액 × (1 + 사정률/100).

    사정률로부터 만든 예정가격은 실제 확정 예정가격이 아니므로 기본 상태는 SCENARIO 이다.
    """
    if price_status is PriceStatus.ACTUAL:
        raise CalcInputError("price_status", "사정률로 역산한 값은 확정 예정가격이 될 수 없습니다.")
    base = require_positive(to_decimal(base_amount, "base_amount"), "base_amount")
    rate_pct = to_percent(sajeong_rate_value, rate_unit, "sajeong_rate")
    if rate_pct <= -100:
        raise CalcInputError("sajeong_rate", "사정률이 -100% 이하이면 예정가격이 0 이하가 됩니다.")
    raw = base * (1 + rate_pct / 100)
    value, warnings = apply_rounding(raw, rounding)
    return CalcResult(
        name="assumed_estimated_price",
        value=value,
        unit="KRW",
        formula="기초금액 × (1 + 사정률 ÷ 100)",
        inputs={
            "base_amount": str(base),
            "sajeong_rate_pct": str(rate_pct),
            "rounding": rounding.to_dict() if rounding else None,
        },
        price_status=price_status,
        warnings=tuple(warnings),
        extra={"unrounded": str(raw)},
    )


def lower_limit_amount(
    reference_price: object,
    lower_limit_rate: object,
    *,
    rate_unit: RateUnit = RateUnit.PERCENT,
    reference_basis: RateBasis = RateBasis.ESTIMATED_PRICE,
    price_status: PriceStatus,
    rounding: RoundingRule | None = None,
) -> CalcResult:
    """낙찰하한금액 = 기준가격 × 낙찰하한율.

    price_status 는 필수 인자다. 기준가격이 확정값인지 가정값인지 호출자가 반드시 밝혀야 한다.
    """
    ref = require_positive(to_decimal(reference_price, "reference_price"), "reference_price")
    rate_pct = to_percent(lower_limit_rate, rate_unit, "lower_limit_rate")
    if not (Decimal(0) < rate_pct <= Decimal(100)):
        raise CalcInputError("lower_limit_rate", f"낙찰하한율은 0% 초과 100% 이하여야 합니다: {rate_pct}%")
    raw = ref * rate_pct / 100
    value, warnings = apply_rounding(raw, rounding)
    if price_status is not PriceStatus.ACTUAL:
        warnings.append(f"ASSUMPTION_BASED: 기준가격이 확정값이 아니므로({price_status.value}) 하한금액도 {ASSUMPTION_LABEL} 결과입니다.")
    return CalcResult(
        name="lower_limit_amount",
        value=value,
        unit="KRW",
        formula=f"{RATE_BASIS_LABEL[reference_basis]} × 낙찰하한율",
        inputs={
            "reference_price": str(ref),
            "reference_basis": reference_basis.value,
            "lower_limit_rate_pct": str(rate_pct),
            "rounding": rounding.to_dict() if rounding else None,
        },
        price_status=price_status,
        warnings=tuple(warnings),
        extra={"unrounded": str(raw)},
    )


def bid_rate(
    bid_amount: object,
    reference_amount: object,
    *,
    basis: RateBasis,
    price_status: PriceStatus,
) -> CalcResult:
    """투찰률(%) = 투찰금액 ÷ 기준금액 × 100. basis 로 기준금액의 종류를 반드시 밝힌다."""
    bid = require_positive(to_decimal(bid_amount, "bid_amount"), "bid_amount")
    ref = require_positive(to_decimal(reference_amount, "reference_amount"), "reference_amount")
    warnings: list[str] = []
    if bid != bid.to_integral_value():
        warnings.append("NON_INTEGER_BID: 투찰금액에 원 미만 금액이 있습니다.")
    if price_status is not PriceStatus.ACTUAL:
        warnings.append(f"ASSUMPTION_BASED: 기준금액이 확정값이 아니므로 투찰률도 {ASSUMPTION_LABEL} 결과입니다.")
    return CalcResult(
        name="bid_rate",
        value=_quantize_rate(bid / ref * 100),
        unit="%",
        formula=f"투찰금액 ÷ {RATE_BASIS_LABEL[basis]} × 100",
        inputs={"bid_amount": str(bid), "reference_amount": str(ref), "basis": basis.value},
        price_status=price_status,
        warnings=tuple(warnings),
    )


def bid_amount_from_rate(
    reference_amount: object,
    rate: object,
    *,
    rate_unit: RateUnit = RateUnit.PERCENT,
    basis: RateBasis,
    price_status: PriceStatus,
    rounding: RoundingRule | None = None,
) -> CalcResult:
    """후보 투찰금액 = 기준금액 × 투찰률 ÷ 100"""
    ref = require_positive(to_decimal(reference_amount, "reference_amount"), "reference_amount")
    rate_pct = require_positive(to_percent(rate, rate_unit, "rate"), "rate")
    raw = ref * rate_pct / 100
    value, warnings = apply_rounding(raw, rounding)
    if price_status is not PriceStatus.ACTUAL:
        warnings.append(f"ASSUMPTION_BASED: 기준금액이 확정값이 아니므로 {ASSUMPTION_LABEL} 결과입니다.")
    return CalcResult(
        name="bid_amount",
        value=value,
        unit="KRW",
        formula=f"{RATE_BASIS_LABEL[basis]} × 투찰률 ÷ 100",
        inputs={"reference_amount": str(ref), "rate_pct": str(rate_pct), "basis": basis.value},
        price_status=price_status,
        warnings=tuple(warnings),
        extra={"unrounded": str(raw)},
    )


@dataclass(frozen=True)
class VatSplit:
    supply_amount: Decimal  # 공급가액
    vat_amount: Decimal  # 부가가치세
    total_amount: Decimal  # 합계
    vat_rate_pct: Decimal
    warnings: tuple[str, ...]
    source: str  # "stated"(공고 명시값) 또는 "computed"

    def to_dict(self) -> dict:
        return {
            "supply_amount": str(self.supply_amount),
            "vat_amount": str(self.vat_amount),
            "total_amount": str(self.total_amount),
            "vat_rate_pct": str(self.vat_rate_pct),
            "warnings": list(self.warnings),
            "source": self.source,
        }


def split_vat(
    amount: object,
    *,
    vat_included: bool | None,
    vat_rate_pct: object = "10",
    stated_vat_amount: object | None = None,
    rounding: RoundingRule | None = None,
) -> VatSplit:
    """공급가액과 세액을 분리한다.

    - vat_included 가 None(포함 여부 미확인)이면 계산을 거부한다. 중복 계산을 막기 위함이다.
    - 공고에 세액이 명시되어 있으면(stated_vat_amount) 그 값을 우선 사용한다.
    - 세액 단수 처리 규칙이 없으면 원 미만 값을 그대로 두고 경고한다.
    """
    if vat_included is None:
        raise CalcInputError("vat_included", "부가가치세 포함 여부가 확인되지 않아 분리 계산을 하지 않습니다.")
    value = require_non_negative(to_decimal(amount, "amount"), "amount")
    rate = require_non_negative(to_decimal(vat_rate_pct, "vat_rate_pct"), "vat_rate_pct")
    warnings: list[str] = []

    if stated_vat_amount is not None:
        vat = require_non_negative(to_decimal(stated_vat_amount, "stated_vat_amount"), "stated_vat_amount")
        if vat_included:
            if vat > value:
                raise CalcInputError("stated_vat_amount", "세액이 총액보다 큽니다.")
            supply, total = value - vat, value
        else:
            supply, total = value, value + vat
        expected = supply * rate / 100
        if supply > 0 and abs(expected - vat) >= 1:
            warnings.append(f"VAT_MISMATCH: 명시 세액({vat})이 공급가액×{rate}%({expected})와 1원 이상 다릅니다.")
        return VatSplit(supply, vat, total, rate, tuple(warnings), "stated")

    if vat_included:
        supply_raw = value * 100 / (100 + rate)
        supply, w = apply_rounding(supply_raw, rounding)
        warnings.extend(w)
        vat = value - supply
        total = value
    else:
        vat_raw = value * rate / 100
        vat, w = apply_rounding(vat_raw, rounding)
        warnings.extend(w)
        supply = value
        total = value + vat
    return VatSplit(supply, vat, total, rate, tuple(warnings), "computed")


@dataclass(frozen=True)
class BoundsCheck:
    ok: bool
    violations: tuple[str, ...]


def check_amount_bounds(amount: object, *, minimum: object | None = None, maximum: object | None = None, field_name: str = "amount") -> BoundsCheck:
    """금액의 최소·최대 경계를 검증한다. 경계값과 같으면 통과(포함)로 본다."""
    value = to_decimal(amount, field_name)
    violations: list[str] = []
    if value < 0:
        violations.append(f"{field_name}: 음수 금액입니다.")
    if value != value.to_integral_value():
        violations.append(f"{field_name}: 원 미만 금액이 포함되어 있습니다.")
    if minimum is not None and value < to_decimal(minimum, "minimum"):
        violations.append(f"{field_name}: 최소값({minimum}) 미만입니다.")
    if maximum is not None and value > to_decimal(maximum, "maximum"):
        violations.append(f"{field_name}: 최대값({maximum}) 초과입니다.")
    return BoundsCheck(ok=not violations, violations=tuple(violations))
