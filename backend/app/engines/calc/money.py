"""금액·비율 기본 타입과 변환.

모든 금액은 원 단위 Decimal, 모든 비율은 퍼센트(%) 단위 Decimal로 다룬다.
float 입력은 받지 않는다(이진 부동소수점 오차가 금액에 섞이는 것을 막기 위함).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from .errors import CalcInputError


class RateUnit(StrEnum):
    """비율 입력 단위. 87.745 와 0.87745 를 자동으로 추측하지 않고 명시적으로 받는다."""

    PERCENT = "percent"  # 87.745 (%)
    RATIO = "ratio"  # 0.87745


class RoundingMode(StrEnum):
    TRUNCATE = "truncate"  # 절사(0 방향 버림)
    FLOOR = "floor"  # 음의 무한대 방향 버림
    CEIL = "ceil"  # 올림
    HALF_UP = "half_up"  # 사사오입
    NONE = "none"  # 원 미만을 그대로 둔다(규칙 미확인 시)


_DECIMAL_ROUNDING = {
    RoundingMode.TRUNCATE: ROUND_DOWN,
    RoundingMode.FLOOR: ROUND_FLOOR,
    RoundingMode.CEIL: ROUND_CEILING,
    RoundingMode.HALF_UP: ROUND_HALF_UP,
}


@dataclass(frozen=True)
class RoundingRule:
    """금액 처리 규칙. unit 은 처리 단위(원): 1, 10, 100, 1000 ..."""

    mode: RoundingMode
    unit: int = 1
    source: str | None = None  # 규칙 근거(공고문 페이지, 예규 조항 등)

    def __post_init__(self) -> None:
        if self.unit <= 0:
            raise CalcInputError("rounding.unit", "처리 단위는 1원 이상이어야 합니다.")

    def to_dict(self) -> dict:
        return {"mode": self.mode.value, "unit": self.unit, "source": self.source}

    @classmethod
    def from_dict(cls, data: dict | None) -> RoundingRule | None:
        if not data:
            return None
        return cls(mode=RoundingMode(data["mode"]), unit=int(data.get("unit", 1)), source=data.get("source"))


def to_decimal(value: object, field: str) -> Decimal:
    """문자열·int·Decimal 을 Decimal 로 변환한다. float, bool, None 은 거부한다."""
    if value is None:
        raise CalcInputError(field, "값이 없습니다.")
    if isinstance(value, bool) or isinstance(value, float):
        raise CalcInputError(field, "float/bool 은 허용하지 않습니다. 문자열 또는 Decimal 로 전달하세요.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("원", "").replace("%", "")
        if cleaned == "":
            raise CalcInputError(field, "빈 값입니다.")
        try:
            result = Decimal(cleaned)
        except InvalidOperation as exc:
            raise CalcInputError(field, f"숫자로 변환할 수 없습니다: {value!r}") from exc
    else:
        raise CalcInputError(field, f"지원하지 않는 타입입니다: {type(value).__name__}")
    if not result.is_finite():
        raise CalcInputError(field, "유한한 숫자가 아닙니다.")
    return result


def require_positive(value: Decimal, field: str) -> Decimal:
    if value <= 0:
        raise CalcInputError(field, "0보다 커야 합니다.")
    return value


def require_non_negative(value: Decimal, field: str) -> Decimal:
    if value < 0:
        raise CalcInputError(field, "음수일 수 없습니다.")
    return value


def to_percent(value: object, unit: RateUnit, field: str) -> Decimal:
    """비율을 퍼센트 단위로 정규화한다."""
    number = to_decimal(value, field)
    if unit is RateUnit.PERCENT:
        return number
    if unit is RateUnit.RATIO:
        return number * 100
    raise CalcInputError(field, f"알 수 없는 비율 단위: {unit}")


def percent_to_ratio(percent: Decimal) -> Decimal:
    return percent / 100


def apply_rounding(amount: Decimal, rule: RoundingRule | None) -> tuple[Decimal, list[str]]:
    """금액 처리 규칙을 적용한다.

    규칙이 없으면 값을 바꾸지 않고 경고를 돌려준다. 법정 규칙을 임의로 만들지 않기 위함이다.
    """
    if rule is None:
        warnings = []
        if amount == amount.to_integral_value():
            return amount.quantize(Decimal(1)), warnings
        warnings.append("ROUNDING_RULE_UNKNOWN: 금액 처리(절사·반올림) 규칙이 확인되지 않아 원 미만 값을 그대로 표시합니다.")
        return amount, warnings
    if rule.mode is RoundingMode.NONE:
        return amount, []
    unit = Decimal(rule.unit)
    quotient = (amount / unit).quantize(Decimal(1), rounding=_DECIMAL_ROUNDING[rule.mode])
    return quotient * unit, []
