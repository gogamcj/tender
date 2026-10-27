from decimal import Decimal

import pytest

from app.core.config import get_settings

from .test_analysis_api import history  # noqa: F401  (가상 표본 240건 적재 fixture)

RULE = {
    "rule_code": "LOCAL_QUAL_TEST", "rule_name": "테스트용 지자체 적격심사 하한", "procurement_type": "construction",
    "issuing_authority_type": "local", "contract_method": "any", "award_method": "적격심사", "effective_from": "2020-01-01",
    "formula_definition": {"module": "simple_lower_limit", "params": {"lower_limit_rate_pct": "87.745"}},
}
TARGET = {
    "notice_number": "T-2026-1", "title": "대상 공사", "agency_name": "샘플시청", "procurement_type": "construction",
    "issuing_authority_type": "local", "contract_method": "제한경쟁", "award_method": "적격심사", "base_amount": "800000000",
    "announcement_date": "2026-10-20", "bid_deadline": "2026-10-30T10:00:00+09:00", "vat_included": True,
}
COST = {"material_cost": "400000000", "labor_cost": "250000000", "equipment_cost": "0", "subcontract_cost": "0",
        "transport_cost": "0", "site_overhead": "20000000", "general_overhead": "10000000", "statutory_costs": "5000000",
        "other_costs": "0", "vat_treatment": "excluded", "target_profit": "20000000"}


@pytest.fixture
def target(history):  # noqa: F811
    r = history.post("/api/notices", json=TARGET)
    assert r.status_code == 201, r.text
    return history, r.json()["id"]


def test_refuses_without_lower_limit(target):
    client, nid = target
    r = client.post("/api/recommend", json={"notice_id": nid})
    assert r.status_code == 422 and r.json()["field"] == "lower_limit_rate"


def test_recommend_with_rule_and_cost_saved_and_reproducible(target):
    client, nid = target
    assert client.post("/api/rules", json=RULE).status_code == 201
    body = {"notice_id": nid, "period": None, "cost": COST, "custom": [{"name": "내 금액", "bid_amount": "710000000"}], "save": True}
    r = client.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "assumption_based"
    assert out["lower_limit"]["source"] == "rule" and out["lower_limit"]["rule_code"] == "LOCAL_QUAL_TEST"
    assert any(w.startswith("UNVERIFIED_RULE") for w in out["warnings"])
    assert out["sample"]["n"] >= 30
    # 대상 공고 입찰마감 이후 개찰 건은 표본에 없다(가상 표본은 모두 그 이전)
    assert nid not in out["sample"]["notice_ids"]
    names = [s["name"] for s in out["scenarios"]]
    assert names == ["conservative", "moderate", "aggressive", "내 금액"]
    amounts = [Decimal(s["candidate_amount"]) for s in out["scenarios"][:3]]
    assert amounts[0] > amounts[1] > amounts[2]
    for s in out["scenarios"]:
        assert s["profit"]["status"] == "computed"
        assert "probability" not in str(s).lower()
    assert out["cost"]["break_even"]["break_even_bid"] == str(int(Decimal("685000000") * Decimal("1.1")))
    run_id = out["analysis_run_id"]

    detail = client.get(f"/api/analysis/runs/{run_id}").json()
    assert detail["analysis_type"] == "recommend" and detail["rule_version"] == {"LOCAL_QUAL_TEST": "1"}
    assert len(detail["scenarios"]) == 4 and detail["scenarios"][0]["rate_basis"] == "base_amount"
    assert client.get("/api/analysis/runs", params={"notice_id": nid}).json()[0]["id"] == run_id

    rep = client.post(f"/api/analysis/runs/{run_id}/reproduce").json()
    assert rep["data_changed"] is False and rep["result_identical"] is True

    # 과거 자료 하나를 분석에서 제외하면 재현 시 데이터 변경이 드러난다
    victim = out["sample"]["notice_ids"][0]
    client.patch(f"/api/notices/{victim}/status", json={"data_status": "excluded"})
    rep2 = client.post(f"/api/analysis/runs/{run_id}/reproduce").json()
    assert rep2["data_changed"] is True and rep2["result_identical"] is False


def test_user_override_and_insufficient_data(target):
    client, nid = target
    r = client.post("/api/recommend", json={"notice_id": nid, "period": None, "lower_limit_rate_pct": "87.745",
                                            "history_filters": {"agency_name": "존재하지않는기관"},
                                            "custom": [{"sajeong_rate_pct": "0"}]}).json()
    assert r["status"] == "insufficient_data" and r["sample"]["n"] == 0
    assert any(w.startswith("ASSUMED_LOWER_LIMIT") for w in r["warnings"])
    assert [s["name"] for s in r["scenarios"]] == ["custom"]
    assert r["scenarios"][0]["candidate_amount"] == "701960000"  # 800,000,000 × 87.745%
    bad = client.post("/api/recommend", json={"notice_id": nid, "lower_limit_rate_pct": "87.745", "history_filters": {"x": 1}})
    assert bad.status_code == 400


