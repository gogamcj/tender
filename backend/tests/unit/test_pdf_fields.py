from decimal import Decimal

import pytest

from app.pdf import FIELD_BY_NAME, PdfRejected, extract_fields, open_pdf, parse_value, read_pdf, summarize_candidates
from tests.pdf_samples import build_notice_pdf, sample_notice_pdf


def _extract(data: bytes):
    with open_pdf(data) as pdf:
        content = read_pdf(pdf)
        return content, extract_fields(content)


def by_field(cands):
    out = {}
    for c in cands:
        out.setdefault(c.field_name, []).append(c)
    return out


def test_sample_notice_fields_with_page_and_bbox():
    content, cands = _extract(sample_notice_pdf())
    assert content.page_count == 2 and content.text_layer == "native"
    f = by_field(cands)
    assert f["notice_number"][0].value == "R26BK00000001-000"
    assert f["base_amount"][0].value == "812345000"
    assert f["presumed_price"][0].value == "738495455"
    assert f["a_value"][0].value == "12345000"
    assert f["bid_deadline"][0].value == "2026-11-05T10:00:00+09:00"
    assert f["opening_date"][0].value == "2026-11-05T11:00:00+09:00"
    assert f["contract_method"][0].value == "제한경쟁"
    assert f["award_method"][0].value == "적격심사"
    assert f["reserve_range"][0].value == "-2~2"
    assert f["vat_included"][0].value == "True" and f["vat_included"][0].method == "keyword"
    assert f["agency_name"][0].value == "샘플시청" and f["demand_agency_name"][0].value == "샘플시 도로과"
    assert f["qualification"][0].method == "table"
    # 같은 값이 두 쪽에서 나오면 쪽마다 후보로 남는다
    assert sorted(c.page_number for c in f["lower_limit_rate"]) == [1, 2]
    for c in cands:
        assert c.page_number >= 1 and 0 < c.confidence <= 1
        assert c.bbox is None or len(c.bbox) == 4
    # 문장 속 '기초금액' 언급(±2% 범위 설명, 부가세 안내 문장)은 후보가 되지 않는다
    assert [c.value for c in f["base_amount"]] == ["812345000"]


def test_conflicting_values_reported_not_resolved():
    data = build_notice_pdf(lines=["기초금액: 100,000,000원", "기초금액: 120,000,000원", "낙찰하한율: 87.745%"])
    _, cands = _extract(data)
    s = summarize_candidates([c.to_dict() | {"review_status": "unreviewed"} for c in cands])
    assert s["base_amount"]["conflict"] is True and s["base_amount"]["distinct_values"] == ["100000000", "120000000"]
    assert s["lower_limit_rate"]["conflict"] is False
    assert s["presumed_price"]["found"] is False


def test_units_other_than_won_are_not_converted():
    spec = FIELD_BY_NAME["base_amount"]
    assert parse_value(spec, "1,234천원")[0] is None
    assert parse_value(spec, "12억원")[0] is None
    assert parse_value(spec, "금 1,000원")[0] == "1000"
    assert parse_value(spec, "1,000")[1] < parse_value(spec, "1,000원")[1]  # 단위 없으면 신뢰도 낮춤


def test_rate_datetime_enum_parsing():
    assert parse_value(FIELD_BY_NAME["lower_limit_rate"], "87.745 %")[0] == "87.745"
    assert parse_value(FIELD_BY_NAME["lower_limit_rate"], "150%")[0] is None
    assert parse_value(FIELD_BY_NAME["lower_limit_rate"], "87.745")[0] is None  # % 없으면 해석하지 않음
    assert parse_value(FIELD_BY_NAME["opening_date"], "2026-02-30 10:00")[0] is None
    assert parse_value(FIELD_BY_NAME["opening_date"], "2026/11/05 14:30")[0] == "2026-11-05T14:30:00+09:00"
    assert parse_value(FIELD_BY_NAME["award_method"], "적격심사 또는 최저가")[0] is None  # 여러 값 → 고르지 않음
    assert parse_value(FIELD_BY_NAME["reserve_range"], "-3% ~ +3%")[0] == "-3~3"


def test_reject_bad_files():
    with pytest.raises(PdfRejected):
        open_pdf(b"not a pdf")
    with pytest.raises(PdfRejected):
        open_pdf(b"%PDF-1.4\n garbage")


def test_blank_pdf_has_no_text_layer():
    data = build_notice_pdf(lines=[" "])
    content, _ = _extract(data)
    assert content.text_layer == "none" and content.warnings[0].startswith("NO_TEXT_LAYER")


def test_decimal_not_float():
    _, cands = _extract(sample_notice_pdf())
    rate = next(c for c in cands if c.field_name == "lower_limit_rate")
    assert Decimal(rate.value) == Decimal("87.745")
