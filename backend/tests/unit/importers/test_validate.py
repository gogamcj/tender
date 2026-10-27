from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.db.enums import DataStatus, NoticePhase
from app.engines.calc import RateBasis
from app.importers.fields import suggest_mapping
from app.importers.reader import Sheet, read_upload
from app.importers.validate import ExistingNotice, ImportOptions, RowStatus, validate_rows

SAMPLE = Path(__file__).resolve().parents[3] / "seed" / "sample_results.csv"
NOW = datetime(2026, 10, 27, tzinfo=UTC)
OPTS = ImportOptions(default_winning_rate_basis=RateBasis.ESTIMATED_PRICE, issuing_authority_type="local", now=NOW)


def none_lookup(*_):
    return None


def no_revs(_):
    return []


def sample_sheet() -> Sheet:
    return read_upload("sample_results.csv", SAMPLE.read_bytes()).sheets[0]


def run(sheet=None, mapping=None, options=OPTS, lookup=none_lookup, revisions=no_revs):
    sheet = sheet or sample_sheet()
    mapping = mapping if mapping is not None else suggest_mapping(sheet.columns)
    return validate_rows(sheet, mapping, options, lookup, revisions)


def test_sample_mapping_is_complete():
    m = suggest_mapping(sample_sheet().columns)
    for key in ("notice_number", "notice_revision", "title", "agency_name", "base_amount", "estimated_price",
                "winning_bid_amount", "winning_rate", "bid_count", "opening_date", "announcement_date"):
        assert key in m, key


def test_sample_file_statuses():
    report = run()
    by_row = {r.row_number: r for r in report.rows}
    assert report.mapping_errors == []
    assert by_row[2].status is RowStatus.NEW
    assert by_row[2].values["base_amount"] == Decimal("150000000")
    assert by_row[2].values["issuing_authority_type"] == "local"
    assert by_row[2].values["winning_rate_basis"] == "estimated_price"
    assert by_row[2].values["estimated_price_status"] == "actual"
    assert by_row[2].values["opening_status"] == "awarded"
    assert by_row[2].phase is NoticePhase.POST_OPENING
    # 사정률 = (149,250,000 − 150,000,000) ÷ 150,000,000 × 100 = −0.5
    assert by_row[2].values["actual_sajeong_rate"] == Decimal("-0.500000")
    # 잘못된 날짜
    assert by_row[6].status is RowStatus.INVALID
    assert any("존재하지 않는 날짜" in e for e in by_row[6].errors)
    # 파일 내 중복
    assert by_row[7].status is RowStatus.DUPLICATE_IN_FILE
    # 개찰일이 지났는데 결과가 없음 → 결과 미확인(유찰로 간주하지 않음)
    assert by_row[8].status is RowStatus.NEW
    assert by_row[8].data_status is DataStatus.RESULT_UNCONFIRMED
    assert by_row[8].values.get("opening_status") is None
    assert report.counts()["new"] == 5


def test_mapping_errors():
    sheet = Sheet("S", ["번호", "이름", "률"], [["1", "a", "87"]])
    r = validate_rows(sheet, {"notice_number": "번호"}, ImportOptions(), none_lookup, no_revs)
    assert any("공고명" in e for e in r.mapping_errors)
    r2 = validate_rows(sheet, {"notice_number": "번호", "title": "이름", "winning_rate": "률"}, ImportOptions(), none_lookup, no_revs)
    assert any("낙찰률 기준" in e for e in r2.mapping_errors)
    r3 = validate_rows(sheet, {"notice_number": "번호", "title": "번호"}, ImportOptions(), none_lookup, no_revs)
    assert any("여러 필드" in e for e in r3.mapping_errors)
    r4 = validate_rows(sheet, {"notice_number": "없음", "title": "이름"}, ImportOptions(), none_lookup, no_revs)
    assert any("파일에 없는 열" in e for e in r4.mapping_errors)


def test_required_values_missing():
    sheet = Sheet("S", ["번호", "이름"], [["", "a"], ["1", ""]])
    r = validate_rows(sheet, {"notice_number": "번호", "title": "이름"}, ImportOptions(), none_lookup, no_revs)
    assert all(x.status is RowStatus.INVALID for x in r.rows)


