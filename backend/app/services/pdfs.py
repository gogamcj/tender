"""PDF 공고문 업로드·추출·검토·반영.

- 같은 파일(SHA-256)은 한 번만 저장한다.
- 추출값은 '미검토'로 저장되고, 사용자가 확인·수정한 값만 공고에 반영할 수 있다.
- 반영 시 공고에 이미 다른 값이 있으면 덮어쓰지 않고 '보류 변경'으로 남긴다(사용자가 덮어쓰기를 지정한 항목만 반영).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.enums import ReviewStatus
from app.db.models import NoticeChangeLog, PdfDocument, PdfExtraction, ProcurementNotice
from app.importers.validate import FieldDiff
from app.pdf import FIELD_BY_NAME, PdfRejected, extract_fields, open_pdf, parse_value, read_pdf
from app.services import notices as notice_service

# 범위 항목은 공고의 두 칸(하한·상한 비율)에 나눠 넣는다.
SPLIT_TARGETS = {"reserve_range": ("reserve_range_begin_rate", "reserve_range_end_rate")}


class PdfStateError(RuntimeError):
    pass


def storage_path(file_hash: str) -> Path:
    base = Path(get_settings().storage_dir) / "pdf"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{file_hash}.pdf"


def find_by_hash(session: Session, file_hash: str) -> PdfDocument | None:
    return session.scalar(select(PdfDocument).where(PdfDocument.file_hash == file_hash))


def ingest(session: Session, file_name: str, data: bytes, *, notice_id: int | None) -> tuple[PdfDocument, list[str]]:
    file_hash = hashlib.sha256(data).hexdigest()
    with open_pdf(data) as pdf:  # 검사 실패 시 PdfRejected
        content = read_pdf(pdf)
        candidates = extract_fields(content) if content.text_layer == "native" else []
    path = storage_path(file_hash)
    if not path.exists():
        path.write_bytes(data)
    doc = PdfDocument(notice_id=notice_id, file_name=file_name[:300], file_hash=file_hash, page_count=content.page_count,
                      storage_path=str(path), text_layer=content.text_layer)
    session.add(doc)
    session.flush()
    for c in candidates:
        session.add(PdfExtraction(
            document_id=doc.id, field_name=c.field_name, raw_text=c.raw_text, extracted_value=c.value, page_number=c.page_number,
            bbox=c.bbox, table_ref=c.table_ref, confidence=c.confidence, method=c.method,
        ))
    session.flush()
    return doc, content.warnings


def page_text(doc: PdfDocument, page_number: int) -> str:
    data = Path(doc.storage_path).read_bytes()
    with open_pdf(data) as pdf:
        if not (1 <= page_number <= len(pdf.pages)):
            raise PdfRejected("쪽 번호가 범위를 벗어났습니다.")
        return pdf.pages[page_number - 1].extract_text() or ""


def normalize_review_value(field_name: str, raw: str) -> str:
    """사용자가 고친 값을 항목 형식에 맞게 검사·정규화한다. 해석할 수 없으면 ValueError."""
    spec = FIELD_BY_NAME[field_name]
    if spec.kind == "bool":
        if raw in {"True", "False"}:
            return raw
        raise ValueError("True 또는 False 로 입력하세요.")
    if spec.kind in {"text", "code"}:
        v = raw.strip()
        if not v:
            raise ValueError("빈 값입니다.")
        return v[:300]
    if spec.kind == "money":
        v = raw.replace(",", "").strip()
        if not v.isdigit():
            raise ValueError("원 단위 정수로 입력하세요.")
        return str(int(v))
    if spec.kind == "datetime":
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as e:
            raise ValueError("ISO 형식(예: 2026-11-05T10:00:00+09:00)으로 입력하세요.") from e
        if dt.tzinfo is None:
            raise ValueError("시간대가 필요합니다(예: +09:00).")
        return dt.isoformat()
    if spec.kind == "rate":
        v = Decimal(raw.rstrip("%").strip())
        if not (Decimal(0) < v <= Decimal(100)):
            raise ValueError("0 초과 100 이하의 % 값이어야 합니다.")
        return str(v)
    if spec.kind == "range":
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*%?\s*~\s*(-?\d+(?:\.\d+)?)\s*%?\s*", raw)
        if not m or Decimal(m.group(1)) > Decimal(m.group(2)):
            raise ValueError("'-2~2' 처럼 하한~상한(%)으로 입력하세요.")
        return f"{Decimal(m.group(1))}~{Decimal(m.group(2))}"
    # 선택 항목: 알려진 값이면 그 값으로, 아니면 사용자가 확인한 원문 그대로
    value, _, _ = parse_value(spec, raw)
    if value is None and not raw.strip():
        raise ValueError("빈 값입니다.")
    return value or raw.strip()[:60]


def review(session: Session, ex: PdfExtraction, status: ReviewStatus, value: str | None) -> PdfExtraction:
    if status is ReviewStatus.UNREVIEWED:
        ex.reviewed_value = None
    elif status is ReviewStatus.CORRECTED:
        if value is None:
            raise ValueError("수정 값을 입력하세요.")
        ex.reviewed_value = normalize_review_value(ex.field_name, value)
    elif status is ReviewStatus.CONFIRMED:
        if ex.extracted_value is None:
            raise ValueError("해석된 값이 없는 후보는 '확인'할 수 없습니다. 값을 직접 입력해 '수정'으로 처리하세요.")
        ex.reviewed_value = None
    else:
        ex.reviewed_value = None
    ex.review_status = status
    ex.reviewed_at = datetime.now(UTC)
    session.flush()
    return ex


def final_value(ex: PdfExtraction) -> str | None:
    if ex.review_status is ReviewStatus.CORRECTED:
        return ex.reviewed_value
    if ex.review_status is ReviewStatus.CONFIRMED:
        return ex.extracted_value
    return None


def accepted_values(session: Session, doc: PdfDocument) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for ex in session.scalars(select(PdfExtraction).where(PdfExtraction.document_id == doc.id)):
        v = final_value(ex)
        if v is not None:
            out.setdefault(ex.field_name, set()).add(v)
    return out


def _targets(field_name: str, value: str) -> dict[str, str]:
    if field_name in SPLIT_TARGETS:
        lo, hi = value.split("~")
        a, b = SPLIT_TARGETS[field_name]
        return {a: lo, b: hi}
    target = FIELD_BY_NAME[field_name].target
    return {target: value} if target else {}


def apply_to_notice(session: Session, doc: PdfDocument, notice: ProcurementNotice, fields: list[str], overwrite: set[str]) -> dict[str, Any]:
    """검토를 마친 값을 공고에 반영. 결과: 항목별 applied / unchanged / pending(기존 값과 다름) / skipped(사유)."""
    accepted = accepted_values(session, doc)
    report: dict[str, Any] = {}
    for name in fields:
        if name not in FIELD_BY_NAME:
            report[name] = {"status": "skipped", "reason": "알 수 없는 항목"}
            continue
        if name not in SPLIT_TARGETS and FIELD_BY_NAME[name].target is None:
            report[name] = {"status": "skipped", "reason": "참고용 항목이라 공고에 반영하지 않습니다."}
            continue
        values = accepted.get(name, set())
        if not values:
            report[name] = {"status": "skipped", "reason": "확인·수정된 값이 없습니다."}
            continue
        if len(values) > 1:
            report[name] = {"status": "skipped", "reason": f"확인된 값이 서로 다릅니다: {sorted(values)}"}
            continue
        value = next(iter(values))
        for col, text in _targets(name, value).items():
            new = notice_service.parse_stored(col, text)
            old = getattr(notice, col)
            old_text = notice_service._to_text(old)
            new_text = notice_service._to_text(new)
            if old is not None and old_text == new_text:
                report[col] = {"status": "unchanged", "value": new_text}
            elif old is None or name in overwrite:
                notice_service.apply_diffs(session, notice, [FieldDiff(col, col, old_text, new_text)], {col: new},
                                           change_source=f"pdf:{doc.id}")
                report[col] = {"status": "applied", "old": old_text, "new": new_text}
            else:
                log = NoticeChangeLog(notice_id=notice.id, field_name=col, old_value=old_text, new_value=new_text,
                                      change_source=f"pdf:{doc.id}", applied=False)
                session.add(log)
                session.flush()
                report[col] = {"status": "pending", "old": old_text, "new": new_text, "change_log_id": log.id,
                               "reason": "공고에 다른 값이 있어 덮어쓰지 않았습니다. 확인 후 반영하세요."}
    session.flush()
    return report
