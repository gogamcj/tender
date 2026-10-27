"""공고·결과 저장, 정정 차수 관리, 확인된 변경 반영."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import DataStatus, LookupStatus, NoticePhase, OpeningStatus, PriceStatus, RateBasis
from app.db.models import BidResult, NoticeChangeLog, ProcurementNotice
from app.importers.validate import ExistingNotice, FieldDiff

# 업로드 필드 → 공고 컬럼
NOTICE_COLUMNS = (
    "notice_number", "notice_revision", "title", "agency_code", "agency_name", "demand_agency_code",
    "demand_agency_name", "issuing_authority_type", "procurement_type", "contract_method", "award_method",
    "region_code", "region_name", "industry_code", "industry_name", "announcement_date", "bid_deadline",
    "opening_date", "base_amount", "presumed_price", "estimated_cost", "vat_amount", "vat_included",
    "lower_limit_rate", "notice_url", "estimated_price", "estimated_price_status",
    "reserve_range_begin_rate", "reserve_range_end_rate",
)  # fmt: skip
# 업로드 필드 → 결과 컬럼
RESULT_COLUMNS = {
    "opening_status": "opening_status",
    "bid_count": "bid_count",
    "winning_vendor_name": "winning_vendor_name",
    "winning_bid_amount": "winning_bid_amount",
    "winning_rate": "winning_rate",
    "winning_rate_basis": "winning_rate_basis",
    "actual_sajeong_rate": "actual_sajeong_rate",
}
_ENUM_COLUMNS = {
    "estimated_price_status": PriceStatus,
    "opening_status": OpeningStatus,
    "winning_rate_basis": RateBasis,
}


def _revision_key(rev: str) -> tuple[int, str]:
    return (int(rev), rev) if re.fullmatch(r"\d+", rev) else (-1, rev)


def primary_result(notice: ProcurementNotice) -> BidResult | None:
    results = sorted(notice.results, key=lambda r: (r.rebid_number, r.id))
    return results[0] if results else None


def existing_values(notice: ProcurementNotice) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for col in NOTICE_COLUMNS:
        v = getattr(notice, col)
        values[col] = v.value if hasattr(v, "value") else v
    res = primary_result(notice)
    if res is not None:
        for key, col in RESULT_COLUMNS.items():
            v = getattr(res, col)
            values[key] = v.value if hasattr(v, "value") else v
    return values


def find_notice(session: Session, notice_number: str, revision: str) -> ProcurementNotice | None:
    """출처와 상관없이 같은 공고번호·차수를 찾는다(출처가 달라도 같은 공고를 중복 저장하지 않기 위함)."""
    return session.scalars(
        select(ProcurementNotice)
        .where(ProcurementNotice.notice_number == notice_number, ProcurementNotice.notice_revision == revision)
        .order_by(ProcurementNotice.id)
    ).first()


def lookup_existing(session: Session):
    def _lookup(notice_number: str, revision: str) -> ExistingNotice | None:
        n = find_notice(session, notice_number, revision)
        if n is None:
            return None
        return ExistingNotice(n.id, n.source_name, existing_values(n))

    return _lookup


def lookup_revisions(session: Session):
    def _revs(notice_number: str) -> list[str]:
        return list(
            session.scalars(
                select(ProcurementNotice.notice_revision).where(ProcurementNotice.notice_number == notice_number).distinct()
            )
        )

    return _revs


def refresh_latest_revision(session: Session, notice_number: str) -> None:
    """같은 공고번호의 차수 중 가장 큰 차수만 최신으로 표시한다."""
    rows = list(session.scalars(select(ProcurementNotice).where(ProcurementNotice.notice_number == notice_number)))
    if not rows:
        return
    latest = max(rows, key=lambda n: _revision_key(n.notice_revision))
    for n in rows:
        n.is_latest_revision = n is latest
        n.superseded_by_id = None if n is latest else latest.id
    session.flush()


def _coerce(col: str, value: Any) -> Any:
    if value is None:
        return None
    if col in _ENUM_COLUMNS:
        return _ENUM_COLUMNS[col](value)
    return value


def create_notice(
    session: Session,
    values: dict[str, Any],
    *,
    source_name: str,
    data_status: DataStatus,
    phase: NoticePhase,
    has_result: bool,
    import_job_id: int | None = None,
) -> ProcurementNotice:
    kwargs = {c: _coerce(c, values.get(c)) for c in NOTICE_COLUMNS if values.get(c) is not None}
    if "estimated_price_status" not in kwargs:
        kwargs["estimated_price_status"] = PriceStatus.UNKNOWN
    notice = ProcurementNotice(
        **kwargs, source_name=source_name, data_status=data_status, phase=phase, import_job_id=import_job_id
    )
    session.add(notice)
    session.flush()
    if has_result:
        _upsert_result(session, notice, values, source_name=source_name, import_job_id=import_job_id)
    refresh_latest_revision(session, notice.notice_number)
    return notice


def _upsert_result(
    session: Session, notice: ProcurementNotice, values: dict[str, Any], *, source_name: str, import_job_id: int | None
) -> BidResult:
    res = primary_result(notice)
    if res is None:
        res = BidResult(notice_id=notice.id, source_name=source_name, import_job_id=import_job_id, rebid_number=0)
        session.add(res)
        notice.results.append(res)
    for key, col in RESULT_COLUMNS.items():
        if values.get(key) is not None:
            setattr(res, col, _coerce(col, values[key]))
    if values.get("estimated_price") is not None and values.get("estimated_price_status") == PriceStatus.ACTUAL.value:
        res.actual_estimated_price = values["estimated_price"]
    if values.get("base_amount") is not None:
        res.actual_base_price = values["base_amount"]
    if values.get("opening_date") is not None:
        res.opening_datetime = values["opening_date"]
    res.lookup_status = LookupStatus.FOUND
    session.flush()
    return res


def _to_text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime | date):
        return v.isoformat()
    return str(v.value if hasattr(v, "value") else v)


def apply_diffs(
    session: Session,
    notice: ProcurementNotice,
    diffs: list[FieldDiff],
    new_values: dict[str, Any],
    *,
    change_source: str,
    import_job_id: int | None = None,
) -> int:
    """사용자가 확인한 변경만 반영하고, 필드별 변경 전후를 기록한다."""
    result_values: dict[str, Any] = {}
    for d in diffs:
        session.add(
            NoticeChangeLog(
                notice_id=notice.id,
                field_name=d.field,
                old_value=d.old,
                new_value=d.new,
                change_source=change_source,
                applied=True,
                import_job_id=import_job_id,
            )
        )
        if d.field in NOTICE_COLUMNS:
            setattr(notice, d.field, _coerce(d.field, new_values[d.field]))
        if d.field in RESULT_COLUMNS or d.field in {"estimated_price", "base_amount", "opening_date"}:
            result_values[d.field] = new_values[d.field]
    if any(k in RESULT_COLUMNS for k in result_values):
        merged = {**new_values}
        _upsert_result(session, notice, merged, source_name=notice.source_name, import_job_id=None)
    session.flush()
    return len(diffs)


def revert_change(session: Session, log: NoticeChangeLog) -> None:
    """변경 기록의 이전 값으로 되돌린다(업로드 작업 되돌리기용)."""
    notice = session.get(ProcurementNotice, log.notice_id)
    if notice is None:
        return
    old = parse_stored(log.field_name, log.old_value)
    if log.field_name in NOTICE_COLUMNS:
        setattr(notice, log.field_name, old)
    if log.field_name in RESULT_COLUMNS:
        res = primary_result(notice)
        if res is not None:
            setattr(res, RESULT_COLUMNS[log.field_name], old)
    log.applied = False
    session.flush()


def parse_stored(field: str, text: str | None) -> Any:
    if text is None:
        return None
    if field in _ENUM_COLUMNS:
        return _ENUM_COLUMNS[field](text)
    column = ProcurementNotice.__table__.c.get(field)
    if column is None and field in RESULT_COLUMNS:
        column = BidResult.__table__.c.get(RESULT_COLUMNS[field])
    if column is None:
        return text
    pytype = column.type.python_type
    if pytype is Decimal:
        return Decimal(text)
    if pytype is int:
        return int(text)
    if pytype is bool:
        return text == "True"
    if pytype is datetime:
        return datetime.fromisoformat(text)
    if pytype is date:
        return date.fromisoformat(text)
    return text
