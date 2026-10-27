"""계산 엔진 테스트.

기대값은 테스트 안에서 분수(Fraction)로 독립 계산하거나 손으로 검산한 값이다.
실제 공고문의 공식 예시와의 교차 검증은 docs/known-limitations.md 에 '미완료'로 기록되어 있다.
"""

from decimal import Decimal
from fractions import Fraction

import pytest

from app.engines.calc import (
    CalcInputError,
    PriceStatus,
    RateBasis,
    RateUnit,
    RoundingMode,
    RoundingRule,
    apply_rounding,
    bid_amount_from_rate,
    bid_rate,
    check_amount_bounds,
    estimated_price_from_sajeong,
    lower_limit_amount,
    sajeong_rate,
    split_vat,
    to_decimal,
    to_percent,
)

TRUNC = RoundingRule(RoundingMode.TRUNCATE, 1, source="테스트")


# ------------------------------------------------------------------ 낙찰하한금액


def test_lower_limit_exact_integer():
    r = lower_limit_amount("99500000", "87.745", price_status=PriceStatus.ACTUAL, rounding=TRUNC)
    assert r.value == Decimal("87306275")
    assert r.unit == "KRW"
    assert not r.assumption_based
    assert r.warnings == ()


def test_lower_limit_truncation_vs_ceil_vs_half_up():
    # 123,456,789 × 87.745% = 108,327,159.50805
    exact = Fraction(123456789) * Fraction(87745, 100000)
    assert exact == Fraction("108327159.50805")
    args = ("123456789", "87.745")
    assert lower_limit_amount(*args, price_status=PriceStatus.ACTUAL, rounding=TRUNC).value == Decimal("108327159")
    ceil = RoundingRule(RoundingMode.CEIL, 1)
    assert lower_limit_amount(*args, price_status=PriceStatus.ACTUAL, rounding=ceil).value == Decimal("108327160")
    half = RoundingRule(RoundingMode.HALF_UP, 1)
    assert lower_limit_amount(*args, price_status=PriceStatus.ACTUAL, rounding=half).value == Decimal("108327160")


def test_lower_limit_without_rounding_rule_keeps_fraction_and_warns():
    r = lower_limit_amount("123456789", "87.745", price_status=PriceStatus.ACTUAL)
    assert r.value == Decimal("108327159.50805")
    assert any(w.startswith("ROUNDING_RULE_UNKNOWN") for w in r.warnings)


def test_lower_limit_ratio_unit_equals_percent_unit():
    a = lower_limit_amount("99500000", "87.745", price_status=PriceStatus.ACTUAL, rounding=TRUNC)
    b = lower_limit_amount("99500000", "0.87745", rate_unit=RateUnit.RATIO, price_status=PriceStatus.ACTUAL, rounding=TRUNC)
    assert a.value == b.value


def test_lower_limit_assumed_price_is_marked():
    r = lower_limit_amount("99500000", "87.745", price_status=PriceStatus.USER_ASSUMED, rounding=TRUNC)
    assert r.assumption_based
    assert r.status_label == "가정 기반 분석"
    assert any(w.startswith("ASSUMPTION_BASED") for w in r.warnings)


def test_lower_limit_requires_price_status():
    with pytest.raises(TypeError):
        lower_limit_amount("99500000", "87.745")  # type: ignore[call-arg]


@pytest.mark.parametrize("rate", ["0", "-1", "100.0001", "150"])
def test_lower_limit_rejects_out_of_range_rate(rate):
    with pytest.raises(CalcInputError) as e:
        lower_limit_amount("100000000", rate, price_status=PriceStatus.ACTUAL)
    assert e.value.field == "lower_limit_rate"


def test_lower_limit_rate_boundary_100_is_allowed():
    r = lower_limit_amount("100000000", "100", price_status=PriceStatus.ACTUAL, rounding=TRUNC)
    assert r.value == Decimal("100000000")


@pytest.mark.parametrize("price", ["0", "-1", None, "", "abc"])
def test_lower_limit_rejects_bad_reference(price):
    with pytest.raises(CalcInputError):
        lower_limit_amount(price, "87.745", price_status=PriceStatus.ACTUAL)


