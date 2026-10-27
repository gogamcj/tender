"""입찰공고, 원본 레코드, 변경 이력, 개찰·낙찰 결과."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, JSONType, Money, PreciseMoney, Rate, TZDateTime, enum_column, utcnow
from ..enums import DataStatus, LookupStatus, NoticePhase, OpeningStatus, PriceStatus, RateBasis


class ProcurementNotice(Base):
    """입찰공고 기본정보.

    유일성: (source_name, notice_number, notice_revision).
    같은 공고번호의 정정·변경 차수는 각각 별도 행으로 보존하고, is_latest_revision 으로 최신본을 표시한다.
    """

    __tablename__ = "procurement_notices"
    __table_args__ = (
        UniqueConstraint("source_name", "notice_number", "notice_revision"),
        Index("ix_notice_agency_date", "agency_code", "announcement_date"),
        Index("ix_notice_industry_region", "industry_code", "region_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_number: Mapped[str] = mapped_column(String(40), index=True)
    notice_revision: Mapped[str] = mapped_column(String(10), default="000")
    is_latest_revision: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_notices.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500))
    agency_code: Mapped[str | None] = mapped_column(String(20))
    agency_name: Mapped[str | None] = mapped_column(String(200))
    demand_agency_code: Mapped[str | None] = mapped_column(String(20))
    demand_agency_name: Mapped[str | None] = mapped_column(String(200))
    issuing_authority_type: Mapped[str | None] = mapped_column(String(20))  # national/local/public_corp/other
    procurement_type: Mapped[str | None] = mapped_column(String(20))  # construction/service/goods/foreign/other
    bid_type_id: Mapped[int | None] = mapped_column(ForeignKey("bid_types.id", ondelete="SET NULL"))
    contract_method: Mapped[str | None] = mapped_column(String(60))
    award_method: Mapped[str | None] = mapped_column(String(60))
    region_code: Mapped[str | None] = mapped_column(String(20))
    region_name: Mapped[str | None] = mapped_column(String(100))
    industry_code: Mapped[str | None] = mapped_column(String(20))
    industry_name: Mapped[str | None] = mapped_column(String(200))
    announcement_date: Mapped[date | None] = mapped_column(Date, index=True)
    bid_deadline: Mapped[datetime | None] = mapped_column(TZDateTime())
    opening_date: Mapped[datetime | None] = mapped_column(TZDateTime(), index=True)
    base_amount: Mapped[Decimal | None] = mapped_column(Money)  # 기초금액
    presumed_price: Mapped[Decimal | None] = mapped_column(Money)  # 추정가격
    estimated_price: Mapped[Decimal | None] = mapped_column(Money)  # 예정가격(확정 시)
    estimated_price_status: Mapped[PriceStatus] = mapped_column(
        enum_column(PriceStatus, "price_status"), default=PriceStatus.UNKNOWN
    )
    estimated_price_basis: Mapped[str | None] = mapped_column(String(200))  # 예정가격 산정 방식(공고 기재)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Money)  # 설계금액·추정금액 등 공고 기재 비용
    vat_amount: Mapped[Decimal | None] = mapped_column(Money)
    vat_included: Mapped[bool | None] = mapped_column(Boolean)
    lower_limit_rate: Mapped[Decimal | None] = mapped_column(Rate)  # 공고에 기재된 낙찰하한율(%)
    # 복수예비가격 범위(기초금액 대비 %, 공식 데이터·공고문에서 확인된 경우에만)
    reserve_range_begin_rate: Mapped[Decimal | None] = mapped_column(Rate)
    reserve_range_end_rate: Mapped[Decimal | None] = mapped_column(Rate)
    notice_url: Mapped[str | None] = mapped_column(String(1000))
    phase: Mapped[NoticePhase] = mapped_column(enum_column(NoticePhase, "notice_phase"), default=NoticePhase.PRE_OPENING)
    source_name: Mapped[str] = mapped_column(String(60))
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
    data_status: Mapped[DataStatus] = mapped_column(enum_column(DataStatus, "data_status"), default=DataStatus.COLLECTED)
    # 이 행을 새로 만든 업로드 작업(작업 단위 되돌리기에 사용)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"), index=True)

    results: Mapped[list[BidResult]] = relationship(back_populates="notice")


class NoticeRawRecord(Base):
    """수집·업로드 원본. 정규화 데이터와 분리해 보존한다."""

    __tablename__ = "notice_raw_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_notices.id", ondelete="SET NULL"), index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("bid_results.id", ondelete="SET NULL"), index=True)
    source_name: Mapped[str] = mapped_column(String(60))
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    record_kind: Mapped[str] = mapped_column(String(30))  # notice / result / candidate / reserve_price
    payload: Mapped[dict] = mapped_column(JSONType)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    collection_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_collection_jobs.id", ondelete="SET NULL"))
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"))
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class NoticeChangeLog(Base):
    """필드별 변경 전후 값. 정정공고나 재업로드로 값이 바뀔 때 기록한다."""

    __tablename__ = "notice_change_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("procurement_notices.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    change_source: Mapped[str] = mapped_column(String(60))  # revision / import:{job_id} / collection:{job_id} / manual
    applied: Mapped[bool] = mapped_column(Boolean, default=False)  # 사용자가 확인해 반영했는지
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"), index=True)
    changed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class BidResult(Base):
    """개찰·낙찰 결과.

    winning_rate_basis 는 필수다. 기초금액 대비 비율과 예정가격 대비 비율을 섞지 않기 위함이다.
    actual_sajeong_rate 는 내부 정의((예정가격−기초금액)/기초금액×100)로 계산한 값만 넣고,
    외부 데이터가 다른 정의로 준 값은 external_metrics 에 원문 그대로 둔다.
    """

    __tablename__ = "bid_results"
    __table_args__ = (UniqueConstraint("notice_id", "source_name", "rebid_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("procurement_notices.id", ondelete="RESTRICT"), index=True)
    rebid_number: Mapped[int] = mapped_column(Integer, default=0)
    opening_status: Mapped[OpeningStatus] = mapped_column(
        enum_column(OpeningStatus, "opening_status"), default=OpeningStatus.UNCONFIRMED
    )
    lookup_status: Mapped[LookupStatus] = mapped_column(
        enum_column(LookupStatus, "lookup_status"), default=LookupStatus.NOT_QUERIED
    )
    bid_count: Mapped[int | None] = mapped_column(Integer)
    eligible_bid_count: Mapped[int | None] = mapped_column(Integer)
    winning_vendor_name: Mapped[str | None] = mapped_column(String(200))
    winning_vendor_id: Mapped[str | None] = mapped_column(String(40))  # 사업자등록번호 등 공개 식별자
    winning_bid_amount: Mapped[Decimal | None] = mapped_column(Money)
    winning_rate: Mapped[Decimal | None] = mapped_column(Rate)
    winning_rate_basis: Mapped[RateBasis | None] = mapped_column(enum_column(RateBasis, "rate_basis"))
    actual_estimated_price: Mapped[Decimal | None] = mapped_column(Money)
    actual_base_price: Mapped[Decimal | None] = mapped_column(Money)
    actual_sajeong_rate: Mapped[Decimal | None] = mapped_column(Rate)
    lower_limit_amount: Mapped[Decimal | None] = mapped_column(PreciseMoney)
    external_metrics: Mapped[dict | None] = mapped_column(JSONType)
    opening_datetime: Mapped[datetime | None] = mapped_column(TZDateTime(), index=True)
    source_name: Mapped[str] = mapped_column(String(60))
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    verified_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    data_quality_status: Mapped[DataStatus] = mapped_column(
        enum_column(DataStatus, "data_status"), default=DataStatus.COLLECTED
    )
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"), index=True)

    notice: Mapped[ProcurementNotice] = relationship(back_populates="results")
    candidates: Mapped[list[BidCandidate]] = relationship(back_populates="result", cascade="all, delete-orphan")
    reserve_prices: Mapped[list[ReservePrice]] = relationship(back_populates="result", cascade="all, delete-orphan")


class BidCandidate(Base):
    """참여업체별 공개 결과. 공개된 경우에만 저장하며 추정·생성하지 않는다."""

    __tablename__ = "bid_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("bid_results.id", ondelete="CASCADE"), index=True)
    vendor_identifier: Mapped[str | None] = mapped_column(String(40))  # 사업자등록번호 등 공개 식별자
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    bid_amount: Mapped[Decimal | None] = mapped_column(Money)
    bid_rate: Mapped[Decimal | None] = mapped_column(Rate)
    bid_rate_basis: Mapped[RateBasis | None] = mapped_column(enum_column(RateBasis, "rate_basis"))
    ranking: Mapped[int | None] = mapped_column(Integer)
    qualification_status: Mapped[str | None] = mapped_column(String(60))
    source_name: Mapped[str] = mapped_column(String(60))

    result: Mapped[BidResult] = relationship(back_populates="candidates")


class ReservePrice(Base):
    """복수예비가격 상세(공개된 경우)."""

    __tablename__ = "reserve_prices"
    __table_args__ = (UniqueConstraint("result_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("bid_results.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Money)
    drawn: Mapped[bool | None] = mapped_column(Boolean)
    draw_count: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(60))

    result: Mapped[BidResult] = relationship(back_populates="reserve_prices")