def test_partial_status_when_key_fields_missing():
    sheet = Sheet("S", ["번호", "이름"], [["1", "a"]])
    r = validate_rows(sheet, {"notice_number": "번호", "title": "이름"}, ImportOptions(now=NOW), none_lookup, no_revs)
    assert r.rows[0].data_status is DataStatus.PARTIAL


def test_failed_with_winner_is_contradiction():
    sheet = Sheet("S", ["번호", "이름", "상태", "낙찰업체"], [["1", "a", "유찰", "가상"]])
    m = {"notice_number": "번호", "title": "이름", "opening_status": "상태", "winning_vendor_name": "낙찰업체"}
    r = validate_rows(sheet, m, ImportOptions(now=NOW), none_lookup, no_revs)
    assert r.rows[0].status is RowStatus.INVALID


def test_estimated_price_without_result_is_user_assumed():
    sheet = Sheet("S", ["번호", "이름", "예정가격"], [["1", "a", "1000"]])
    m = {"notice_number": "번호", "title": "이름", "estimated_price": "예정가격"}
    r = validate_rows(sheet, m, ImportOptions(now=NOW), none_lookup, no_revs)
    assert r.rows[0].values["estimated_price_status"] == "user_assumed"
    assert any("가정값" in w for w in r.rows[0].warnings)


def test_winning_rate_mismatch_warns():
    sheet = Sheet("S", ["번호", "이름", "예정가격", "낙찰금액", "낙찰률"], [["1", "a", "100000000", "88000000", "87.0"]])
    m = {"notice_number": "번호", "title": "이름", "estimated_price": "예정가격", "winning_bid_amount": "낙찰금액", "winning_rate": "낙찰률"}
    opts = ImportOptions(default_winning_rate_basis=RateBasis.ESTIMATED_PRICE, now=NOW)
    r = validate_rows(sheet, m, opts, none_lookup, no_revs)
    assert any("낙찰률 불일치" in w for w in r.rows[0].warnings)


def test_sajeong_outlier_warns():
    sheet = Sheet("S", ["번호", "이름", "기초금액", "예정가격", "낙찰업체"], [["1", "a", "100000000", "120000000", "가상"]])
    m = {"notice_number": "번호", "title": "이름", "base_amount": "기초금액", "estimated_price": "예정가격", "winning_vendor_name": "낙찰업체"}
    r = validate_rows(sheet, m, ImportOptions(now=NOW), none_lookup, no_revs)
    assert any("이상치" in w for w in r.rows[0].warnings)


def test_existing_unchanged_and_changed():
    sheet = Sheet("S", ["번호", "이름", "기초금액"], [["1", "a", "1000"], ["2", "b", "2000"]])
    m = {"notice_number": "번호", "title": "이름", "base_amount": "기초금액"}
    existing = {
        ("1", "000"): ExistingNotice(10, "upload", {"title": "a", "base_amount": Decimal("1000")}),
        ("2", "000"): ExistingNotice(11, "g2b", {"title": "b", "base_amount": Decimal("2500")}),
    }
    r = validate_rows(sheet, m, ImportOptions(now=NOW), lambda n, rev: existing.get((n, rev)), no_revs)
    assert r.rows[0].status is RowStatus.UNCHANGED
    assert r.rows[1].status is RowStatus.CHANGED
    assert r.rows[1].existing_id == 11
    diff = r.rows[1].diffs[0]
    assert (diff.field, diff.old, diff.new) == ("base_amount", "2500", "2000")


def test_new_revision_detected():
    sheet = Sheet("S", ["번호", "차수", "이름"], [["1", "001", "정정"]])
    m = {"notice_number": "번호", "notice_revision": "차수", "title": "이름"}
    r = validate_rows(sheet, m, ImportOptions(now=NOW), none_lookup, lambda n: ["000"])
    assert r.rows[0].status is RowStatus.NEW_REVISION


def test_validation_is_deterministic():
    a = run()
    b = run()
    assert [x.to_dict() for x in a.rows] == [x.to_dict() for x in b.rows]
