from decimal import Decimal

import numpy as np
import pytest

from app.engines.calc import CalcInputError, PriceStatus, RoundingMode, RoundingRule, lower_limit_amount_with_a_value
from app.engines.recommend import (
    CostSheet,
    CustomScenario,
    LowerLimitSpec,
    QualItem,
    ScenarioRequest,
    break_even,
    build_scenarios,
    cost_summary,
    evaluate_items,
    evaluate_profit,
    historical_check,
    percentile,
)

D = Decimal
SAMPLES = [D(x) / 10 for x in range(-20, 21)]  # -2.0 ~ +2.0, 41건
SPEC = LowerLimitSpec(rate_pct=D("87.745"), source="rule", verified=True, rule_code="R1", rule_version="1")
BASE = D("1000000000")


def test_percentile_matches_numpy_and_is_exact():
    vals = sorted(D(x) for x in ("-1.2", "-0.3", "0.1", "0.4", "1.9"))
    for p in (0, 20, 50, 80, 100):
        assert float(percentile(vals, D(p))) == pytest.approx(np.percentile([float(v) for v in vals], p), abs=1e-6)
    with pytest.raises(CalcInputError):
        percentile(vals, D(101))


def test_a_value_lower_limit_formula():
    r = lower_limit_amount_with_a_value("1000000000", "87.745", "50000000", price_status=PriceStatus.ACTUAL)
    # 50,000,000 + 950,000,000 × 0.87745 = 883,577,500
    assert r.value == D("883577500")
    assert r.formula.startswith("A값")
    with pytest.raises(CalcInputError):
        lower_limit_amount_with_a_value("100", "87.745", "200", price_status=PriceStatus.ACTUAL)


def test_scenarios_ordered_and_above_assumed_lower_limit():
    out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES))
    assert out["status"] == "assumption_based" and out["label"] == "가정 기반 분석"
    by = {s["name"]: s for s in out["scenarios"]}
    cons, mod, aggr = (D(by[k]["candidate_amount"]) for k in ("conservative", "moderate", "aggressive"))
    assert cons > mod > aggr
    for s in out["scenarios"]:
        amt = D(s["candidate_amount"])
        assert amt == amt.to_integral_value() and amt >= D(s["assumed_lower_limit"])
        assert amt - D(s["assumed_lower_limit"]) < 1
    # 중앙값 0% → 예정가격 = 기초금액, 하한 = 877,450,000
    assert by["moderate"]["candidate_amount"] == "877450000"
    assert "낙찰을 보장" in out["disclaimer"]
    assert all("probability" not in k for s in out["scenarios"] for k in s)


def test_historical_check_counts():
    # 사정률 +2% 를 가정한 금액 → 그보다 높은 사정률이 없으니 하한 미달 0건
    out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES,
                                          custom=[CustomScenario(name="max", sajeong_rate_pct=D("2.0"))]))
    mx = next(s for s in out["scenarios"] if s["name"] == "max")
    assert mx["historical_check"]["below_lower_limit"] == 0
    aggr = next(s for s in out["scenarios"] if s["name"] == "aggressive")
    # 20 백분위 = -1.2% 가정 → -1.1% 이상 사정률(32건)에서는 하한 미달
    assert aggr["historical_check"]["below_lower_limit"] == 32
    assert any(f.startswith("BELOW_LOWER_LIMIT_IN_HISTORY") for f in aggr["risk_flags"])
    chk = historical_check(D("2000000000"), BASE, SPEC, SAMPLES)
    assert chk["above_estimated_price"] == 41 and "확률이 아닙니다" in chk["meaning"]


def test_insufficient_samples_refuse_presets_but_allow_custom_amount():
    out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES[:5],
                                          custom=[CustomScenario(bid_amount=D("880000000"))]))
    assert out["status"] == "insufficient_data"
    assert [s["name"] for s in out["scenarios"]] == ["custom"]
    assert any(w.startswith("INSUFFICIENT_DATA") for w in out["warnings"])
    with pytest.raises(CalcInputError):
        build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES[:5],
                                        custom=[CustomScenario(percentile=D(50))]))


def test_custom_validation():
    for bad in (CustomScenario(), CustomScenario(sajeong_rate_pct=D(0), bid_amount=D(1)), CustomScenario(bid_amount=D("1.5"))):
        with pytest.raises(CalcInputError):
            build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES, custom=[bad]))


def test_lower_limit_sources_add_warnings_and_rounding():
    for source, code in (("user_assumed", "ASSUMED_LOWER_LIMIT"), ("notice", "LOWER_LIMIT_FROM_NOTICE")):
        spec = LowerLimitSpec(rate_pct=D("87.745"), source=source)
        out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=spec, sajeong_samples=SAMPLES))
        assert any(w.startswith(code) for w in out["warnings"])
    unverified = LowerLimitSpec(rate_pct=D("87.745"), source="rule", verified=False)
    out = build_scenarios(ScenarioRequest(base_amount=D("1000000007"), lower_limit=unverified, sajeong_samples=SAMPLES))
    assert any(w.startswith("UNVERIFIED_RULE") for w in out["warnings"])
    assert any(w.startswith("ROUNDING_RULE_UNKNOWN") for w in out["warnings"])
    with pytest.raises(CalcInputError):
        LowerLimitSpec(rate_pct=D(0), source="rule")
    rounded = LowerLimitSpec(rate_pct=D("87.745"), source="rule", rounding=RoundingRule(RoundingMode.CEIL, 1000))
    assert rounded.amount(D("1000000007")) == D("877450000") + 1000 * 1  # 877,450,006.1 → 천원 올림


