"""복수예비가격 조회·분석.

- 공고별: 예비가격과 기초금액 대비 비율, 추첨 여부, 추첨된 값의 평균과 확정 예정가격 비교
- 여러 공고: 예비가격 비율 분포와 번호별 추첨 횟수. 조건(대분류·기관 유형·계약방법·결정방식·하한율·예비가격 범위)이 다르면 나눠 낸다.
예비가격은 공개된 경우(나라장터 개찰결과 복수예비가격 상세)만 있으며, 업로드 자료에는 없다.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.analysis import FiltersIn, _filters
from app.db.models import BidResult, ProcurementNotice, ReservePrice
from app.db.session import get_session
from app.engines.stats import histogram, summarize
from app.engines.stats.descriptive import stratum_label, stratum_of
from app.services.analysis import dataset_version, load_records

router = APIRouter(tags=["복수예비가격"])
Q6 = Decimal("0.000001")


def _rate(amount: Decimal, base: Decimal | None) -> Decimal | None:
    return None if not base else ((amount / base - 1) * 100).quantize(Q6)


@router.get("/api/notices/{notice_id}/reserve-prices", summary="공고의 복수예비가격과 추첨 결과")
def notice_reserve_prices(notice_id: int, session: Session = Depends(get_session)) -> dict:
    n = session.get(ProcurementNotice, notice_id)
    if n is None:
        raise HTTPException(404, "공고가 없습니다.")
    out = []
    for res in session.scalars(select(BidResult).where(BidResult.notice_id == n.id).order_by(BidResult.rebid_number, BidResult.id)):
        prices = list(session.scalars(select(ReservePrice).where(ReservePrice.result_id == res.id).order_by(ReservePrice.seq)))
        base = res.actual_base_price or n.base_amount
        drawn = [p.amount for p in prices if p.drawn]
        mean = (sum(drawn, Decimal(0)) / len(drawn)) if drawn else None
        check = None
        if mean is not None and res.actual_estimated_price is not None:
            diff = res.actual_estimated_price - mean
            check = {"drawn_mean": str(mean), "actual_estimated_price": str(res.actual_estimated_price), "difference": str(diff),
                     "consistent": abs(diff) < 1,
                     "meaning": "추첨된 예비가격의 평균과 공개된 예정가격의 차이(1원 이상이면 단수처리·자료를 확인하세요)"}
        out.append({
            "result_id": res.id, "source_name": res.source_name, "rebid_number": res.rebid_number,
            "base_amount": str(base) if base is not None else None,
            "prices": [{"seq": p.seq, "amount": str(p.amount), "rate_vs_base": str(r) if (r := _rate(p.amount, base)) is not None else None,
                        "drawn": p.drawn, "draw_count": p.draw_count} for p in prices],
            "drawn_count": len(drawn), "estimated_check": check,
        })
    return {"notice_id": n.id, "reserve_range": {"begin_rate": str(n.reserve_range_begin_rate) if n.reserve_range_begin_rate is not None else None,
                                                  "end_rate": str(n.reserve_range_end_rate) if n.reserve_range_end_rate is not None else None},
            "results": out, "available": any(r["prices"] for r in out),
            "note": None if any(r["prices"] for r in out) else "이 공고의 복수예비가격 자료가 없습니다(공개·수집된 경우에만 표시)."}


class ReserveStatsIn(BaseModel):
    filters: FiltersIn = Field(default_factory=FiltersIn)
    bin_width: float = Field(0.25, gt=0, le=5)


@router.post("/api/analysis/reserve-prices", summary="복수예비가격 비율 분포·번호별 추첨 횟수(조건별)")
def reserve_stats(body: ReserveStatsIn, session: Session = Depends(get_session)) -> dict:
    f = _filters(body.filters)
    records = load_records(session, f)
    by_id = {r.notice_id: r for r in records}
    if not by_id:
        rows = []
    else:
        rows = session.execute(
            select(ReservePrice, BidResult, ProcurementNotice)
            .join(BidResult, BidResult.id == ReservePrice.result_id)
            .join(ProcurementNotice, ProcurementNotice.id == BidResult.notice_id)
            .where(BidResult.notice_id.in_(list(by_id)))
        ).all()
    groups: dict[tuple, dict] = defaultdict(lambda: {"all": [], "drawn": [], "seq_draws": defaultdict(int), "notices": set()})
    for rp, res, n in rows:
        base = res.actual_base_price or n.base_amount
        rate = _rate(rp.amount, base)
        if rate is None:
            continue
        key = stratum_of(by_id[n.id], "sajeong_rate") + (("reserve_range", f"{n.reserve_range_begin_rate}~{n.reserve_range_end_rate}"),)
        g = groups[key]
        g["all"].append(rate)
        g["notices"].add(n.id)
        if rp.drawn:
            g["drawn"].append(rate)
            g["seq_draws"][rp.seq] += 1
    strata = []
    for key, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["notices"])):
        base_key = key[:-1]
        strata.append({
            "label": stratum_label(base_key) + f", 예비가격 범위={key[-1][1]}",
            "conditions": dict(key),
            "notice_count": len(g["notices"]),
            "all_prices": summarize(g["all"]).to_dict(),
            "drawn_prices": summarize(g["drawn"]).to_dict(),
            "histogram_all": histogram(g["all"], bin_width=body.bin_width),
            "histogram_drawn": histogram(g["drawn"], bin_width=body.bin_width) if g["drawn"] else [],
            "draws_by_seq": [{"seq": s, "count": c} for s, c in sorted(g["seq_draws"].items())],
        })
    warnings = []
    if not strata:
        warnings.append("NO_DATA: 조건에 맞는 복수예비가격 자료가 없습니다. 예비가격은 공식 API 수집 자료에만 있습니다.")
    if len(strata) > 1:
        warnings.append("MIXED_CONDITIONS: 조건이 다른 자료를 나눠 표시했습니다. 합쳐서 해석하지 마세요.")
    return {
        "period": f.describe(), "strata": strata, "warnings": warnings, "bin_width": body.bin_width,
        "dataset_version": dataset_version(records, f.as_of),
        "definition": "예비가격 비율(%) = (예비가격 ÷ 기초금액 − 1) × 100",
        "disclaimer": "과거 추첨 결과의 요약입니다. 번호별 추첨 횟수는 다음 추첨을 예측하지 않습니다(추첨은 무작위).",
    }