def test_lower_limit_basis_appears_in_formula():
    r = lower_limit_amount(
        "100000000", "87.745", reference_basis=RateBasis.BASE_AMOUNT, price_status=PriceStatus.ACTUAL, rounding=TRUNC
    )
    assert r.formula.startswith("기초금액")
    assert r.inputs["reference_basis"] == "base_amount"


# ------------------------------------------------------------------ 사정률


def test_sajeong_rate_definition():
    # (98,765,432 − 100,000,000) ÷ 100,000,000 × 100 = −1.23456800 (정확히 −154321/125000)
    r = sajeong_rate("100000000", "98765432")
    assert r.value == Decimal("-1.234568")
    assert r.unit == "%"


def test_sajeong_rate_zero_and_positive():
    assert sajeong_rate("100000000", "100000000").value == Decimal("0.000000")
    assert sajeong_rate("100000000", "102000000").value == Decimal("2.000000")


def test_sajeong_rate_rejects_zero_base():
    with pytest.raises(CalcInputError) as e:
        sajeong_rate("0", "100")
    assert e.value.field == "base_amount"


def test_estimated_price_from_sajeong_roundtrip():
    r = estimated_price_from_sajeong("100000000", "-1.234568", rounding=TRUNC)
    assert r.value == Decimal("98765432")
    assert r.price_status is PriceStatus.SCENARIO
    assert r.assumption_based


def test_estimated_price_from_sajeong_cannot_be_actual():
    with pytest.raises(CalcInputError):
        estimated_price_from_sajeong("100000000", "1", price_status=PriceStatus.ACTUAL)


def test_estimated_price_from_sajeong_rejects_minus_100():
    with pytest.raises(CalcInputError):
        estimated_price_from_sajeong("100000000", "-100")


def test_estimated_price_from_sajeong_ratio_unit():
    r = estimated_price_from_sajeong("100000000", "0.02", rate_unit=RateUnit.RATIO, rounding=TRUNC)
    assert r.value == Decimal("102000000")


# ------------------------------------------------------------------ 투찰률


def test_bid_rate_basis_is_required_and_recorded():
    r = bid_rate("87654321", "99500000", basis=RateBasis.ESTIMATED_PRICE, price_status=PriceStatus.ACTUAL)
    # 87,654,321 ÷ 99,500,000 × 100 = 88.0947949748... → 소수 6자리
    assert r.value == Decimal("88.094795")
    assert r.inputs["basis"] == "estimated_price"
    assert "예정가격" in r.formula
    with pytest.raises(TypeError):
        bid_rate("1", "2", price_status=PriceStatus.ACTUAL)  # type: ignore[call-arg]


def test_bid_rate_differs_by_basis():
    a = bid_rate("90000000", "100000000", basis=RateBasis.BASE_AMOUNT, price_status=PriceStatus.ACTUAL)
    b = bid_rate("90000000", "98000000", basis=RateBasis.ESTIMATED_PRICE, price_status=PriceStatus.ACTUAL)
    assert a.value == Decimal("90.000000")
    assert b.value != a.value


def test_bid_rate_flags_non_integer_bid():
    r = bid_rate("100.5", "1000", basis=RateBasis.BASE_AMOUNT, price_status=PriceStatus.ACTUAL)
    assert any(w.startswith("NON_INTEGER_BID") for w in r.warnings)


def test_bid_amount_from_rate():
    r = bid_amount_from_rate(
        "99500000", "88.094795", basis=RateBasis.ESTIMATED_PRICE, price_status=PriceStatus.SCENARIO, rounding=TRUNC
    )
    # 99,500,000 × 88.094795% = 87,654,321.025 → 절사 87,654,321
    assert r.value == Decimal("87654321")
    assert r.assumption_based


# ------------------------------------------------------------------ 부가가치세


def test_vat_included_split():
    s = split_vat("110000000", vat_included=True, rounding=TRUNC)
    assert (s.supply_amount, s.vat_amount, s.total_amount) == (Decimal("100000000"), Decimal("10000000"), Decimal("110000000"))
    assert s.supply_amount + s.vat_amount == s.total_amount


def test_vat_included_split_with_remainder():
    # 12,345,678 ÷ 1.1 = 11,223,343.636... → 공급가액 절사 11,223,343, 세액 = 총액 − 공급가액
    s = split_vat("12345678", vat_included=True, rounding=TRUNC)
    assert s.supply_amount == Decimal("11223343")
    assert s.vat_amount == Decimal("1122335")
    assert s.supply_amount + s.vat_amount == Decimal("12345678")


