"""업로드·수집 이력, API 호출 카운터, 오류·경고 로그."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, JSONType, TZDateTime, enum_column, utcnow
from ..enums import CollectionStatus, ImportStatus


class DataImportJob(Base):
    __tablename__ = "data_import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(300))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(20))  # xlsx / xls / csv
    encoding: Mapped[str | None] = mapped_column(String(20))
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    target_kind: Mapped[str] = mapped_column(String(30), default="notice_result")
    column_mapping: Mapped[dict | None] = mapped_column(JSONType)
    status: Mapped[ImportStatus] = mapped_column(enum_column(ImportStatus, "import_status"), default=ImportStatus.ANALYZING)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_report: Mapped[dict | None] = mapped_column(JSONType)


class DataCollectionJob(Base):
    __tablename__ = "data_collection_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(60), index=True)
    operation: Mapped[str | None] = mapped_column(String(100))
    query_parameters: Mapped[dict] = mapped_column(JSONType)
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    status: Mapped[CollectionStatus] = mapped_column(
        enum_column(CollectionStatus, "collection_status"), default=CollectionStatus.PENDING
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[dict | None] = mapped_column(JSONType)


class ApiCallCounter(Base):
    """API 별 일일 호출 수. 한도 초과를 막기 위해 호출 전에 확인한다."""

    __tablename__ = "api_call_counters"

    source_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    call_date: Mapped[date] = mapped_column(Date, primary_key=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)


class AppEvent(Base):
    """오류·경고 기록."""

    __tablename__ = "app_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(10), index=True)  # info / warning / error
    category: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
