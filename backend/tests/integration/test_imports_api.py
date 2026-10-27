import csv
import io
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import BidResult, NoticeChangeLog, NoticeRawRecord, ProcurementNotice

SAMPLE = Path(__file__).resolve().parents[2] / "seed" / "sample_results.csv"
OPTIONS = {"default_winning_rate_basis": "estimated_price", "issuing_authority_type": "local"}


def upload(client, data: bytes, name="sample_results.csv"):
    return client.post("/api/imports", files={"file": (name, data, "text/csv")})


def full_import(client, data: bytes, accept=(), name="sample_results.csv"):
    up = upload(client, data, name)
    assert up.status_code == 201, up.text
    job_id = up.json()["job_id"]
    sheet = up.json()["sheets"][0]
    pv = client.post(f"/api/imports/{job_id}/preview", json={"mapping": sheet["suggested_mapping"], "options": OPTIONS})
    assert pv.status_code == 200, pv.text
    cm = client.post(f"/api/imports/{job_id}/commit", json={"accept_changes": list(accept)})
    assert cm.status_code == 200, cm.text
    return up.json(), pv.json(), cm.json()


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_full_flow_and_reimport(client, session):
    analysis, preview, committed = full_import(client, SAMPLE.read_bytes())
    assert analysis["encoding"] == "utf-8-sig"
    assert preview["counts"]["new"] == 5
    assert preview["counts"]["invalid"] == 1
    assert preview["counts"]["duplicate_in_file"] == 1
    assert committed["counts"]["inserted"] == 5
    assert committed["counts"]["rejected"] == 1
    assert count(session, ProcurementNotice) == 5
    assert count(session, BidResult) == 4  # 결과 없는 1건은 결과 행을 만들지 않음
    assert count(session, NoticeRawRecord) == 5

    n = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "SAMPLE-2024-0001"))
    assert n.source_name == "upload"
    assert n.results[0].winning_rate_basis.value == "estimated_price"
    assert str(n.results[0].actual_sajeong_rate) == "-0.500000"

    # 같은 파일 재업로드: 경고 + 모두 '변경 없음', 아무것도 추가되지 않음
    analysis2, preview2, committed2 = full_import(client, SAMPLE.read_bytes())
    assert analysis2["previously_imported_job_ids"] == [analysis["job_id"]]
    assert preview2["counts"]["unchanged"] == 5
    assert committed2["counts"]["inserted"] == 0
    assert count(session, ProcurementNotice) == 5


def test_changed_rows_need_acceptance_and_rollback(client, session):
    full_import(client, SAMPLE.read_bytes())
    changed = SAMPLE.read_text(encoding="utf-8").replace('"150,000,000"', '"151,000,000"').replace("가상 하수관로 정비", "가상 하수관로 정비 변경")
    up = upload(client, changed.encode("utf-8"))
    job_id = up.json()["job_id"]
    pv = client.post(f"/api/imports/{job_id}/preview", json={"mapping": up.json()["sheets"][0]["suggested_mapping"], "options": OPTIONS}).json()
    changed_rows = [r for r in pv["rows"] if r["status"] == "changed"]
    assert {r["row_number"] for r in changed_rows} == {2, 8}
    row2 = next(r for r in changed_rows if r["row_number"] == 2)
    assert {"field": "base_amount", "label": "기초금액", "old": "150000000", "new": "151000000"} in row2["diffs"]

    # 2행만 반영, 8행은 반영하지 않음 → 기존 값 유지
    cm = client.post(f"/api/imports/{job_id}/commit", json={"accept_changes": [2]}).json()
    assert cm["counts"]["updated"] == 1
    assert cm["counts"]["changes_not_accepted"] == 1
    session.expire_all()
    n1 = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "SAMPLE-2024-0001"))
    n6 = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "SAMPLE-2024-0006"))
    assert str(n1.base_amount) == "151000000"
    assert n6.title == "[샘플] 가상 하수관로 정비"
    logs = list(session.scalars(select(NoticeChangeLog)))
    assert any(log.field_name == "base_amount" and log.old_value == "150000000" for log in logs)

    # 되돌리기: 변경 전 값으로 복원
    rb = client.post(f"/api/imports/{job_id}/rollback")
    assert rb.status_code == 200, rb.text
    session.expire_all()
    n1 = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "SAMPLE-2024-0001"))
    assert str(n1.base_amount) == "150000000"
    # 두 번 되돌리기 불가
    assert client.post(f"/api/imports/{job_id}/rollback").status_code == 409


def test_rollback_of_inserting_job_removes_rows(client, session):
    analysis, _, _ = full_import(client, SAMPLE.read_bytes())
    rb = client.post(f"/api/imports/{analysis['job_id']}/rollback").json()
    assert rb["deleted_notices"] == 5
    assert count(session, ProcurementNotice) == 0
    assert count(session, BidResult) == 0


def test_new_revision_updates_latest_flag(client, session):
    full_import(client, SAMPLE.read_bytes())
    text = "공고번호,차수,공고명\nSAMPLE-2024-0001,001,[샘플] 가상 도로 보수공사(정정)\n"
    _, pv, cm = full_import(client, text.encode(), name="rev.csv")
    assert pv["rows"][0]["status"] == "new_revision"
    session.expire_all()
    rows = list(session.scalars(select(ProcurementNotice).where(ProcurementNotice.notice_number == "SAMPLE-2024-0001").order_by(ProcurementNotice.notice_revision)))
    assert [r.is_latest_revision for r in rows] == [False, True]
    assert rows[0].superseded_by_id == rows[1].id


def test_cp949_upload(client):
    text = "공고번호,공고명,기초금액\nK-1,한글 인코딩 확인,1000000\n"
    _, pv, cm = full_import(client, text.encode("cp949"), name="k.csv")
    assert cm["counts"]["inserted"] == 1


def test_report_csv(client):
    analysis, _, _ = full_import(client, SAMPLE.read_bytes())
    res = client.get(f"/api/imports/{analysis['job_id']}/report.csv")
    assert res.status_code == 200
    text = res.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    outcomes = {r[0]: r[1] for r in rows if r and r[0].isdigit()}
    assert outcomes["6"] == "invalid"
    assert outcomes["7"] == "duplicate_in_file"


def test_invalid_upload_and_state_errors(client):
    assert upload(client, b"", "a.csv").status_code == 400
    assert upload(client, b"x", "a.pdf").status_code == 400
    job_id = upload(client, SAMPLE.read_bytes()).json()["job_id"]
    # 미리보기 전에는 저장 불가
    assert client.post(f"/api/imports/{job_id}/commit", json={}).status_code == 409
    # 필수 열 누락 매핑 → 매핑 오류
    pv = client.post(f"/api/imports/{job_id}/preview", json={"mapping": {"notice_number": "공고번호"}}).json()
    assert pv["mapping_errors"]
    assert client.post(f"/api/imports/{job_id}/commit", json={}).status_code == 409
    # 잘못된 옵션
    bad = client.post(f"/api/imports/{job_id}/preview", json={"mapping": {}, "options": {"rate_unit": "x"}})
    assert bad.status_code == 400
    assert client.get("/api/imports/9999").status_code == 404


def test_job_list(client):
    full_import(client, SAMPLE.read_bytes())
    jobs = client.get("/api/imports").json()
    assert jobs[0]["status"] == "committed"
    assert jobs[0]["accepted_count"] == 5
