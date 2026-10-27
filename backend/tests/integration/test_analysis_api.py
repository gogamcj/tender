from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[2] / "seed"
AS_OF = "2026-10-27T00:00:00+09:00"


@pytest.fixture
def history(client):
    data = (SEED / "sample_history.csv").read_bytes()
    up = client.post("/api/imports", files={"file": ("sample_history.csv", data, "text/csv")}).json()
    pv = client.post(f"/api/imports/{up['job_id']}/preview", json={
        "mapping": up["sheets"][0]["suggested_mapping"], "options": {"default_winning_rate_basis": "estimated_price"}}).json()
    assert pv["counts"]["invalid"] == 0, pv["rows"][:3]
    cm = client.post(f"/api/imports/{up['job_id']}/commit", json={}).json()
    assert cm["counts"]["inserted"] == 240
    return client


def test_stats_stratified_by_conditions(history):
    r = history.post("/api/analysis/stats", json={"filters": {"period": "3y", "as_of": AS_OF}, "metric": "sajeong_rate",
                                                  "group_by": ["agency_name"]})
    assert r.status_code == 200, r.text
    body = r.json()
    # 기관유형(국가/지자체) × 결정방식(적격심사/최저가) → 여러 층, 합친 통계 없음
    assert len(body["strata"]) >= 3 and body["pooled"] is None
    assert any(w.startswith("MIXED_CONDITIONS") for w in body["warnings"])
    total_n = sum(s["summary"]["n"] for s in body["strata"])
    assert total_n + body["missing_count"] == body["n_records"]
    s0 = body["strata"][0]
    for k in ("mean", "median", "q1", "q3", "std", "min", "max", "outliers"):
        assert k in s0["summary"]
    assert s0["groups"] and s0["trend"]
    assert body["period"]["preset"] == "3y" and body["period"]["basis"] == "개찰일시"
    assert body["sources"] == {"upload": total_n}
    assert "보장하지 않습니다" in body["disclaimer"]


def test_stats_with_single_stratum_has_pooled_and_can_be_saved(history):
    r = history.post("/api/analysis/stats", json={
        "filters": {"period": None, "as_of": AS_OF, "issuing_authority_type": "local", "award_method": "적격심사"},
        "metric": "winning_rate", "save": True}).json()
    assert len(r["strata"]) == 1 and r["pooled"]["n"] > 30
    assert r["strata"][0]["conditions"]["rate_basis"] == "estimated_price"
    assert 87.7 < r["pooled"]["median"] < 88.7
    assert r["analysis_run_id"] > 0


def test_period_presets_reduce_sample(history):
    def n(period):
        body = history.post("/api/analysis/stats", json={"filters": {"period": period, "as_of": AS_OF}, "metric": "bid_count"}).json()
        return body["n_records"]

    assert n("3m") <= n("6m") <= n("1y") <= n("3y")
    bad = history.post("/api/analysis/stats", json={"filters": {"period": "10y"}})
    assert bad.status_code == 400


def test_filters_by_agency_amount_and_bid_count(history):
    body = history.post("/api/analysis/stats", json={"filters": {
        "period": None, "as_of": AS_OF, "agency_name": "샘플시청", "amount_min": "100000000", "amount_max": "1000000000",
        "bid_count_min": 100}, "metric": "bid_count", "trend": None}).json()
    for s in body["strata"]:
        assert s["summary"]["min"] >= 100


def test_sajeong_distribution(history):
    body = history.post("/api/analysis/sajeong-distribution", json={"filters": {"period": None, "as_of": AS_OF}, "bin_width": 0.5}).json()
    assert body["histograms"]
    for label, bins in body["histograms"].items():
        stratum = next(s for s in body["strata"] if s["label"] == label)
        assert sum(b["count"] for b in bins) == stratum["summary"]["n"]
    assert "미래 예정가격" in body["disclaimer"]


def test_similar_by_notice_and_no_leakage(history):
    found = history.get("/api/notices", params={"q": "SAMPLE-H0100"}).json()["items"][0]
    out = history.post("/api/analysis/similar", json={"notice_id": found["id"], "filters": {"period": None}, "limit": 5}).json()
    assert out["matches"]
    assert all(m["notice_id"] != found["id"] for m in out["matches"])
    cutoff = out["criteria"]["as_of"]
    assert cutoff is not None
    assert all(m["opening_date"] < cutoff for m in out["matches"])
    assert out["matches"][0]["reasons"]
    by_target = history.post("/api/analysis/similar", json={"target": {
        "procurement_type": "construction", "issuing_authority_type": "local", "contract_method": "제한경쟁",
        "award_method": "적격심사", "agency_name": "샘플시청", "amount": "500000000"}, "filters": {"period": None, "as_of": AS_OF}}).json()
    assert by_target["matches"][0]["components"]["agency"] == 3.0
    assert history.post("/api/analysis/similar", json={}).status_code == 400


def test_notice_search_and_detail(history):
    page = history.get("/api/notices", params={"agency": "샘플시청", "amount_min": "1000000000", "size": 5, "sort": "-base_amount"}).json()
    assert page["total"] > 0 and len(page["items"]) <= 5
    amounts = [int(i["base_amount"]) for i in page["items"]]
    assert amounts == sorted(amounts, reverse=True) and amounts[-1] >= 1_000_000_000
    no_result = history.get("/api/notices", params={"has_result": False}).json()
    assert no_result["total"] > 0 and all(i["result"] is None for i in no_result["items"])
    with_result = history.get("/api/notices", params={"has_result": True, "size": 1}).json()["items"][0]
    d = history.get(f"/api/notices/{with_result['id']}").json()
    assert d["results"] and d["revisions"] and d["raw_record_count"] == 1
    assert history.get("/api/notices/999999").status_code == 404


def test_manual_notice_and_status(client):
    r = client.post("/api/notices", json={"notice_number": "M-1", "title": "수동 입력 공고", "base_amount": "100000000",
                                          "announcement_date": "2026-10-01", "opening_date": "2026-11-01T11:00:00+09:00"})
    assert r.status_code == 201, r.text
    nid = r.json()["id"]
    assert r.json()["source_name"] == "manual" and r.json()["data_status"] == "collected"
    assert client.post("/api/notices", json={"notice_number": "M-1", "title": "중복"}).status_code == 409
    assert client.post("/api/notices", json={"notice_number": "M-2", "title": "x", "opening_date": "2026-11-01T11:00:00"}).status_code == 422
    assert client.post("/api/notices", json={"notice_number": "M-3", "title": "x", "base_amount": "100.5"}).status_code == 422
    s = client.patch(f"/api/notices/{nid}/status", json={"data_status": "excluded"}).json()
    assert s["data_status"] == "excluded"
    log = client.get(f"/api/notices/{nid}").json()["change_log"][0]
    assert (log["field_name"], log["old_value"], log["new_value"]) == ("data_status", "collected", "excluded")


def test_excluded_notice_left_out_of_stats(history):
    item = history.get("/api/notices", params={"has_result": True, "size": 1}).json()["items"][0]
    before = history.post("/api/analysis/stats", json={"filters": {"period": None, "as_of": AS_OF}, "metric": "bid_count"}).json()["n_records"]
    history.patch(f"/api/notices/{item['id']}/status", json={"data_status": "excluded"})
    after = history.post("/api/analysis/stats", json={"filters": {"period": None, "as_of": AS_OF}, "metric": "bid_count"}).json()["n_records"]
    assert after == before - 1
