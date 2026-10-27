RULE = {
    "rule_code": "TEST_RULE",
    "rule_name": "테스트용 규칙(실제 규정 아님)",
    "procurement_type": "construction",
    "issuing_authority_type": "national",
    "effective_from": "2024-01-01",
    "effective_until": "2024-12-31",
    "formula_definition": {"module": "simple_lower_limit", "params": {"lower_limit_rate_pct": "87.745"}},
    "rounding_rule": {"mode": "truncate", "unit": 1},
}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_openapi_docs_available(client):
    spec = client.get("/openapi.json").json()
    assert "/api/calc/lower-limit" in spec["paths"]


def test_lower_limit_endpoint(client):
    r = client.post(
        "/api/calc/lower-limit",
        json={"reference_price": "99500000", "lower_limit_rate": "87.745", "price_status": "user_assumed",
              "rounding": {"mode": "truncate", "unit": 1}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "87306275"
    assert body["assumption_based"] is True
    assert body["status_label"] == "가정 기반 분석"


def test_float_amount_rejected(client):
    r = client.post("/api/calc/sajeong-rate", json={"base_amount": 100000000.5, "estimated_price": "99000000"})
    assert r.status_code == 422


def test_calc_input_error_returns_field(client):
    r = client.post("/api/calc/sajeong-rate", json={"base_amount": "0", "estimated_price": "1"})
    assert r.status_code == 422
    assert r.json()["field"] == "base_amount"


def test_vat_requires_inclusion_flag(client):
    r = client.post("/api/calc/vat", json={"amount": "110000000", "vat_included": None})
    assert r.status_code == 422
    assert r.json()["field"] == "vat_included"


def test_rule_lifecycle_and_selection(client):
    created = client.post("/api/rules", json=RULE)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert created.json()["verification_status"] == "unverified"

    notice = {"announcement_date": "2024-06-01", "procurement_type": "construction", "issuing_authority_type": "national"}
    sel = client.post("/api/rules/select", json={"notice": notice, "inputs": {"reference_price": "99500000", "price_status": "actual"}}).json()
    assert sel["selected_rule_code"] == "TEST_RULE"
    assert sel["evaluation"]["definitive"] is False  # 미검증

    # 근거 문서 없이 검증 처리 불가
    bad = client.patch(f"/api/rules/{rid}/verification", json={"verification_status": "verified"})
    assert bad.status_code == 422

    # 과거 규칙은 2025년 공고에 적용되지 않음
    later = client.post("/api/rules/select", json={"notice": {**notice, "announcement_date": "2025-03-01"}}).json()
    assert later["selected_rule_code"] is None
    assert any(w.startswith("NO_RULE") for w in later["warnings"])


def test_duplicate_rule_version_rejected(client):
    assert client.post("/api/rules", json=RULE).status_code == 201
    dup = client.post("/api/rules", json=RULE)
    assert dup.status_code == 409
    assert dup.json()["error"] == "conflict"
