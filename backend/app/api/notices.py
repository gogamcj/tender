"""입찰공고 검색·상세·수동 입력·상태 관리 API."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import LABELS, DataStatus, NoticePhase, PriceStatus
from app.db.models import BidResult, NoticeChangeLog, NoticeRawRecord, ProcurementNotice
from app.db.session import get_session
from app.importers.parsing import KST
from app.importers.validate import FieldDiff
from app.services import notices as notice_service

router = APIRouter(prefix="/api/notices", tags=["입찰공고"])


def _v(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, datetime | date):
        return x.isoformat()
    return x.value if hasattr(x, "value") else x


def notice_summary(n: ProcurementNotice) -> dict:
    res = notice_service.primary_result(n) if "results" in n.__dict__ else None
    return {
        "id": n.id, "notice_number": n.notice_number, "notice_revision": n.notice_revision, "title": n.title,
        "agency_name": n.agency_name, "demand_agency_name": n.demand_agency_name, "procurement_type": n.procurement_type,
        "issuing_authority_type": n.issuing_authority_type, "contract_method": n.contract_method, "award_method": n.award_method,
        "region_name": n.region_name, "industry_name": n.industry_name,
        "announcement_date": _v(n.announcement_date), "bid_deadline": _v(n.bid_deadline), "opening_date": _v(n.opening_date),
        "base_amount": _v(n.base_amount), "presumed_price": _v(n.presumed_price), "estimated_price": _v(n.estimated_price),
        "estimated_price_status": _v(n.estimated_price_status), "lower_limit_rate": _v(n.lower_limit_rate),
        "phase": _v(n.phase), "data_status": _v(n.data_status), "data_status_label": LABELS.get(n.data_status, ""),
        "is_latest_revision": n.is_latest_revision, "source_name": n.source_name, "notice_url": n.notice_url,
        "result": None if res is None else {
            "opening_status": _v(res.opening_status), "opening_status_label": LABELS.get(res.opening_status, ""),
            "winning_vendor_name": res.winning_vendor_name, "winning_bid_amount": _v(res.winning_bid_amount),
            "winning_rate": _v(res.winning_rate), "winning_rate_basis": _v(res.winning_rate_basis),
            "actual_sajeong_rate": _v(res.actual_sajeong_rate), "bid_count": res.bid_count,
        },
    }


def search_params(
    q: str | None = Query(None, description="공고명·공고번호 검색어"),
    agency: str | None = None,
    industry: str | None = None,
    region: str | None = None,
    procurement_type: str | None = None,
    issuing_authority_type: str | None = None,
    award_method: str | None = None,
    amount_min: Decimal | None = Query(None, description="기초금액(없으면 추정가격) 하한"),
    amount_max: Decimal | None = None,
    date_from: date | None = Query(None, description="공고일 시작"),
    date_to: date | None = None,
    opening_from: date | None = Query(None, description="개찰일 시작"),
    opening_to: date | None = None,
    data_status: DataStatus | None = None,
    phase: NoticePhase | None = None,
    has_result: bool | None = None,
    latest_only: bool = True,
    sort: str = Query("-announcement_date", pattern="^-?(announcement_date|opening_date|base_amount|id)$"),
) -> dict:
    """검색 조건(목록 화면과 내보내기에서 같이 쓴다)."""
    return dict(locals())


def search_statement(p: dict):
    stmt = select(ProcurementNotice)
    if p["latest_only"]:
        stmt = stmt.where(ProcurementNotice.is_latest_revision.is_(True))
    if p["q"]:
        like = f"%{p['q'].strip()}%"
        stmt = stmt.where(or_(ProcurementNotice.title.ilike(like), ProcurementNotice.notice_number.ilike(like)))
    if agency := p["agency"]:
        stmt = stmt.where(or_(ProcurementNotice.agency_name.ilike(f"%{agency}%"), ProcurementNotice.demand_agency_name.ilike(f"%{agency}%")))
    if p["industry"]:
        stmt = stmt.where(ProcurementNotice.industry_name.ilike(f"%{p['industry']}%"))
    if p["region"]:
        stmt = stmt.where(ProcurementNotice.region_name.ilike(f"%{p['region']}%"))
    for key in ("procurement_type", "issuing_authority_type", "award_method", "data_status", "phase"):
        if p[key] is not None:
            stmt = stmt.where(getattr(ProcurementNotice, key) == p[key])
    amount = func.coalesce(ProcurementNotice.base_amount, ProcurementNotice.presumed_price)
    if p["amount_min"] is not None:
        stmt = stmt.where(amount >= p["amount_min"])
    if p["amount_max"] is not None:
        stmt = stmt.where(amount <= p["amount_max"])
    if p["date_from"]:
        stmt = stmt.where(ProcurementNotice.announcement_date >= p["date_from"])
    if p["date_to"]:
        stmt = stmt.where(ProcurementNotice.announcement_date <= p["date_to"])
    if p["opening_from"]:
        stmt = stmt.where(ProcurementNotice.opening_date >= datetime.combine(p["opening_from"], time(0), KST))
    if p["opening_to"]:
        stmt = stmt.where(ProcurementNotice.opening_date < datetime.combine(p["opening_to"] + timedelta(days=1), time(0), KST))
    if p["has_result"] is not None:
        exists = select(BidResult.id).where(BidResult.notice_id == ProcurementNotice.id).exists()
        stmt = stmt.where(exists if p["has_result"] else ~exists)
    return stmt


def search_order(p: dict):
    sort = p["sort"]
    col = getattr(ProcurementNotice, sort.lstrip("-"))
    return (col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last()), ProcurementNotice.id.desc()


@router.get("", summary="입찰공고 검색(금액·날짜·기관·공종 등)")
def search(
    params: dict = Depends(search_params),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict:
    stmt = search_statement(params)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(
        stmt.options(selectinload(ProcurementNotice.results)).order_by(*search_order(params))
        .offset((page - 1) * size).limit(size)
    )
    return {"total": total, "page": page, "size": size, "items": [notice_summary(n) for n in rows]}


@router.get("/{notice_id}", summary="공고 상세(결과·예비가격·참여업체·변경이력·차수)")
def detail(notice_id: int, session: Session = Depends(get_session)) -> dict:
    n = session.get(ProcurementNotice, notice_id, options=[selectinload(ProcurementNotice.results)])
    if n is None:
        raise HTTPException(404, "공고가 없습니다.")
    revisions = session.scalars(
        select(ProcurementNotice).where(ProcurementNotice.notice_number == n.notice_number).order_by(ProcurementNotice.notice_revision)
    )
    logs = session.scalars(select(NoticeChangeLog).where(NoticeChangeLog.notice_id == n.id).order_by(NoticeChangeLog.id.desc()))
    raw_count = session.scalar(select(func.count()).select_from(NoticeRawRecord).where(NoticeRawRecord.notice_id == n.id))
    out = notice_summary(n)
    out.update({
        "agency_code": n.agency_code, "demand_agency_code": n.demand_agency_code, "region_code": n.region_code,
        "industry_code": n.industry_code, "estimated_cost": _v(n.estimated_cost), "vat_amount": _v(n.vat_amount),
        "vat_included": n.vat_included, "estimated_price_basis": n.estimated_price_basis,
        "reserve_range_begin_rate": _v(n.reserve_range_begin_rate), "reserve_range_end_rate": _v(n.reserve_range_end_rate),
        "collected_at": _v(n.collected_at), "last_updated_at": _v(n.last_updated_at), "source_record_id": n.source_record_id,
        "raw_record_count": raw_count,
        "revisions": [{"id": r.id, "notice_revision": r.notice_revision, "title": r.title, "is_latest": r.is_latest_revision} for r in revisions],
        "results": [
            {
                "id": r.id, "source_name": r.source_name, "rebid_number": r.rebid_number, "opening_status": _v(r.opening_status),
                "lookup_status": _v(r.lookup_status), "bid_count": r.bid_count, "winning_vendor_name": r.winning_vendor_name,
                "winning_bid_amount": _v(r.winning_bid_amount), "winning_rate": _v(r.winning_rate),
                "winning_rate_basis": _v(r.winning_rate_basis), "actual_estimated_price": _v(r.actual_estimated_price),
                "actual_base_price": _v(r.actual_base_price), "actual_sajeong_rate": _v(r.actual_sajeong_rate),
                "external_metrics": r.external_metrics, "opening_datetime": _v(r.opening_datetime),
                "reserve_prices": [{"seq": p.seq, "amount": _v(p.amount), "drawn": p.drawn} for p in sorted(r.reserve_prices, key=lambda p: p.seq)],
                "candidates": [{"ranking": c.ranking, "vendor_name": c.vendor_name, "bid_amount": _v(c.bid_amount),
                                "bid_rate": _v(c.bid_rate), "bid_rate_basis": _v(c.bid_rate_basis), "qualification_status": c.qualification_status}
                               for c in sorted(r.candidates, key=lambda c: (c.ranking is None, c.ranking or 0))],
            }
            for r in n.results
        ],
        "change_log": [{"id": c.id, "field_name": c.field_name, "old_value": c.old_value, "new_value": c.new_value,
                        "change_source": c.change_source, "applied": c.applied, "changed_at": _v(c.changed_at)} for c in logs],
    })
    return out


class ManualNoticeIn(BaseModel):
    notice_number: str = Field(min_length=1, max_length=40)
    notice_revision: str = "000"
    title: str = Field(min_length=1, max_length=500)
    agency_name: str | None = None
    demand_agency_name: str | None = None
    procurement_type: str | None = None
    issuing_authority_type: str | None = None
    contract_method: str | None = None
    award_method: str | None = None
    region_name: str | None = None
    industry_name: str | None = None
    announcement_date: date | None = None
    bid_deadline: datetime | None = None
    opening_date: datetime | None = None
    base_amount: Decimal | None = Field(None, ge=0, decimal_places=0)
    presumed_price: Decimal | None = Field(None, ge=0, decimal_places=0)
    vat_amount: Decimal | None = Field(None, ge=0, decimal_places=0)
    vat_included: bool | None = None
    lower_limit_rate: Decimal | None = Field(None, gt=0, le=100, decimal_places=6)
    notice_url: str | None = None


@router.post("", status_code=201, summary="공고 수동 입력(API 장애 시에도 사용 가능)")
def create_manual(body: ManualNoticeIn, session: Session = Depends(get_session)) -> dict:
    if notice_service.find_notice(session, body.notice_number, body.notice_revision):
        raise HTTPException(409, "같은 공고번호·차수가 이미 있습니다. 상세 화면에서 확인하세요.")
    for dt in (body.bid_deadline, body.opening_date):
        if dt is not None and dt.tzinfo is None:
            raise HTTPException(422, "일시에는 시간대가 필요합니다(예: 2024-06-18T11:00:00+09:00).")
    values = body.model_dump()
    values["estimated_price_status"] = PriceStatus.UNKNOWN.value
    status = DataStatus.PARTIAL if body.base_amount is None or body.announcement_date is None else DataStatus.COLLECTED
    n = notice_service.create_notice(session, values, source_name="manual", data_status=status,
                                     phase=NoticePhase.PRE_OPENING, has_result=False)
    session.commit()
    return notice_summary(n)


class StatusIn(BaseModel):
    data_status: DataStatus


@router.patch("/{notice_id}/status", summary="데이터 상태 변경(예: 분석 제외, 검증 완료)")
def set_status(notice_id: int, body: StatusIn, session: Session = Depends(get_session)) -> dict:
    n = session.get(ProcurementNotice, notice_id)
    if n is None:
        raise HTTPException(404, "공고가 없습니다.")
    old = n.data_status
    n.data_status = body.data_status
    session.add(NoticeChangeLog(notice_id=n.id, field_name="data_status", old_value=old.value, new_value=body.data_status.value,
                                change_source="manual", applied=True))
    session.commit()
    return notice_summary(n)


@router.post("/{notice_id}/changes/{log_id}/apply", summary="보류된 변경(공식 값과 불일치) 반영")
def apply_pending(notice_id: int, log_id: int, session: Session = Depends(get_session)) -> dict:
    n = session.get(ProcurementNotice, notice_id)
    log = session.get(NoticeChangeLog, log_id)
    if n is None or log is None or log.notice_id != n.id:
        raise HTTPException(404, "변경 기록이 없습니다.")
    if log.applied:
        raise HTTPException(409, "이미 반영된 변경입니다.")
    if log.field_name not in notice_service.NOTICE_COLUMNS:
        raise HTTPException(400, "이 항목은 여기서 반영할 수 없습니다.")
    value = notice_service.parse_stored(log.field_name, log.new_value)
    notice_service.apply_diffs(session, n, [FieldDiff(log.field_name, log.field_name, log.old_value, log.new_value)],
                               {log.field_name: value}, change_source=f"manual-apply:{log.id}")
    log.applied = True
    pending = session.scalar(select(func.count()).select_from(NoticeChangeLog).where(
        NoticeChangeLog.notice_id == n.id, NoticeChangeLog.applied.is_(False)))
    if not pending and n.data_status is DataStatus.SOURCE_MISMATCH:
        n.data_status = DataStatus.COLLECTED
    session.commit()
    return notice_summary(n)
