"""분석 실행, 투찰 시나리오, 원가, 적격심사, PDF 추출."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, JSONType, Money, Rate, TZDateTime, enum_column, utcnow
from ..enums import PriceStatus, RateBasis, ReviewStatus, ScoreStatus


class AnalysisRun(Base):
    """분석 실행 기록. input_snapshot 과 rule_version, dataset_version 으로 결과를 재현한다."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_notices.id", ondelete="RESTRICT"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    analysis_type: Mapped[str] = mapped_column(String(40))  # calc / reserve / stats / similar / recommend / cost / qualify
    input_snapshot: Mapped[dict] = mapped_column(JSONType)
    rule_version: Mapped[dict | None] = mapped_column(JSONType)  # {rule_code: source_version}
    dataset_version: Mapped[str | None] = mapped_column(String(100))  # 데이터 해시 + 건수 + 기준시각
    assumptions: Mapped[list | None] = mapped_column(JSONType)
    result_summary: Mapped[dict | None] = mapped_column(JSONType)
    confidence_status: Mapped[str] = mapped_column(String(40))  # definitive / assumption_based / insufficient_data / blocked
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class BidScenario(Base):
    __tablename__ = "bid_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    scenario_name: Mapped[str] = mapped_column(String(60))  # conservative / moderate / aggressive / custom
    target_rate: Mapped[Decimal | None] = mapped_column(Rate)
    rate_basis: Mapped[RateBasis | None] = mapped_column(enum_column(RateBasis, "rate_basis"))
    candidate_amount: Mapped[Decimal | None] = mapped_column(Money)
    assumed_estimated_price: Mapped[Decimal | None] = mapped_column(Money)
    assumed_price_status: Mapped[PriceStatus] = mapped_column(
        enum_column(PriceStatus, "price_status"), default=PriceStatus.SCENARIO
    )
    estimated_profit: Mapped[Decimal | None] = mapped_column(Money)
    estimated_margin: Mapped[Decimal | None] = mapped_column(Rate)
    risk_flags: Mapped[list | None] = mapped_column(JSONType)
    explanation: Mapped[dict | None] = mapped_column(JSONType)


class CompanyCost(Base):
    """업체 원가(민감 자료). owner_user_id 와 관리자만 조회한다."""

    __tablename__ = "company_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_notices.id", ondelete="SET NULL"), index=True)
    material_cost: Mapped[Decimal | None] = mapped_column(Money)
    labor_cost: Mapped[Decimal | None] = mapped_column(Money)
    equipment_cost: Mapped[Decimal | None] = mapped_column(Money)
    subcontract_cost: Mapped[Decimal | None] = mapped_column(Money)
    transport_cost: Mapped[Decimal | None] = mapped_column(Money)
    site_overhead: Mapped[Decimal | None] = mapped_column(Money)
    general_overhead: Mapped[Decimal | None] = mapped_column(Money)
    statutory_costs: Mapped[Decimal | None] = mapped_column(Money)
    other_costs: Mapped[Decimal | None] = mapped_column(Money)
    vat_treatment: Mapped[str | None] = mapped_column(String(30))  # excluded / included / exempt
    target_profit: Mapped[Decimal | None] = mapped_column(Money)
    target_profit_rate: Mapped[Decimal | None] = mapped_column(Rate)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class QualificationCheck(Base):
    """적격심사·참가자격 항목별 검토. 미확인 항목은 0점이나 만점으로 처리하지 않는다."""

    __tablename__ = "qualification_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("procurement_notices.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_code: Mapped[str] = mapped_column(String(60))
    item_name: Mapped[str] = mapped_column(String(200))
    max_score: Mapped[Decimal | None] = mapped_column(Rate)
    score: Mapped[Decimal | None] = mapped_column(Rate)
    score_status: Mapped[ScoreStatus] = mapped_column(enum_column(ScoreStatus, "score_status"), default=ScoreStatus.UNKNOWN)
    basis: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(String(300))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class PdfDocument(Base):
    __tablename__ = "pdf_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_notices.id", ondelete="SET NULL"), index=True)
    file_name: Mapped[str] = mapped_column(String(300))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    text_layer: Mapped[str | None] = mapped_column(String(20))  # native / ocr / none
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class PdfExtraction(Base):
    __tablename__ = "pdf_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("pdf_documents.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(60))
    raw_text: Mapped[str | None] = mapped_column(Text)
    extracted_value: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONType)
    table_ref: Mapped[str | None] = mapped_column(String(60))
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(30))  # regex / table / ocr
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus, "review_status"), default=ReviewStatus.UNREVIEWED
    )
    reviewed_value: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
