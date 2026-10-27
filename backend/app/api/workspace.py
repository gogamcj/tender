"""대시보드, 관심 공고(즐겨찾기), 저장한 검색 조건."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user
from app.api.notices import notice_summary
from app.core.config import get_settings
from app.db.enums import DataStatus, NoticePhase, ReviewStatus
from app.db.models import (
    BidRule,
    DataCollectionJob,
    DataImportJob,
    Favorite,
    NoticeChangeLog,
    PdfExtraction,
    ProcurementNotice,
    SavedFilter,
    User,
)
from app.db.session import get_session
from app.engines.rules import VerificationStatus
from app.services.quota import DEFAULT_DAILY_LIMITS, usage_today

router = APIRouter(tags=["대시보드·관심 공고"])

FILTER_TYPES = {"search", "analysis", "interest"}


def _count(session: Session, q) -> int:
    return session.scalar(select(func.count()).select_from(q.subquery())) or 0


@router.get("/api/dashboard", summary="대시보드 요약")
def dashboard(session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    now = datetime.now(UTC)
    latest = select(ProcurementNotice.id).where(ProcurementNotice.is_latest_revision.is_(True))
    upcoming_q = (
        select(ProcurementNotice)
        .where(ProcurementNotice.is_latest_revision.is_(True), ProcurementNotice.bid_deadline >= now,
               ProcurementNotice.bid_deadline < now + timedelta(days=7), ProcurementNotice.data_status != DataStatus.EXCLUDED)
        .order_by(ProcurementNotice.bid_deadline).limit(10).options(selectinload(ProcurementNotice.results))
    )
    fav_ids = set(session.scalars(select(Favorite.notice_id).where(Favorite.owner_user_id == user.id)))
    review_statuses = (DataStatus.SOURCE_MISMATCH, DataStatus.REVISION_CHECK_NEEDED, DataStatus.DUPLICATE_SUSPECTED, DataStatus.PARTIAL)
    limits = {**DEFAULT_DAILY_LIMITS, **get_settings().api_daily_limits}
    return {
        "generated_at": now.isoformat(),
        "notices": {
            "total": _count(session, latest),
            "pre_opening": _count(session, latest.where(ProcurementNotice.phase == NoticePhase.PRE_OPENING)),
            "needs_review": _count(session, latest.where(ProcurementNotice.data_status.in_(review_statuses))),
            "result_unconfirmed": _count(session, latest.where(ProcurementNotice.data_status == DataStatus.RESULT_UNCONFIRMED)),
            "pending_changes": _count(session, select(NoticeChangeLog.id).where(NoticeChangeLog.applied.is_(False))),
        },
        "upcoming_deadlines": [notice_summary(n) | {"favorite": n.id in fav_ids} for n in session.scalars(upcoming_q)],
        "favorites": len(fav_ids),
        "rules": {
            "total": _count(session, select(BidRule.id)),
            "unverified": _count(session, select(BidRule.id).where(BidRule.verification_status == VerificationStatus.UNVERIFIED)),
        },
        "pdf_unreviewed": _count(session, select(PdfExtraction.id).where(PdfExtraction.review_status == ReviewStatus.UNREVIEWED)),
        "recent_collections": [
            {"id": j.id, "source_name": j.source_name, "operation": j.operation, "status": j.status.value,
             "started_at": j.started_at.isoformat(), "inserted": j.inserted_count, "updated": j.updated_count}
            for j in session.scalars(select(DataCollectionJob).order_by(DataCollectionJob.id.desc()).limit(5))
        ],
        "recent_imports": [
            {"id": j.id, "file_name": j.file_name, "status": j.status.value, "uploaded_at": j.uploaded_at.isoformat(),
             "rows": j.row_count, "accepted": j.accepted_count}
            for j in session.scalars(select(DataImportJob).order_by(DataImportJob.id.desc()).limit(5))
        ],
        "api_usage_today": usage_today(session, limits),
        "api_key_configured": get_settings().data_go_kr_service_key is not None,
    }


# ------------------------------------------------------------------ 관심 공고


class FavoriteIn(BaseModel):
    notice_id: int
    memo: str | None = Field(None, max_length=2000)


def _fav(f: Favorite, n: ProcurementNotice) -> dict:
    return {"id": f.id, "memo": f.memo, "created_at": f.created_at.isoformat(), "notice": notice_summary(n)}


@router.get("/api/favorites", summary="내 관심 공고")
def list_favorites(session: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    rows = session.execute(
        select(Favorite, ProcurementNotice).join(ProcurementNotice, ProcurementNotice.id == Favorite.notice_id)
        .where(Favorite.owner_user_id == user.id).order_by(ProcurementNotice.bid_deadline.is_(None), ProcurementNotice.bid_deadline)
        .options(selectinload(ProcurementNotice.results))
    ).all()
    return [_fav(f, n) for f, n in rows]


@router.post("/api/favorites", status_code=201, summary="관심 공고 추가")
def add_favorite(body: FavoriteIn, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    n = session.get(ProcurementNotice, body.notice_id)
    if n is None:
        raise HTTPException(404, "공고가 없습니다.")
    if session.scalar(select(Favorite).where(Favorite.owner_user_id == user.id, Favorite.notice_id == n.id)):
        raise HTTPException(409, "이미 관심 공고입니다.")
    f = Favorite(owner_user_id=user.id, notice_id=n.id, memo=body.memo)
    session.add(f)
    session.commit()
    return _fav(f, n)


class MemoIn(BaseModel):
    memo: str | None = Field(None, max_length=2000)


def _own_fav(session: Session, fav_id: int, user: User) -> Favorite:
    f = session.get(Favorite, fav_id)
    if f is None or f.owner_user_id != user.id:
        raise HTTPException(404, "관심 공고가 없습니다.")
    return f


@router.patch("/api/favorites/{fav_id}", summary="메모 수정")
def update_favorite(fav_id: int, body: MemoIn, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    f = _own_fav(session, fav_id, user)
    f.memo = body.memo
    session.commit()
    return _fav(f, session.get(ProcurementNotice, f.notice_id))


@router.delete("/api/favorites/{fav_id}", status_code=204, summary="관심 공고 해제")
def delete_favorite(fav_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)) -> None:
    session.delete(_own_fav(session, fav_id, user))
    session.commit()


# ------------------------------------------------------------------ 저장한 조건


class SavedFilterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    filter_type: str = "search"
    criteria: dict


def _sf(s: SavedFilter) -> dict:
    return {"id": s.id, "name": s.name, "filter_type": s.filter_type, "criteria": s.criteria, "created_at": s.created_at.isoformat()}


@router.get("/api/saved-filters")
def list_saved_filters(filter_type: str | None = None, session: Session = Depends(get_session), user: User = Depends(current_user)) -> list[dict]:
    q = select(SavedFilter).where(SavedFilter.owner_user_id == user.id).order_by(SavedFilter.name)
    if filter_type:
        q = q.where(SavedFilter.filter_type == filter_type)
    return [_sf(s) for s in session.scalars(q)]


@router.post("/api/saved-filters", status_code=201)
def create_saved_filter(body: SavedFilterIn, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    if body.filter_type not in FILTER_TYPES:
        raise HTTPException(400, f"filter_type 은 {sorted(FILTER_TYPES)} 중 하나여야 합니다.")
    s = SavedFilter(owner_user_id=user.id, name=body.name, filter_type=body.filter_type, criteria=body.criteria)
    session.add(s)
    session.commit()  # 같은 이름이면 IntegrityError → 409
    return _sf(s)


@router.delete("/api/saved-filters/{sf_id}", status_code=204)
def delete_saved_filter(sf_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)) -> None:
    s = session.get(SavedFilter, sf_id)
    if s is None or s.owner_user_id != user.id:
        raise HTTPException(404, "저장한 조건이 없습니다.")
    session.delete(s)
    session.commit()