def test_a_value_scenario():
    spec = LowerLimitSpec(rate_pct=D("87.745"), source="rule", a_value=D("50000000"), verified=True)
    out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=spec, sajeong_samples=SAMPLES))
    mod = next(s for s in out["scenarios"] if s["name"] == "moderate")
    assert mod["candidate_amount"] == "883577500"
    assert out["lower_limit"]["formula"].startswith("A값")


# ------------------------------------------------------------------ 원가


def full_cost(**kw) -> CostSheet:
    items = {k: D(0) for k in ("material_cost", "labor_cost", "equipment_cost", "subcontract_cost", "transport_cost",
                                "site_overhead", "general_overhead", "statutory_costs", "other_costs")}
    items.update(material_cost=D("500000000"), labor_cost=D("300000000"))
    items.update(kw.pop("items", {}))
    return CostSheet(items=items, **kw)


def test_cost_incomplete_does_not_compute_profit():
    sheet = CostSheet(items={"material_cost": D("100")}, vat_treatment="excluded")
    s = cost_summary(sheet)
    assert not s["complete"] and "labor_cost" in s["missing_items"] and s["supply_total"] is None
    p = evaluate_profit(D("1000"), sheet, bid_vat_included=True)
    assert p["status"] == "cost_incomplete" and p["profit"] is None


def test_profit_with_vat_and_targets():
    sheet = full_cost(vat_treatment="excluded", target_profit=D("10000000"), target_profit_rate=D("5"))
    p = evaluate_profit(D("880000000"), sheet, bid_vat_included=True)
    # 공급가액 800,000,000 − 원가 800,000,000 = 0
    assert p["bid_supply_amount"] == "800000000" and p["profit"] == "0"
    assert any(f.startswith("BELOW_TARGET_PROFIT") for f in p["flags"])
    loss = evaluate_profit(D("870000000"), sheet, bid_vat_included=True)
    assert D(loss["profit"]) < 0 and any(f.startswith("BELOW_COST") for f in loss["flags"])
    assert evaluate_profit(D("880000000"), sheet, bid_vat_included=None)["status"] == "vat_unknown"
    be = break_even(sheet, bid_vat_included=True)
    assert be["break_even_bid"] == "880000000"
    assert be["min_bid_for_target_profit"] == "891000000"
    # 800,000,000 ÷ 0.95 = 842,105,263.157... × 1.1 = 926,315,789.47 → 올림
    assert be["min_bid_for_target_margin"] == "926315790"


def test_cost_included_vat_and_validation():
    sheet = full_cost(vat_treatment="included")
    assert cost_summary(sheet)["supply_total"].startswith("727272727")
    with pytest.raises(CalcInputError):
        CostSheet(items={"magic": D(1)})
    with pytest.raises(CalcInputError):
        CostSheet(items={"labor_cost": D(-1)})
    with pytest.raises(CalcInputError):
        CostSheet(vat_treatment="maybe")


def test_scenarios_include_profit():
    sheet = full_cost(vat_treatment="excluded")
    out = build_scenarios(ScenarioRequest(base_amount=BASE, lower_limit=SPEC, sajeong_samples=SAMPLES, cost=sheet, bid_vat_included=True))
    assert all(s["profit"]["status"] == "computed" for s in out["scenarios"])


# ------------------------------------------------------------------ 적격심사


def items(*specs):
    return [QualItem(item_code=c, item_name=c, max_score=None if m is None else D(m), score=None if s is None else D(s), status=st)
            for c, m, s, st in specs]


def test_unknown_items_give_range_not_zero_or_full():
    r = evaluate_items(items(("a", 30, 30, "confirmed"), ("b", 20, 15, "expected"), ("c", 50, None, "unknown")), pass_threshold=95)
    assert r["confirmed_score"] == "30" and r["expected_score"] == "15"
    assert (r["range_with_expected"]["min"], r["range_with_expected"]["max"]) == ("45", "95")
    assert r["range_with_expected"]["verdict"] == "undetermined"
    assert (r["range_confirmed_only"]["min"], r["range_confirmed_only"]["max"]) == ("30", "100")
    assert any(w.startswith("UNKNOWN_ITEMS") for w in r["warnings"])


def test_verdicts():
    passed = evaluate_items(items(("a", 60, 60, "confirmed"), ("b", 40, 38, "confirmed")), pass_threshold=95)
    assert passed["range_confirmed_only"]["verdict"] == "pass"
    failed = evaluate_items(items(("a", 60, 40, "confirmed"), ("b", 40, None, "unknown")), pass_threshold=95)
    assert failed["range_with_expected"]["verdict"] == "fail"  # 최대 80 < 95
    no_max = evaluate_items(items(("a", 60, 60, "confirmed"), ("b", None, None, "unknown")), pass_threshold=50)
    assert no_max["range_with_expected"]["max"] is None and no_max["range_with_expected"]["verdict"] == "pass"


def test_qualification_validation():
    for bad in (items(("a", 10, 5, "unknown")), items(("a", 10, None, "confirmed")), items(("a", 10, 11, "expected")),
                items(("a", 10, 1, "maybe")), items(("a", 10, 1, "confirmed"), ("a", 10, 1, "confirmed"))):
        with pytest.raises(CalcInputError):
            evaluate_items(bad)
