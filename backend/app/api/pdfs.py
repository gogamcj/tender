"""PDF 공고문 업로드·항목 추출·검토·공고 반영 API."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ReviewStatus
from app.db.models import PdfDocument, PdfExtraction, ProcurementNotice
from app.db.session import get_session
from app.pdf import FIELD_BY_NAME, PdfRejected, summarize_candidates
from app.pdf.extract import MAX_BYTES
from app.services import notices as notice_service
from app.services import pdfs as pdf_service

router = APIRouter(prefix="/api/pdfs", tags=["PDF 공고문"])

NOTE = "자동 추출 값은 검토 전에는 공고에 반영되지 않습니다. 쪽 번호와 원문을 확인한 뒤 확인·수정하세요."


def _ex(e: PdfExtraction) -> dict:
    return {"id": e.id, "field_name": e.field_name, "raw_text": e.raw_text, "value": e.extracted_value, "page_number": e.page_number,
            "bbox": e.bbox, "table_ref": e.table_ref, "confidence": e.confidence, "method": e.method,
            "review_status": e.review_status.value, "reviewed_value": e.reviewed_value,
            "final_value": pdf_service.final_value(e)}


def _doc(session: Session, d: PdfDocument) -> dict:
    exs = [_ex(e) for e in session.scalars(select(PdfExtraction).where(PdfExtraction.document_id == d.id).order_by(PdfExtraction.id))]
    fields = summarize_candidates(exs)
    if d.notice_id is not None and (n := session.get(ProcurementNotice, d.notice_id)) is not None:
        for name, f in fields.items():
            cols = pdf_service.SPLIT_TARGETS.get(name) or ((FIELD_BY_NAME[name].target,) if FIELD_BY_NAME[name].target else ())
            f["notice_value"] = {c: notice_service._to_text(getattr(n, c)) for c in cols} or None
    unreviewed = sum(1 for e in exs if e["review_status"] == "unreviewed")
    return {"id": d.id, "file_name": d.file_name, "file_hash": d.file_hash, "page_count": d.page_count, "text_layer": d.text_layer,
            "notice_id": d.notice_id, "uploaded_at": d.uploaded_at.isoformat(), "extraction_count": len(exs),
            "unreviewed_count": unreviewed, "fields": fields, "note": NOTE}


@router.post("", status_code=201, summary="PDF 공고문 업로드 및 항목 후보 추출")
async def upload_pdf(file: UploadFile = File(...), notice_id: int | None = Form(None), session: Session = Depends(get_session)) -> dict:
    data = await file.read(MAX_BYTES + 1)
    if notice_id is not None and session.get(ProcurementNotice, notice_id) is None:
        raise HTTPException(404, "공고가 없습니다.")
    existing = pdf_service.find_by_hash(session, hashlib.sha256(data).hexdigest())
    if existing is not None:
        raise HTTPException(409, {"message": "이미 올린 파일입니다.", "document_id": existing.id})
    try:
        doc, warnings = pdf_service.ingest(session, file.filename or "notice.pdf", data, notice_id=notice_id)
    except PdfRejected as e:
        raise HTTPException(400, str(e)) from e
    session.commit()
    return _doc(session, doc) | {"warnings": warnings}


@router.get("", summary="PDF 목록")
def list_pdfs(notice_id: int | None = None, session: Session = Depends(get_session)) -> list[dict]:
    q = select(PdfDocument).order_by(PdfDocument.id.desc()).limit(200)
    if notice_id is not None:
        q = q.where(PdfDocument.notice_id == notice_id)
    return [{"id": d.id, "file_name": d.file_name, "page_count": d.page_count, "text_layer": d.text_layer, "notice_id": d.notice_id,
             "uploaded_at": d.uploaded_at.isoformat()} for d in session.scalars(q)]


def _get(session: Session, doc_id: int) -> PdfDocument:
    d = session.get(PdfDocument, doc_id)
    if d is None:
        raise HTTPException(404, "PDF 가 없습니다.")
    return d


@router.get("/{doc_id}", summary="추출 항목(후보·쪽·신뢰도·불일치·공고 값 비교)")
def get_pdf(doc_id: int, session: Session = Depends(get_session)) -> dict:
    return _doc(session, _get(session, doc_id))


@router.get("/{doc_id}/pages/{page_number}", summary="쪽 원문 텍스트(근거 확인용)")
def get_page(doc_id: int, page_number: int, session: Session = Depends(get_session)) -> dict:
    d = _get(session, doc_id)
    try:
        return {"document_id": d.id, "page_number": page_number, "text": pdf_service.page_text(d, page_number)}
    except PdfRejected as e:
        raise HTTPException(400, str(e)) from e


class LinkIn(BaseModel):
    notice_id: int | None


@router.patch("/{doc_id}", summary="공고 연결")
def link_pdf(doc_id: int, body: LinkIn, session: Session = Depends(get_session)) -> dict:
    d = _get(session, doc_id)
    if body.notice_id is not None and session.get(ProcurementNotice, body.notice_id) is None:
        raise HTTPException(404, "공고가 없습니다.")
    d.notice_id = body.notice_id
    session.commit()
    return _doc(session, d)


class ReviewIn(BaseModel):
    review_status: ReviewStatus
    value: str | None = Field(None, max_length=300)


@router.patch("/{doc_id}/extractions/{ex_id}", summary="추출 값 검토(확인·수정·기각)")
def review_extraction(doc_id: int, ex_id: int, body: ReviewIn, session: Session = Depends(get_session)) -> dict:
    ex = session.get(PdfExtraction, ex_id)
    if ex is None or ex.document_id != doc_id:
        raise HTTPException(404, "추출 항목이 없습니다.")
    try:
        pdf_service.review(session, ex, body.review_status, body.value)
    except (ValueError, ArithmeticError) as e:
        raise HTTPException(422, str(e)) from e
    session.commit()
    return _ex(ex)


class ManualFieldIn(BaseModel):
    field_name: str
    value: str = Field(max_length=300)
    page_number: int | None = None


@router.post("/{doc_id}/extractions", status_code=201, summary="추출하지 못한 항목을 직접 입력(수정 상태로 저장)")
def add_manual(doc_id: int, body: ManualFieldIn, session: Session = Depends(get_session)) -> dict:
    d = _get(session, doc_id)
    if body.field_name not in FIELD_BY_NAME:
        raise HTTPException(400, "알 수 없는 항목입니다.")
    ex = PdfExtraction(document_id=d.id, field_name=body.field_name, raw_text=None, extracted_value=None, page_number=body.page_number,
                       confidence=None, method="manual")
    session.add(ex)
    session.flush()
    try:
        pdf_service.review(session, ex, ReviewStatus.CORRECTED, body.value)
    except (ValueError, ArithmeticError) as e:
        session.rollback()
        raise HTTPException(422, str(e)) from e
    session.commit()
    return _ex(ex)


class ApplyIn(BaseModel):
    fields: list[str]
    overwrite: list[str] = Field(default_factory=list, description="공고에 다른 값이 있어도 덮어쓸 항목(명시적으로 지정)")


@router.post("/{doc_id}/apply", summary="검토된 값을 연결된 공고에 반영(다른 값은 보류 변경으로)")
def apply_pdf(doc_id: int, body: ApplyIn, session: Session = Depends(get_session)) -> dict:
    d = _get(session, doc_id)
    if d.notice_id is None:
        raise HTTPException(400, "먼저 공고를 연결하세요.")
    n = session.get(ProcurementNotice, d.notice_id)
    report = pdf_service.apply_to_notice(session, d, n, body.fields, set(body.overwrite))
    session.commit()
    return {"document_id": d.id, "notice_id": n.id, "report": report}