def test_blocked_unverified_rule(target, monkeypatch):
    client, nid = target
    client.post("/api/rules", json=RULE)
    monkeypatch.setenv("BID_BLOCK_UNVERIFIED_RULES", "true")
    get_settings.cache_clear()
    try:
        r = client.post("/api/recommend", json={"notice_id": nid, "period": None})
        assert r.status_code == 409
    finally:
        monkeypatch.delenv("BID_BLOCK_UNVERIFIED_RULES")
        get_settings.cache_clear()


def test_a_value_rule_requires_a_value(target):
    client, nid = target
    client.post("/api/rules", json={**RULE, "rule_code": "A_RULE", "formula_definition": {
        "module": "a_value_lower_limit", "params": {"lower_limit_rate_pct": "87.745"}}})
    r = client.post("/api/recommend", json={"notice_id": nid, "period": None})
    assert r.status_code == 422 and r.json()["field"] == "a_value"
    ok = client.post("/api/recommend", json={"notice_id": nid, "period": None, "a_value": "40000000"}).json()
    assert ok["lower_limit"]["formula"].startswith("A값") and ok["lower_limit"]["a_value"] == "40000000"


def test_cost_crud_and_evaluate(client):
    r = client.post("/api/costs", json={"material_cost": "100000000", "vat_treatment": "excluded"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["summary"]["complete"] is False
    ev = client.post("/api/costs/evaluate", json={"cost_id": cid, "bid_amount": "200000000", "bid_vat_included": True}).json()
    assert ev["profit"]["status"] == "cost_incomplete" and ev["break_even"]["status"] == "not_computed"
    full = {**COST}
    assert client.put(f"/api/costs/{cid}", json=full).json()["summary"]["complete"] is True
    ev = client.post("/api/costs/evaluate", json={"cost_id": cid, "bid_amount": "770000000", "bid_vat_included": True}).json()
    assert ev["profit"]["profit"] == "15000000"  # 700,000,000 − 685,000,000
    assert any(f.startswith("BELOW_TARGET_PROFIT") for f in ev["profit"]["flags"])
    assert client.post("/api/costs", json={"labor_cost": "100.5"}).status_code == 422
    assert client.post("/api/costs", json={"labor_cost": "-1"}).status_code == 422
    assert client.get("/api/costs/9999").status_code == 404


def test_qualification_checklist(client):
    nid = client.post("/api/notices", json={"notice_number": "Q-1", "title": "심사 대상"}).json()["id"]
    assert client.get("/api/qualification/templates").json()["items"]
    items = [
        {"item_code": "experience", "item_name": "시공실적", "max_score": "15", "score": "15", "status": "confirmed"},
        {"item_code": "financial", "item_name": "경영상태", "max_score": "15", "score": "13", "status": "expected"},
        {"item_code": "price", "item_name": "입찰가격", "max_score": "70", "status": "unknown"},
    ]
    r = client.put(f"/api/notices/{nid}/qualification", json={"items": items, "pass_threshold": "95"})
    assert r.status_code == 200, r.text
    ev = r.json()["evaluation"]
    assert ev["range_with_expected"] == {**ev["range_with_expected"], "min": "28", "max": "98", "verdict": "undetermined"}
    got = client.get(f"/api/notices/{nid}/qualification", params={"pass_threshold": "95"}).json()
    assert [i["status"] for i in got["items"]] == ["confirmed", "expected", "unknown"]
    assert got["items"][2]["score"] is None
    bad = client.put(f"/api/notices/{nid}/qualification", json={"items": [{**items[2], "score": "0"}]})
    assert bad.status_code == 422
    # 거부된 요청은 기존 점검표를 바꾸지 않는다
    assert len(client.get(f"/api/notices/{nid}/qualification").json()["items"]) == 3


def test_stats_run_reproduce(history):  # noqa: F811
    out = history.post("/api/analysis/stats", json={"filters": {"period": None, "as_of": "2026-10-27T00:00:00+09:00"},
                                                    "metric": "sajeong_rate", "save": True}).json()
    rep = history.post(f"/api/analysis/runs/{out['analysis_run_id']}/reproduce").json()
    assert rep["data_changed"] is False and rep["result_identical"] is True
    assert history.post("/api/analysis/runs/9999/reproduce").status_code == 404
