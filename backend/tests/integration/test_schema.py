"""마이그레이션으로 만든 스키마가 유일성·외래키·삭제 정책·상태값 제약을 실제로 지키는지 확인한다."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, StatementError

from app.db.enums import DataStatus, OpeningStatus, PriceStatus, RateBasis
from app.db.models import BidCandidate, BidResult, ProcurementNotice, ReservePrice


def notice(**kw) -> ProcurementNotice:
    data = dict(
        notice_number="R24BK00000001",
        notice_revision="000",
        title="샘플 공고(테스트)",
        source_name="sample",
        announcement_date=date(2024, 6, 1),
        base_amount=Decimal("100000000"),
    )
    data.update(kw)
    return ProcurementNotice(**data)


def test_all_tables_created(engine):
    names = set(inspect(engine).get_table_names())
    expected = {
        "procurement_notices", "bid_results", "bid_candidates", "bid_rules", "analysis_runs", "bid_scenarios",
        "company_costs", "data_import_jobs", "data_collection_jobs", "company_profiles", "saved_filters",
        "notice_raw_records", "notice_change_log", "reserve_prices", "bid_types", "notice_rule_links",
        "qualification_checks", "pdf_documents", "pdf_extractions", "users", "favorites", "api_call_counters", "app_events",
    }
    assert expected <= names


def test_notice_revision_uniqueness(session):
    session.add(notice())
    session.commit()
    session.add(notice(notice_revision="001", title="정정 공고"))  # 다른 차수는 허용
    session.commit()
    session.add(notice())  # 같은 출처·번호·차수는 거부
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_number_from_different_source_allowed(session):
    session.add(notice())
    session.add(notice(source_name="upload"))
    session.commit()


def test_money_keeps_exact_decimal(session):
    n = notice(base_amount=Decimal("123456789012345678"))
    session.add(n)
    session.commit()
    session.expire_all()
    got = session.scalar(select(ProcurementNotice.base_amount))
    assert got == Decimal("123456789012345678")


def test_rate_precision(session):
    n = notice()
    session.add(n)
    session.flush()
    r = BidResult(notice_id=n.id, source_name="sample", winning_rate=Decimal("87.745123"), winning_rate_basis=RateBasis.ESTIMATED_PRICE)
    session.add(r)
    session.commit()
    session.expire_all()
    assert session.scalar(select(BidResult.winning_rate)) == Decimal("87.745123")


def test_result_defaults_to_unconfirmed_not_failed(session):
    n = notice()
    session.add(n)
    session.flush()
    r = BidResult(notice_id=n.id, source_name="sample")
    session.add(r)
    session.commit()
    assert r.opening_status is OpeningStatus.UNCONFIRMED
    assert n.estimated_price_status is PriceStatus.UNKNOWN
    assert n.data_status is DataStatus.COLLECTED


def test_notice_with_results_cannot_be_deleted(session):
    n = notice()
    session.add(n)
    session.flush()
    session.add(BidResult(notice_id=n.id, source_name="sample"))
    session.commit()
    session.delete(n)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_deleting_result_cascades_candidates_and_reserve_prices(session):
    n = notice()
    session.add(n)
    session.flush()
    r = BidResult(notice_id=n.id, source_name="sample")
    r.candidates.append(BidCandidate(vendor_name="공개업체A", bid_amount=Decimal("88000000"), ranking=1, source_name="sample"))
    r.reserve_prices.append(ReservePrice(seq=1, amount=Decimal("99000000"), source_name="sample"))
    session.add(r)
    session.commit()
    session.delete(r)
    session.commit()
    assert session.scalar(select(BidCandidate.id)) is None
    assert session.scalar(select(ReservePrice.id)) is None


def test_invalid_status_value_rejected(session):
    n = notice()
    n.data_status = "made_up_status"  # type: ignore[assignment]
    session.add(n)
    with pytest.raises((StatementError, LookupError, IntegrityError)):
        session.commit()
    session.rollback()


def test_reserve_price_seq_unique(session):
    n = notice()
    session.add(n)
    session.flush()
    r = BidResult(notice_id=n.id, source_name="sample")
    session.add(r)
    session.flush()
    session.add_all([ReservePrice(result_id=r.id, seq=1, amount=Decimal(1), source_name="s"),
                     ReservePrice(result_id=r.id, seq=1, amount=Decimal(2), source_name="s")])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_money_rejects_silent_rounding(session):
    session.add(notice(base_amount=Decimal("100.5")))
    with pytest.raises(StatementError):
        session.commit()
    session.rollback()


def test_money_rejects_float(session):
    session.add(notice(base_amount=100.0))
    with pytest.raises(StatementError):
        session.commit()
    session.rollback()
