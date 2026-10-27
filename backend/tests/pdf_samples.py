"""테스트용 가상 공고문 PDF 생성(reportlab, 내장 한글 CID 글꼴). 실제 공고문이 아니다."""

from __future__ import annotations

import io

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

FONT = "HYSMyeongJo-Medium"
rl_config.invariant = 1  # 같은 내용이면 같은 바이트(생성 시각·문서 ID 고정)
pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def build_notice_pdf(*, lines: list[str] | None = None, table: list[list[str]] | None = None,
                     page2_lines: list[str] | None = None) -> bytes:
    style = ParagraphStyle("k", fontName=FONT, fontSize=10, leading=14)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story: list = []
    for ln in lines or []:
        story.append(Paragraph(ln, style))
    if table:
        t = Table(table, colWidths=[120, 300])
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), FONT, 10), ("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
        story += [Spacer(1, 12), t]
    if page2_lines:
        from reportlab.platypus import PageBreak

        story.append(PageBreak())
        for ln in page2_lines:
            story.append(Paragraph(ln, style))
    doc.build(story)
    return buf.getvalue()


SAMPLE_LINES = [
    "[가상] 입찰공고",
    "입찰공고번호: R26BK00000001-000",
    "공고명: [샘플] 가상 도로 정비공사",
    "공고기관: 샘플시청  수요기관: 샘플시 도로과",
    "계약방법: 제한경쟁입찰(총액)",
    "낙찰자 결정방법: 적격심사",
    "입찰마감일시: 2026.11.05(목) 10:00",
    "개찰일시: 2026년 11월 5일 11시 00분",
    "예비가격 범위: 기초금액의 ±2% 범위에서 복수예비가격 15개 작성",
    "기초금액 및 추정가격은 부가가치세 포함 금액입니다.",
    "A값: 12,345,000원",
]
SAMPLE_TABLE = [
    ["기초금액", "금 812,345,000원"],
    ["추정가격", "738,495,455원"],
    ["낙찰하한율", "87.745%"],
    ["참가자격", "토목공사업 등록업체"],
]


def sample_notice_pdf() -> bytes:
    return build_notice_pdf(lines=SAMPLE_LINES, table=SAMPLE_TABLE, page2_lines=["지역제한: 가상도 소재 업체", "낙찰하한율: 87.745%"])
