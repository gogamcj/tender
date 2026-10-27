"""PDF 공고문 텍스트·표 추출.

- 텍스트 레이어가 있는 PDF 만 처리한다. 스캔 이미지 PDF(텍스트 없음)는 'none' 으로 표시하고 OCR 은 하지 않는다.
- 암호화·손상·용량·쪽수 초과 파일은 거부한다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.psparser import PSException

MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 300
MIN_CHARS_PER_PAGE = 20  # 이보다 적으면 텍스트 레이어가 없는 것으로 본다


class PdfRejected(ValueError):
    pass


@dataclass
class PageContent:
    number: int  # 1부터
    text: str
    lines: list[str]
    tables: list[list[list[str | None]]]
    width: float
    height: float
    _page: object = field(default=None, repr=False)


@dataclass
class PdfContent:
    page_count: int
    pages: list[PageContent]
    text_layer: str  # native / none
    warnings: list[str]


def check_bytes(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise PdfRejected(f"파일이 너무 큽니다(최대 {MAX_BYTES // 1024 // 1024}MB).")
    if not data.startswith(b"%PDF-"):
        raise PdfRejected("PDF 파일이 아닙니다.")


def open_pdf(data: bytes) -> pdfplumber.PDF:
    check_bytes(data)
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        n = len(pdf.pages)
    except PDFPasswordIncorrect as e:
        raise PdfRejected("암호가 걸린 PDF 는 처리하지 않습니다.") from e
    except (PSException, ValueError, KeyError, TypeError) as e:
        raise PdfRejected(f"PDF 를 읽을 수 없습니다: {type(e).__name__}") from e
    if n > MAX_PAGES:
        pdf.close()
        raise PdfRejected(f"쪽수가 너무 많습니다(최대 {MAX_PAGES}쪽).")
    if getattr(pdf.doc, "encryption", None):
        pdf.close()
        raise PdfRejected("암호화된 PDF 는 처리하지 않습니다.")
    return pdf


def read_pdf(pdf: pdfplumber.PDF) -> PdfContent:
    pages: list[PageContent] = []
    total = 0
    for i, p in enumerate(pdf.pages, start=1):
        text = p.extract_text() or ""
        total += len(text.strip())
        try:
            tables = p.extract_tables()
        except Exception:  # noqa: BLE001  표 인식 실패는 텍스트 추출을 막지 않는다
            tables = []
        pages.append(PageContent(i, text, [ln.strip() for ln in text.splitlines() if ln.strip()], tables, float(p.width), float(p.height), p))
    warnings: list[str] = []
    layer = "native"
    if not pages or total < MIN_CHARS_PER_PAGE * len(pages):
        layer = "none"
        warnings.append("NO_TEXT_LAYER: 텍스트를 거의 찾지 못했습니다. 스캔 이미지 PDF 로 보이며 OCR 은 지원하지 않습니다.")
    return PdfContent(len(pages), pages, layer, warnings)
