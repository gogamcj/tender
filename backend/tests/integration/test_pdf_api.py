from tests.pdf_samples import build_notice_pdf, sample_notice_pdf


def upload(client, data=None, notice_id=None):
    files = {"file": ("notice.pdf", data or sample_notice_pdf(), "application/pdf")}
    return client.post("/api/pdfs", files=files, data={"notice_id": str(notice_id)} if notice_id else None)


def ex_id(doc, field, page=None):
    cands = doc["fields"][field]["candidates"]
    return next(c["id"] for c in cands if page is None or c["page_number"] == page)


def test_upload_extract_and_duplicate(client):
    r = upload(client)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["page_count"] == 2 and doc["text_layer"] == "native"
    assert doc["unreviewed_count"] == doc["extraction_count"] > 10
    assert doc["fields"]["base_amount"]["distinct_values"] == ["812345000"]
    assert all(c["review_status"] == "unreviewed" and c["final_value"] is None for f in doc["fields"].values() for c in f["candidates"])
    dup = upload(client)
    assert dup.status_code == 409 and dup.json()["detail"]["document_id"] == doc["id"]
    page = client.get(f"/api/pdfs/{doc['id']}/pages/2").json()
    assert "지역제한" in page["text"]
    assert client.get(f"/api/pdfs/{doc['id']}/pages/9").status_code == 400
    assert client.post("/api/pdfs", files={"file": ("x.pdf", b"hello", "application/pdf")}).status_code == 400


def test_review_and_apply_without_overwriting(client):
    nid = client.post("/api/notices", json={"notice_number": "R26BK00000001", "title": "기존 제목", "base_amount": "800000000"}).json()["id"]
    doc = upload(client, notice_id=nid).json()
    did = doc["id"]
    assert doc["fields"]["base_amount"]["notice_value"] == {"base_amount": "800000000"}

    # 검토하지 않은 값은 반영되지 않는다
    rep = client.post(f"/api/pdfs/{did}/apply", json={"fields": ["lower_limit_rate"]}).json()["report"]
    assert rep["lower_limit_rate"]["status"] == "skipped"

    for field in ("base_amount", "lower_limit_rate", "bid_deadline", "reserve_range", "vat_included", "award_method"):
        r = client.patch(f"/api/pdfs/{did}/extractions/{ex_id(doc, field, 1)}", json={"review_status": "confirmed"})
        assert r.status_code == 200, r.text
    rep = client.post(f"/api/pdfs/{did}/apply", json={"fields": ["base_amount", "lower_limit_rate", "bid_deadline", "reserve_range",
                                                                  "vat_included", "award_method", "a_value"]}).json()["report"]
    assert rep["lower_limit_rate"]["status"] == "applied"
    assert rep["reserve_range_begin_rate"]["status"] == "applied" and rep["reserve_range_end_rate"]["new"] == "2"
    assert rep["a_value"]["status"] == "skipped"  # 참고용 항목
    # 기존 기초금액과 다르면 덮어쓰지 않고 보류
    assert rep["base_amount"]["status"] == "pending"
    detail = client.get(f"/api/notices/{nid}").json()
    assert detail["base_amount"] == "800000000" and detail["lower_limit_rate"].startswith("87.745")
    assert detail["vat_included"] is True and detail["award_method"] == "적격심사"
    assert detail["bid_deadline"].startswith("2026-11-05T01:00:00")  # UTC 저장
    pending = rep["base_amount"]["change_log_id"]
    assert client.post(f"/api/notices/{nid}/changes/{pending}/apply").status_code == 200
    assert client.get(f"/api/notices/{nid}").json()["base_amount"] == "812345000"
    # 다시 반영하면 '같음'
    rep2 = client.post(f"/api/pdfs/{did}/apply", json={"fields": ["base_amount"]}).json()["report"]
    assert rep2["base_amount"]["status"] == "unchanged"


def test_explicit_overwrite_and_corrections(client):
    nid = client.post("/api/notices", json={"notice_number": "X-1", "title": "기존 제목"}).json()["id"]
    did = upload(client).json()["id"]
    client.patch(f"/api/pdfs/{did}", json={"notice_id": nid})
    doc = client.get(f"/api/pdfs/{did}").json()
    t = ex_id(doc, "title")
    assert client.patch(f"/api/pdfs/{did}/extractions/{t}", json={"review_status": "corrected", "value": "고친 공고명"}).json()["final_value"] == "고친 공고명"
    rep = client.post(f"/api/pdfs/{did}/apply", json={"fields": ["title"], "overwrite": ["title"]}).json()["report"]
    assert rep["title"] == {"status": "applied", "old": "기존 제목", "new": "고친 공고명"}
    log = client.get(f"/api/notices/{nid}").json()["change_log"]
    assert any(c["field_name"] == "title" and c["change_source"] == f"pdf:{did}" for c in log)
    # 형식에 맞지 않는 수정 값 거부
    b = ex_id(doc, "base_amount")
    assert client.patch(f"/api/pdfs/{did}/extractions/{b}", json={"review_status": "corrected", "value": "8억"}).status_code == 422
    d = ex_id(doc, "bid_deadline")
    assert client.patch(f"/api/pdfs/{did}/extractions/{d}", json={"review_status": "corrected", "value": "2026-11-05T10:00:00"}).status_code == 422


def test_conflict_blocks_apply_and_manual_entry(client):
    nid = client.post("/api/notices", json={"notice_number": "C-1", "title": "충돌"}).json()["id"]
    data = build_notice_pdf(lines=["기초금액: 100,000,000원", "본문", "기초금액: 120,000,000원"])
    doc = upload(client, data, notice_id=nid).json()
    assert doc["fields"]["base_amount"]["conflict"] is True
    for c in doc["fields"]["base_amount"]["candidates"]:
        client.patch(f"/api/pdfs/{doc['id']}/extractions/{c['id']}", json={"review_status": "confirmed"})
    rep = client.post(f"/api/pdfs/{doc['id']}/apply", json={"fields": ["base_amount"]}).json()["report"]
    assert rep["base_amount"]["status"] == "skipped" and "서로 다릅니다" in rep["base_amount"]["reason"]
    # 하나를 기각하면 반영 가능
    rej = doc["fields"]["base_amount"]["candidates"][1]["id"]
    client.patch(f"/api/pdfs/{doc['id']}/extractions/{rej}", json={"review_status": "rejected"})
    assert client.post(f"/api/pdfs/{doc['id']}/apply", json={"fields": ["base_amount"]}).json()["report"]["base_amount"]["status"] == "applied"
    # 찾지 못한 항목은 직접 입력
    m = client.post(f"/api/pdfs/{doc['id']}/extractions", json={"field_name": "lower_limit_rate", "value": "87.745", "page_number": 1})
    assert m.status_code == 201 and m.json()["review_status"] == "corrected"
    assert client.post(f"/api/pdfs/{doc['id']}/extractions", json={"field_name": "lower_limit_rate", "value": "150"}).status_code == 422


def test_apply_requires_linked_notice(client):
    did = upload(client).json()["id"]
    assert client.post(f"/api/pdfs/{did}/apply", json={"fields": ["title"]}).status_code == 400
