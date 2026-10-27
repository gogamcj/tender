"""엑셀·CSV 업로드 API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DataImportJob
from app.db.session import get_session
from app.importers.reader import MAX_FILE_BYTES, FileRejected
from app.services import imports as import_service

router = APIRouter(prefix="/api/imports", tags=["엑셀 업로드"])


def _job(session: Session, job_id: int) -> DataImportJob:
    job = session.get(DataImportJob, job_id)
    if job is None:
        raise HTTPException(404, "업로드 작업이 없습니다.")
    return job


def _summary(job: DataImportJob) -> dict:
    return {
        "id": job.id,
        "file_name": job.file_name,
        "source_type": job.source_type,
        "encoding": job.encoding,
        "status": job.status.value,
        "uploaded_at": job.uploaded_at.isoformat(),
        "committed_at": job.committed_at.isoformat() if job.committed_at else None,
        "row_count": job.row_count,
        "accepted_count": job.accepted_count,
        "rejected_count": job.rejected_count,
        "duplicate_count": job.duplicate_count,
    }


@router.post("", status_code=201, summary="1~2단계: 파일 업로드 및 시트·열 분석")
async def upload(
    file: UploadFile = File(...),
    header_row: int = Query(0, ge=0, le=50, description="헤더가 있는 행(0부터)"),
    session: Session = Depends(get_session),
) -> dict:
    data = await file.read(MAX_FILE_BYTES + 1)
    try:
        job, analysis = import_service.create_job(session, file.filename or "upload", data, header_row=header_row)
    except FileRejected as e:
        raise HTTPException(400, str(e)) from e
    session.commit()
    return analysis


@router.get("")
def list_jobs(session: Session = Depends(get_session)) -> list[dict]:
    return [_summary(j) for j in session.scalars(select(DataImportJob).order_by(DataImportJob.id.desc()).limit(200))]


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = _job(session, job_id)
    return {**_summary(job), "column_mapping": job.column_mapping, "report": job.error_report}


class PreviewIn(BaseModel):
    sheet_name: str | None = None
    mapping: dict[str, str] = Field(description="{대상필드: 원본 열 이름}")
    options: dict = Field(default_factory=dict)


@router.post("/{job_id}/preview", summary="3~8단계: 열 매핑 적용, 형식 변환, 누락·중복·오류 검사, 미리보기")
def post_preview(job_id: int, body: PreviewIn, session: Session = Depends(get_session)) -> dict:
    job = _job(session, job_id)
    try:
        out = import_service.preview(session, job, import_service.PreviewRequest(body.sheet_name, body.mapping, body.options))
    except (import_service.ImportError_, FileRejected, ValueError) as e:
        raise HTTPException(409 if isinstance(e, import_service.ImportError_) else 400, str(e)) from e
    session.commit()
    return out


class CommitIn(BaseModel):
    accept_changes: list[int] = Field(default_factory=list, description="기존 데이터 변경을 반영할 행 번호")
    skip_rows: list[int] = Field(default_factory=list, description="저장하지 않을 행 번호")


@router.post("/{job_id}/commit", summary="9~10단계: 사용자 확인 후 저장, 결과 보고")
def post_commit(job_id: int, body: CommitIn, session: Session = Depends(get_session)) -> dict:
    job = _job(session, job_id)
    try:
        out = import_service.commit(session, job, accept_changes=body.accept_changes, skip_rows=body.skip_rows)
    except import_service.ImportError_ as e:
        raise HTTPException(409, str(e)) from e
    except Exception:
        session.commit()  # 작업 상태(FAILED)와 오류 기록은 남긴다. 저장 중이던 데이터는 savepoint 로 이미 취소됨
        raise
    session.commit()
    return out


@router.post("/{job_id}/rollback", summary="업로드 작업 되돌리기")
def post_rollback(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = _job(session, job_id)
    try:
        out = import_service.rollback(session, job)
    except import_service.ImportError_ as e:
        raise HTTPException(409, str(e)) from e
    session.commit()
    return out


@router.get("/{job_id}/report.csv", summary="업로드 결과·오류 보고서 CSV")
def get_report(job_id: int, session: Session = Depends(get_session)) -> Response:
    job = _job(session, job_id)
    return Response(
        import_service.error_report_csv(job),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import_{job.id}_report.csv"'},
    )
