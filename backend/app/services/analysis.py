"""분석용 데이터 적재(DB → Record), 기간·조건 필터, 데이터셋 버전, 분석 실행 기록."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import DataStatus, OpeningStatus
from app.db.models import AnalysisRun, BidResult, ProcurementNotice
from app.engines.stats import Record
from app.importers.parsing import KST

PERIOD_PRESETS = {"3m": 91, "6m": 182, "1y": 365, "3y": 1095}
# 같은 공고에 여러 출처의 결과가 있으면 공식 수집 결과를 우선한다.
RESULT_SOURCE_PRIORITY = {"g2b_scsbid": 0, "g2b_open_std": 1, "upload": 2, "manual": 3}


@dataclass
class Filters:
    period: str | None = "1y"  # 3m / 6m / 1y / 3y / None(전체)
    date_from: date | None = None  # 개찰일 기준(직접 지정 시 period 무시)
    date_to: date | None = None
    as_of: datetime | None = None  # 분석 기준 시각(이 시각 이후 개찰 건 제외). 기본: 지금
    procurement_type: str | None = None
    issuing_authority_type: str | None = None
    contract_method: str | None = None
    award_method: str | None = None
    agency_name: str | None = None  # 부분 일치
    demand_agency_name: str | None = None
    industry_name: str | None = None
    region_name: str | None = None
    keyword: str | None = None  # 공고명 부분 일치
    amount_min: Decimal | None = None  # 기초금액
    amount_max: Decimal | None = None
    bid_count_min: int | None = None
    bid_count_max: int | None = None

    def resolved_period(self) -> tuple[datetime | None, datetime]:
        as_of = self.as_of or datetime.now(UTC)
        if self.date_from or self.date_to:
            start = datetime.combine(self.date_from, time(0), KST) if self.date_from else None
            end = datetime.combine(self.date_to + timedelta(days=1), time(0), KST) if self.date_to else as_of
            return start, min(end, as_of)
        if self.period:
            if self.period not in PERIOD_PRESETS:
                raise ValueError(f"알 수 없는 기간: {self.period}")
            return as_of - timedelta(days=PERIOD_PRESETS[self.period]), as_of
        return None, as_of

    def describe(self) -> dict:
        start, end = self.resolved_period()
        out: dict[str, Any] = {"from": start.isoformat() if start else None, "to": end.isoformat(), "basis": "개찰일시"}
        if self.period and not (self.date_from or self.date_to):
            out["preset"] = self.period
        return out


def _pick_result(results: list[BidResult]) -> BidResult | None:
    usable = [r for r in results if r.opening_status is not OpeningStatus.UNCONFIRMED or r.actual_sajeong_rate is not None]
    if not usable:
        return None
    return sorted(usable, key=lambda r: (r.rebid_number, RESULT_SOURCE_PRIORITY.get(r.source_name, 9), r.id))[0]


def _contains(value: str | None, needle: str | None) -> bool:
    return needle is None or (value is not None and needle.replace(" ", "") in value.replace(" ", ""))


def load_records(session: Session, f: Filters) -> list[Record]:
    start, end = f.resolved_period()
    q = (
        select(ProcurementNotice)
        .where(ProcurementNotice.is_latest_revision.is_(True), ProcurementNotice.data_status != DataStatus.EXCLUDED)
        .options(selectinload(ProcurementNotice.results))
    )
    for col in ("procurement_type", "issuing_authority_type", "contract_method", "award_method"):
        if (v := getattr(f, col)) is not None:
            q = q.where(getattr(ProcurementNotice, col) == v)
    if f.amount_min is not None:
        q = q.where(ProcurementNotice.base_amount >= f.amount_min)
    if f.amount_max is not None:
        q = q.where(ProcurementNotice.base_amount <= f.amount_max)
    records: list[Record] = []
    for n in session.scalars(q):
        res = _pick_result(n.results)
        if res is None:
            continue
        opening = res.opening_datetime or n.opening_date
        if opening is None or opening >= end or (start is not None and opening < start):
            continue
        if not all(
            (
                _contains(n.agency_name, f.agency_name),
                _contains(n.demand_agency_name, f.demand_agency_name),
                _contains(n.industry_name, f.industry_name),
                _contains(n.region_name, f.region_name),
                _contains(n.title, f.keyword),
            )
        ):
            continue
        if f.bid_count_min is not None and (res.bid_count is None or res.bid_count < f.bid_count_min):
            continue
        if f.bid_count_max is not None and (res.bid_count is None or res.bid_count > f.bid_count_max):
            continue
        records.append(
            Record(
                notice_id=n.id, opening_date=opening, announcement_date=n.announcement_date,
                procurement_type=n.procurement_type, issuing_authority_type=n.issuing_authority_type,
                contract_method=n.contract_method, award_method=n.award_method, agency_name=n.agency_name,
                demand_agency_name=n.demand_agency_name, industry_name=n.industry_name, region_name=n.region_name,
                base_amount=n.base_amount or res.actual_base_price, presumed_price=n.presumed_price,
                estimated_price=res.actual_estimated_price, sajeong_rate=res.actual_sajeong_rate,
                winning_rate=res.winning_rate, rate_basis=res.winning_rate_basis.value if res.winning_rate_basis else None,
                bid_count=res.bid_count, lower_limit_rate=n.lower_limit_rate, source_name=res.source_name, title=n.title,
            )
        )
    return records


def dataset_version(records: list[Record], as_of: datetime | None) -> str:
    h = hashlib.sha256()
    for r in sorted(records, key=lambda x: x.notice_id):
        h.update(f"{r.notice_id}|{r.sajeong_rate}|{r.winning_rate}|{r.rate_basis}|{r.bid_count}|{r.base_amount};".encode())
    return f"n={len(records)};as_of={(as_of or datetime.now(UTC)).isoformat(timespec='seconds')};sha256={h.hexdigest()[:16]}"


def save_run(session: Session, *, analysis_type: str, notice_id: int | None, inputs: dict, records: list[Record],
             as_of: datetime | None, result: dict, assumptions: list[str], confidence: str) -> AnalysisRun:
    run = AnalysisRun(
        notice_id=notice_id, analysis_type=analysis_type, input_snapshot=inputs, rule_version=None,
        dataset_version=dataset_version(records, as_of), assumptions=assumptions, result_summary=result,
        confidence_status=confidence,
    )
    session.add(run)
    session.flush()
    return run
