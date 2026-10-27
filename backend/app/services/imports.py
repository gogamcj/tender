"""업로드 작업: 파일 분석 → 열 매핑 미리보기 → 사용자 확인 후 저장 → 결과 보고서 → (필요 시) 되돌리기."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.enums import ImportStatus
from app.db.models import BidResult, DataImportJob, NoticeChangeLog, NoticeRawRecord, ProcurementNotice
from app.importers.fields import TARGET_FIELDS, suggest_mapping
from app.importers.reader import ParsedFile, read_upload
from app.importers.validate import ImportOptions, RowResult, RowStatus, ValidationReport, validate_rows

from . import notices as notice_service

UPLOAD_SOURCE = "upload"
PREVIEW_SAMPLE_ROWS = 5


class ImportError_(RuntimeError):
    """업로드 작업 상태 오류(예: 이미 저장된 작업을 다시 저장)."""


def _storage_path(file_hash: str, ext: str) -> Path:
    base = Path(get_settings().storage_dir) / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{file_hash}.{ext}"


def _load(job: DataImportJob, header_row: int) -> ParsedFile:
    path = _storage_path(job.file_hash, job.source_type)
    return read_upload(job.file_name, path.read_bytes(), header_row=header_row)


def create_job(session: Session, file_name: str, data: bytes, *, header_row: int = 0, user_id: int | None = None) -> tuple[DataImportJob, dict]:
    parsed = read_upload(file_name, data, header_row=header_row)  # 검사 실패 시 FileRejected
    path = _storage_path(parsed.file_hash, parsed.source_type)
    if not path.exists():
        path.write_bytes(data)
    earlier = list(
        session.scalars(
            select(DataImportJob).where(
                DataImportJob.file_hash == parsed.file_hash, DataImportJob.status == ImportStatus.COMMITTED
            )
        )
    )
    job = DataImportJob(
        file_name=file_name,
        file_hash=parsed.file_hash,
        source_type=parsed.source_type,
        encoding=parsed.encoding,
        status=ImportStatus.MAPPING,
        uploaded_by=user_id,
        row_count=sum(s.row_count for s in parsed.sheets),
        column_mapping={"header_row": header_row},
    )
    session.add(job)
    session.flush()
    analysis = {
        "job_id": job.id,
        "file_name": file_name,
        "file_hash": parsed.file_hash,
        "source_type": parsed.source_type,
        "encoding": parsed.encoding,
        "previously_imported_job_ids": [j.id for j in earlier],
        "warnings": [f"같은 파일이 이미 업로드되어 저장된 적이 있습니다(작업 {', '.join(str(j.id) for j in earlier)})."] if earlier else [],
        "sheets": [
            {
                "name": s.name,
                "columns": s.columns,
                "row_count": s.row_count,
                "sample_rows": s.rows[:PREVIEW_SAMPLE_ROWS],
                "suggested_mapping": suggest_mapping(s.columns),
            }
            for s in parsed.sheets
        ],
        "target_fields": [
            {"key": f.key, "label": f.label, "kind": f.kind.value, "required": f.required, "group": f.group,
             "enum_values": sorted(set(f.enum_values)) if f.enum_values else None}
            for f in TARGET_FIELDS
        ],
    }
    return job, analysis


@dataclass
class PreviewRequest:
    sheet_name: str | None
    mapping: dict[str, str]
    options: dict


def _validate(session: Session, job: DataImportJob) -> ValidationReport:
    cfg = job.column_mapping or {}
    header_row = int(cfg.get("header_row", 0))
    parsed = _load(job, header_row)
    sheet = parsed.sheet(cfg.get("sheet_name"))
    return validate_rows(
        sheet,
        cfg.get("mapping", {}),
        ImportOptions.from_dict(cfg.get("options")),
        notice_service.lookup_existing(session),
        notice_service.lookup_revisions(session),
        header_row=header_row,
    )


def preview(session: Session, job: DataImportJob, req: PreviewRequest) -> dict:
    if job.status not in (ImportStatus.MAPPING, ImportStatus.PREVIEW):
        raise ImportError_(f"미리보기를 할 수 없는 상태입니다: {job.status.value}")
    options = ImportOptions.from_dict(req.options)  # 형식 오류는 여기서 ValueError
    job.column_mapping = {
        **(job.column_mapping or {}),
        "sheet_name": req.sheet_name,
        "mapping": req.mapping,
        "options": options.to_dict(),
    }
    job.sheet_name = req.sheet_name
    report = _validate(session, job)
    job.status = ImportStatus.PREVIEW if not report.mapping_errors else ImportStatus.MAPPING
    session.flush()
    return {
        "job_id": job.id,
        "mapping_errors": report.mapping_errors,
        "counts": report.counts(),
        "rows": [r.to_dict() for r in report.rows],
    }


def commit(session: Session, job: DataImportJob, *, accept_changes: list[int], skip_rows: list[int]) -> dict:
    """미리보기와 같은 검증을 다시 돌린 뒤 저장한다.

    - 새 공고·새 차수: 저장
    - 기존과 다른 행: accept_changes 에 행 번호가 있을 때만 변경 반영(변경 전후 기록)
    - 같음·파일 내 중복: 저장 안 함(중복으로 집계)
    - 오류: 저장 안 함(거부로 집계)
    """
    if job.status is not ImportStatus.PREVIEW:
        raise ImportError_(f"저장할 수 없는 상태입니다: {job.status.value} (미리보기 후 저장할 수 있습니다)")
    report = _validate(session, job)
    if report.mapping_errors:
        raise ImportError_("열 매핑 오류가 있어 저장할 수 없습니다.")
    accept, skip = set(accept_changes), set(skip_rows)
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "duplicate_in_file": 0, "rejected": 0, "skipped_by_user": 0, "changes_not_accepted": 0}
    row_log = []
    try:
        with session.begin_nested():
            for r in report.rows:
                outcome = r.status.value
                if r.row_number in skip:
                    counts["skipped_by_user"] += 1
                    outcome = "skipped_by_user"
                elif r.status is RowStatus.INVALID:
                    counts["rejected"] += 1
                elif r.status in (RowStatus.NEW, RowStatus.NEW_REVISION):
                    n = notice_service.create_notice(
                        session, r.values, source_name=UPLOAD_SOURCE, data_status=r.data_status, phase=r.phase,
                        has_result=r.has_result, import_job_id=job.id,
                    )
                    _raw(session, job, n.id, r)
                    counts["inserted"] += 1
                    outcome = "inserted"
                elif r.status is RowStatus.CHANGED:
                    if r.row_number in accept:
                        n = session.get(ProcurementNotice, r.existing_id)
                        assert n is not None
                        notice_service.apply_diffs(
                            session, n, r.diffs, r.values, change_source=f"import:{job.id}", import_job_id=job.id
                        )
                        _raw(session, job, n.id, r)
                        counts["updated"] += 1
                        outcome = "updated"
                    else:
                        counts["changes_not_accepted"] += 1
                        outcome = "changes_not_accepted"
                elif r.status is RowStatus.UNCHANGED:
                    counts["unchanged"] += 1
                else:
                    counts["duplicate_in_file"] += 1
                row_log.append({"row_number": r.row_number, "outcome": outcome, "errors": r.errors, "warnings": r.warnings,
                                "diffs": [d.__dict__ for d in r.diffs]})
    except Exception as exc:
        job.status = ImportStatus.FAILED
        job.error_report = {"fatal": str(exc)}
        session.flush()
        raise
    job.accepted_count = counts["inserted"] + counts["updated"]
    job.rejected_count = counts["rejected"]
    job.duplicate_count = counts["unchanged"] + counts["duplicate_in_file"]
    job.status = ImportStatus.COMMITTED
    job.committed_at = datetime.now(UTC)
    job.error_report = {"counts": counts, "rows": row_log}
    session.flush()
    return {"job_id": job.id, "counts": counts}


def _raw(session: Session, job: DataImportJob, notice_id: int, r: RowResult) -> None:
    payload = {"row_number": r.row_number, "sheet": job.sheet_name, "cells": r.raw}
    session.add(
        NoticeRawRecord(
            notice_id=notice_id,
            source_name=UPLOAD_SOURCE,
            source_record_id=f"{job.id}:{r.row_number}",
            record_kind="upload_row",
            payload=payload,
            payload_hash=hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            import_job_id=job.id,
        )
    )


def rollback(session: Session, job: DataImportJob) -> dict:
    """작업이 새로 만든 공고·결과를 지우고, 반영한 변경은 이전 값으로 되돌린다.

    다른 데이터(분석 기록 등)가 참조하는 공고는 지우지 않고 오류를 낸다(DB 제약).
    """
    if job.status is not ImportStatus.COMMITTED:
        raise ImportError_(f"되돌릴 수 없는 상태입니다: {job.status.value}")
    with session.begin_nested():
        logs = list(
            session.scalars(
                select(NoticeChangeLog)
                .where(NoticeChangeLog.import_job_id == job.id, NoticeChangeLog.applied.is_(True))
                .order_by(NoticeChangeLog.id.desc())
            )
        )
        for log in logs:
            notice_service.revert_change(session, log)
        created = list(session.scalars(select(ProcurementNotice).where(ProcurementNotice.import_job_id == job.id)))
        numbers = {n.notice_number for n in created}
        for res in session.scalars(select(BidResult).where(BidResult.import_job_id == job.id)):
            session.delete(res)
        session.flush()
        for raw in session.scalars(select(NoticeRawRecord).where(NoticeRawRecord.import_job_id == job.id)):
            session.delete(raw)
        for n in created:
            session.delete(n)
        session.flush()
        for number in numbers:
            notice_service.refresh_latest_revision(session, number)
    job.status = ImportStatus.ROLLED_BACK
    session.flush()
    return {"job_id": job.id, "deleted_notices": len(created), "reverted_changes": len(logs)}


def error_report_csv(job: DataImportJob) -> bytes:
    """업로드 결과 보고서(CSV, Excel 호환 UTF-8 BOM)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["작업ID", job.id, "파일", _safe(job.file_name), "생성일시", datetime.now(UTC).isoformat()])
    report = job.error_report or {}
    for k, v in (report.get("counts") or {}).items():
        w.writerow(["집계", k, v])
    w.writerow([])
    w.writerow(["행번호", "처리결과", "오류", "경고", "변경 항목"])
    for row in report.get("rows", []):
        diffs = "; ".join(f"{d['label']}: {d['old']} → {d['new']}" for d in row.get("diffs", []))
        w.writerow([row["row_number"], row["outcome"], _safe(" | ".join(row["errors"])), _safe(" | ".join(row["warnings"])), _safe(diffs)])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _safe(text: str) -> str:
    """CSV 수식 주입 방지: =, +, -, @ 로 시작하면 작은따옴표를 붙인다."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text
