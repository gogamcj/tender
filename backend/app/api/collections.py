"""공식 데이터 수집 관리 API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import require_admin
from app.connectors.specs import NOTICE_FIELD_MAP, OPERATIONS, QueryMode, operation_label
from app.core.config import get_settings
from app.db.models import DataCollectionJob
from app.db.session import get_session, get_session_factory
from app.services import collection as svc
from app.services.quota import DEFAULT_DAILY_LIMITS, DailyQuota, usage_today

router = APIRouter(prefix="/api/collections", tags=["데이터 수집"])


def daily_limits() -> dict[str, int]:
    return {**DEFAULT_DAILY_LIMITS, **get_settings().api_daily_limits}


def get_client_factory() -> svc.ClientFactory:
    key = get_settings().data_go_kr_service_key
    return svc.default_client_factory(key.get_secret_value() if key else None)


@router.get("/sources", summary="수집 가능한 공식 API 오퍼레이션, 근거 수준, 오늘 사용량")
def sources(session: Session = Depends(get_session)) -> dict:
    return {
        "service_key_configured": get_settings().data_go_kr_service_key is not None,
        "usage_today": usage_today(session, daily_limits()),
        "operations": [
            {
                "key": s.key, "label": s.label, "source_name": s.source_name, "operation": s.operation,
                "handler": s.handler.value, "procurement_type": s.procurement_type, "evidence": s.evidence,
                "date_types": [d for d in s.inqry_div if d != "notice"], "by_notice_number": "notice" in s.inqry_div,
                "max_window_days": s.max_window_days, "search_params": list(s.search_params),
            }
            for s in OPERATIONS.values()
        ],
        "notice_field_map": {k: {"field": f, "evidence": e} for k, (f, e) in NOTICE_FIELD_MAP.items()},
    }


class CollectIn(BaseModel):
    operation_key: str
    mode: QueryMode = QueryMode.DATE_RANGE
    date_from: date | None = None
    date_to: date | None = None
    date_type: str = "posted"
    notice_number: str | None = None
    search: dict[str, str] = Field(default_factory=dict)
    max_pages: int = Field(50, ge=1, le=500)


@router.post("", status_code=202, dependencies=[Depends(require_admin)], summary="수집 작업 시작(백그라운드)")
def start(
    body: CollectIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    factory: sessionmaker[Session] = Depends(get_session_factory),
    client_factory: svc.ClientFactory = Depends(get_client_factory),
) -> dict:
    req = svc.CollectionRequest(**body.model_dump())
    try:
        spec = svc.validate_request(req)
    except svc.CollectionRequestError as e:
        raise HTTPException(400, str(e)) from e
    job = DataCollectionJob(source_name=spec.source_name, operation=spec.operation, query_parameters=req.to_dict())
    session.add(job)
    session.commit()
    quota = DailyQuota(factory, spec.source_name, daily_limits().get(spec.source_name, 1000))
    background.add_task(svc.collect_in_new_session, factory, job.id, req, client_factory, quota.check_and_increment)
    return {"job_id": job.id, "status": job.status.value}


def _out(job: DataCollectionJob) -> dict:
    return {
        "id": job.id, "source_name": job.source_name, "operation": job.operation,
        "operation_label": operation_label(job.source_name, job.operation), "query_parameters": job.query_parameters,
        "status": job.status.value, "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "request_count": job.request_count, "inserted_count": job.inserted_count, "updated_count": job.updated_count,
        "skipped_count": job.skipped_count, "error_summary": job.error_summary,
    }


@router.get("", summary="수집 이력")
def history(session: Session = Depends(get_session)) -> list[dict]:
    return [_out(j) for j in session.scalars(select(DataCollectionJob).order_by(DataCollectionJob.id.desc()).limit(200))]


@router.get("/{job_id}")
def detail(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(DataCollectionJob, job_id)
    if job is None:
        raise HTTPException(404, "수집 작업이 없습니다.")
    return _out(job)