def test_vat_excluded_adds_tax():
    s = split_vat("100000000", vat_included=False, rounding=TRUNC)
    assert s.total_amount == Decimal("110000000")


def test_vat_unknown_inclusion_refuses():
    with pytest.raises(CalcInputError) as e:
        split_vat("100", vat_included=None)
    assert e.value.field == "vat_included"


def test_vat_stated_amount_takes_priority_and_checks_consistency():
    s = split_vat("110000000", vat_included=True, stated_vat_amount="10000000")
    assert s.source == "stated" and s.warnings == ()
    s2 = split_vat("110000000", vat_included=True, stated_vat_amount="9000000")
    assert any(w.startswith("VAT_MISMATCH") for w in s2.warnings)
    with pytest.raises(CalcInputError):
        split_vat("100", vat_included=True, stated_vat_amount="200")


def test_vat_without_rounding_rule_warns():
    s = split_vat("12345678", vat_included=True)
    assert any(w.startswith("ROUNDING_RULE_UNKNOWN") for w in s.warnings)


def test_vat_zero_amount():
    s = split_vat("0", vat_included=True, rounding=TRUNC)
    assert s.total_amount == 0 and s.vat_amount == 0


def test_vat_negative_rejected():
    with pytest.raises(CalcInputError):
        split_vat("-1", vat_included=True)


# ------------------------------------------------------------------ 절사·단위·입력 변환


@pytest.mark.parametrize(
    ("mode", "unit", "value", "expected"),
    [
        (RoundingMode.TRUNCATE, 1, "1234.99", "1234"),
        (RoundingMode.TRUNCATE, 10, "1239", "1230"),
        (RoundingMode.TRUNCATE, 1000, "123999", "123000"),
        (RoundingMode.CEIL, 10, "1231", "1240"),
        (RoundingMode.HALF_UP, 1, "1234.5", "1235"),
        (RoundingMode.HALF_UP, 1, "1234.49", "1234"),
        (RoundingMode.HALF_UP, 100, "1250", "1300"),
        (RoundingMode.NONE, 1, "1234.5", "1234.5"),
    ],
)
def test_rounding_modes(mode, unit, value, expected):
    out, warnings = apply_rounding(Decimal(value), RoundingRule(mode, unit))
    assert out == Decimal(expected)
    assert warnings == []


def test_rounding_rule_invalid_unit():
    with pytest.raises(CalcInputError):
        RoundingRule(RoundingMode.TRUNCATE, 0)


def test_to_decimal_rejects_float():
    with pytest.raises(CalcInputError):
        to_decimal(0.1, "x")
    with pytest.raises(CalcInputError):
        to_decimal(True, "x")


def test_to_decimal_accepts_korean_formatting():
    assert to_decimal("1,234,567원", "x") == Decimal("1234567")
    assert to_decimal(" 87.745% ", "x") == Decimal("87.745")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e", "--1"])
def test_to_decimal_rejects_non_finite(bad):
    with pytest.raises(CalcInputError):
        to_decimal(bad, "x")


def test_to_percent_units():
    assert to_percent("0.87745", RateUnit.RATIO, "r") == Decimal("87.74500")
    assert to_percent("87.745", RateUnit.PERCENT, "r") == Decimal("87.745")


def test_amount_bounds():
    assert check_amount_bounds("100", minimum="100", maximum="100").ok  # 경계값 포함
    r = check_amount_bounds("99", minimum="100")
    assert not r.ok and "최소값" in r.violations[0]
    assert not check_amount_bounds("-5").ok
    assert not check_amount_bounds("10.5").ok
    assert not check_amount_bounds("101", maximum="100").ok


def test_result_is_serializable_for_reproduction():
    r = lower_limit_amount("99500000", "87.745", price_status=PriceStatus.ACTUAL, rounding=TRUNC)
    d = r.to_dict()
    assert d["value"] == "87306275"
    assert d["inputs"]["lower_limit_rate_pct"] == "87.745"
    # 직렬화된 입력으로 다시 계산하면 같은 값이 나와야 한다.
    again = lower_limit_amount(
        d["inputs"]["reference_price"], d["inputs"]["lower_limit_rate_pct"], price_status=PriceStatus(d["price_status"]), rounding=TRUNC
    )
    assert again.value == r.value
