"""입찰 유형 분류 체계와 계산 규칙."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, JSONType, Money, TZDateTime, enum_column, utcnow
from ..enums import LinkSource, VerificationStatus


class BidType(Base):
    """입찰 유형: 명칭이 아니라 계산 규칙·심사 기준을 연결하는 분류 단위."""

    __tablename__ = "bid_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    procurement_category: Mapped[str] = mapped_column(String(20))  # construction/service/goods/foreign/other
    sub_category: Mapped[str | None] = mapped_column(String(60))  # 종합/전문/전기/정보통신/소방/음향영상 ...
    issuing_authority_type: Mapped[str | None] = mapped_column(String(20))
    contract_method: Mapped[str | None] = mapped_column(String(60))
    award_method: Mapped[str | None] = mapped_column(String(60))
    amount_min: Mapped[Decimal | None] = mapped_column(Money)
    amount_max_exclusive: Mapped[Decimal | None] = mapped_column(Money)
    region_restriction: Mapped[str | None] = mapped_column(String(100))
    required_licenses: Mapped[list | None] = mapped_column(JSONType)
    applicable_regulation: Mapped[str | None] = mapped_column(String(300))
    is_user_defined: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class BidRule(Base):
    __tablename__ = "bid_rules"
    __table_args__ = (UniqueConstraint("rule_code", "source_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(80), index=True)
    rule_name: Mapped[str] = mapped_column(String(200))
    procurement_type: Mapped[str] = mapped_column(String(20), default="any")
    issuing_authority_type: Mapped[str] = mapped_column(String(20), default="any")
    contract_method: Mapped[str] = mapped_column(String(60), default="any")
    award_method: Mapped[str] = mapped_column(String(60), default="any")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    source_document: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_version: Mapped[str] = mapped_column(String(40), default="1")
    formula_definition: Mapped[dict] = mapped_column(JSONType)
    rounding_rule: Mapped[dict | None] = mapped_column(JSONType)
    applicability: Mapped[dict | None] = mapped_column(JSONType)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column(VerificationStatus, "verification_status"), default=VerificationStatus.UNVERIFIED
    )
    verified_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class BidTypeRule(Base):
    __tablename__ = "bid_type_rules"

    bid_type_id: Mapped[int] = mapped_column(ForeignKey("bid_types.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("bid_rules.id", ondelete="RESTRICT"), primary_key=True)


class NoticeRuleLink(Base):
    """공고별 적용 규칙. 자동 매칭 결과와 사용자 확정 여부를 함께 남긴다."""

    __tablename__ = "notice_rule_links"

    notice_id: Mapped[int] = mapped_column(ForeignKey("procurement_notices.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("bid_rules.id", ondelete="RESTRICT"), primary_key=True)
    link_source: Mapped[LinkSource] = mapped_column(enum_column(LinkSource, "link_source"))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
