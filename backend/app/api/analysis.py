"""과거 개찰 결과 분석, 사정률 분포, 유사 입찰 검색 API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import ProcurementNotice
from app.db.session import get_session
from app.engines.stats import ALLOWED_DIMENSIONS, METRICS, Target, compute_stats, find_similar, histogram
from app.services.analysis import Filters, dataset_version, load_records, save_run

router = APIRouter(prefix="/api/analysis", tags=["분석"])

DISCLAIMER = "과거에 관측된 결과의 요약입니다. 미래 예정가격이나 낙찰 결과를 예측·보장하지 않습니다."


class FiltersIn(BaseModel):
    period: str | None = "1y"
    date_from: str | None = None
    date_to: str | None = None
    as_of: datetime | None = None
    procurement_type: str | None = None
    issuing_authority_type: str | None = None
    contract_method: str | None = None
    award_method: str | None = None
    agency_name: str | None = None
    demand_agency_name: str | None = None
    industry_name: str | None = None
    region_name: str | None = None
    keyword: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    bid_count_min: int | None = None
    bid_count_max: int | None = None

    def to_filters(self) -> Filters:
        from datetime import date

        data = self.model_dump()
        data["date_from"] = date.fromisoformat(self.date_from) if self.date_from else None
        data["date_to"] = date.fromisoformat(self.date_to) if self.date_to else None
        return Filters(**data)


class StatsIn(BaseModel):
    filters: FiltersIn = Field(default_factory=FiltersIn)
    metric: str = "sajeong_rate"
    group_by: list[str] = Field(default_factory=list)
    exclude_outliers: bool = False
    trend: str | None = "month"
    save: bool = False


@router.get("/options", summary="지표·분류 기준 목록")
def options() -> dict:
    return {"metrics": {k: {"label": v[0], "definition": v[1]} for k, v in METRICS.items()}, "dimensions": ALLOWED_DIMENSIONS}


def _filters(body_filters: FiltersIn) -> Filters:
    try:
        f = body_filters.to_filters()
        f.resolved_period()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return f


@router.post("/stats", summary="과거 개찰 결과 통계(조건별 분리, 이상치·누락률 포함)")
def stats(body: StatsIn, session: Session = Depends(get_session)) -> dict:
    f = _filters(body.filters)
    records = load_records(session, f)
    try:
        result = compute_stats(records, body.metric, group_by=body.group_by, exclude_outliers=body.exclude_outliers,
                               period=f.describe(), trend=body.trend).to_dict()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    result["disclaimer"] = DISCLAIMER
    result["dataset_version"] = dataset_version(records, f.as_of)
    if body.save:
        run = save_run(session, analysis_type="stats", notice_id=None, inputs=body.model_dump(mode="json"), records=records,
                       as_of=f.as_of, result=result, assumptions=[DISCLAIMER],
                       confidence="insufficient_data" if not result["strata"] else "observational")
        session.commit()
        result["analysis_run_id"] = run.id
    return result


class DistributionIn(BaseModel):
    filters: FiltersIn = Field(default_factory=FiltersIn)
    bin_width: float = Field(0.25, gt=0, le=10)


@router.post("/sajeong-distribution", summary="사정률 분포(조건별 히스토그램)")
def sajeong_distribution(body: DistributionIn, session: Session = Depends(get_session)) -> dict:
    f = _filters(body.filters)
    records = load_records(session, f)
    stats_result = compute_stats(records, "sajeong_rate", period=f.describe(), trend="month")
    by_label = {}
    from app.engines.stats.descriptive import stratum_of

    groups: dict[tuple, list] = {}
    for r in records:
        if r.sajeong_rate is not None:
            groups.setdefault(stratum_of(r, "sajeong_rate"), []).append(r.sajeong_rate)
    for s in stats_result.strata:
        key = tuple(s["conditions"].items())
        by_label[s["label"]] = histogram(groups.get(key, []), bin_width=body.bin_width)
    out = stats_result.to_dict()
    out["histograms"] = by_label
    out["bin_width"] = body.bin_width
    out["disclaimer"] = "사정률 분포는 과거 관측 결과일 뿐, 미래 예정가격을 확정적으로 예측하는 정보가 아닙니다."
    return out


class SimilarIn(BaseModel):
    notice_id: int | None = None
    target: dict | None = None  # notice_id 가 없을 때 직접 조건 지정
    filters: FiltersIn = Field(default_factory=lambda: FiltersIn(period="3y"))
    limit: int = Field(20, ge=1, le=200)
    weights: dict[str, float] | None = None
    save: bool = False


@router.post("/similar", summary="유사 입찰 검색(선정 기준·점수 근거 포함)")
def similar(body: SimilarIn, session: Session = Depends(get_session)) -> dict:
    f = _filters(body.filters)
    if body.notice_id is not None:
        n = session.get(ProcurementNotice, body.notice_id)
        if n is None:
            raise HTTPException(404, "공고가 없습니다.")
        # 대상 공고의 입찰마감(없으면 공고일) 이전에 개찰된 건만 비교한다.
        as_of = f.as_of or n.bid_deadline or n.opening_date
        target = Target(
            procurement_type=n.procurement_type, issuing_authority_type=n.issuing_authority_type,
            contract_method=n.contract_method, award_method=n.award_method, agency_name=n.agency_name,
            demand_agency_name=n.demand_agency_name, industry_name=n.industry_name, region_name=n.region_name,
            amount=n.base_amount or n.presumed_price, as_of=as_of, exclude_notice_id=n.id,
        )
    elif body.target:
        t = dict(body.target)
        if "amount" in t and t["amount"] is not None:
            t["amount"] = Decimal(str(t["amount"]))
        try:
            target = Target(**t, as_of=f.as_of) if "as_of" not in t else Target(**t)
        except TypeError as e:
            raise HTTPException(400, f"대상 조건 형식 오류: {e}") from e
    else:
        raise HTTPException(400, "notice_id 또는 target 을 지정하세요.")
    if target.as_of is not None and f.as_of is None:
        f.as_of = target.as_of
    records = load_records(session, f)
    result = find_similar(target, records, limit=body.limit, weights=body.weights)
    result["period"] = f.describe()
    result["dataset_version"] = dataset_version(records, target.as_of)
    if body.save:
        run = save_run(session, analysis_type="similar", notice_id=body.notice_id, inputs=body.model_dump(mode="json"),
                       records=records, as_of=target.as_of, result=result, assumptions=[], confidence="observational")
        session.commit()
        result["analysis_run_id"] = run.id
    return result
