"""유사 입찰 검색.

- 필수 조건(입찰 대분류·발주기관 유형·계약방법·낙찰자 결정방식)이 다르면 후보에서 뺀다. 조건이 미상이면 빼지 않고 감점·표시한다.
- 나머지 조건(기관·업종·지역·금액·시점)은 점수로 합산하고, 항목별 점수와 이유를 함께 돌려준다.
- 기준 시각 이후 개찰 건은 후보에서 뺀다(미래 정보 누출 방지).
- 가중치는 사용자가 바꿀 수 있는 설명용 기본값이며, 통계적으로 최적화된 값이 아니다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .descriptive import Record, filter_as_of

HARD_KEYS = (("procurement_type", "입찰 대분류"), ("issuing_authority_type", "발주기관 유형"),
             ("contract_method", "계약방법"), ("award_method", "낙찰자 결정방식"))

DEFAULT_WEIGHTS = {
    "agency": 3.0,  # 같은 발주(공고)기관
    "demand_agency": 1.0,  # 같은 수요기관
    "industry": 2.0,  # 같은 업종
    "region": 1.0,  # 같은 지역
    "amount": 2.0,  # 기초금액(없으면 추정가격) 근접도
    "recency": 1.0,  # 최근일수록
}
RECENCY_HALF_LIFE_DAYS = 365


@dataclass
class Target:
    procurement_type: str | None
    issuing_authority_type: str | None
    contract_method: str | None
    award_method: str | None
    agency_name: str | None = None
    demand_agency_name: str | None = None
    industry_name: str | None = None
    region_name: str | None = None
    amount: Decimal | None = None
    as_of: datetime | None = None
    exclude_notice_id: int | None = None


@dataclass
class Match:
    record: Record
    score: float
    components: dict[str, float]
    reasons: list[str]
    unknown_conditions: list[str] = field(default_factory=list)


def _amount_of(r: Record) -> Decimal | None:
    return r.base_amount or r.presumed_price


def find_similar(target: Target, records: Sequence[Record], *, limit: int = 20, weights: dict[str, float] | None = None) -> dict:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    pool = filter_as_of(records, target.as_of)
    excluded = {"hard_mismatch": 0, "after_as_of_or_no_opening_date": len(records) - len(pool), "self": 0}
    matches: list[Match] = []
    for r in pool:
        if target.exclude_notice_id is not None and r.notice_id == target.exclude_notice_id:
            excluded["self"] += 1
            continue
        unknown: list[str] = []
        mismatch = False
        for key, label in HARD_KEYS:
            tv, rv = getattr(target, key), r.get(key)
            if tv is None or rv is None:
                unknown.append(label)
            elif tv != rv:
                mismatch = True
                break
        if mismatch:
            excluded["hard_mismatch"] += 1
            continue
        comp: dict[str, float] = {}
        reasons: list[str] = []
        for key, wkey, label in (("agency_name", "agency", "발주기관"), ("demand_agency_name", "demand_agency", "수요기관"),
                                 ("industry_name", "industry", "업종"), ("region_name", "region", "지역")):
            tv, rv = getattr(target, key), r.get(key)
            if tv and rv and tv == rv:
                comp[wkey] = w[wkey]
                reasons.append(f"{label} 같음({rv})")
            else:
                comp[wkey] = 0.0
        ta, ra = target.amount, _amount_of(r)
        if ta and ra and ta > 0 and ra > 0:
            ratio = abs(math.log(float(ra) / float(ta)))
            s = math.exp(-ratio)  # 2배 차이(ratio=ln2)일 때 0.5
            comp["amount"] = round(w["amount"] * s, 4)
            reasons.append(f"금액 비율 {float(ra) / float(ta):.2f}배")
        else:
            comp["amount"] = 0.0
            reasons.append("금액 비교 불가")
        if target.as_of and r.opening_date:
            days = max((target.as_of - r.opening_date).days, 0)
            comp["recency"] = round(w["recency"] * 0.5 ** (days / RECENCY_HALF_LIFE_DAYS), 4)
            reasons.append(f"{days}일 전 개찰")
        else:
            comp["recency"] = 0.0
        if unknown:
            reasons.append(f"조건 미상: {', '.join(unknown)}")
        score = round(sum(comp.values()) - 0.5 * len(unknown), 4)
        matches.append(Match(r, score, comp, reasons, unknown))
    matches.sort(key=lambda m: (-m.score, -(m.record.opening_date.timestamp() if m.record.opening_date else 0)))
    top = matches[:limit]
    return {
        "criteria": {
            "hard_conditions": [label for _, label in HARD_KEYS],
            "weights": w,
            "amount_rule": "|ln(후보금액/대상금액)| 이 ln2(2배 차이)일 때 금액 점수 절반",
            "recency_rule": f"{RECENCY_HALF_LIFE_DAYS}일마다 시점 점수 절반",
            "unknown_condition_penalty": 0.5,
            "as_of": target.as_of.isoformat() if target.as_of else None,
        },
        "excluded": excluded,
        "candidates_considered": len(matches),
        "matches": [
            {"notice_id": m.record.notice_id, "title": m.record.title, "score": m.score, "components": m.components,
             "reasons": m.reasons, "unknown_conditions": m.unknown_conditions,
             "opening_date": m.record.opening_date.isoformat() if m.record.opening_date else None,
             "agency_name": m.record.agency_name, "base_amount": str(m.record.base_amount) if m.record.base_amount else None,
             "sajeong_rate": str(m.record.sajeong_rate) if m.record.sajeong_rate is not None else None,
             "winning_rate": str(m.record.winning_rate) if m.record.winning_rate is not None else None,
             "rate_basis": m.record.rate_basis, "bid_count": m.record.bid_count}
            for m in top
        ],
        "warnings": (["NO_SIMILAR: 조건에 맞는 과거 입찰이 없습니다."] if not top else [])
        + ([f"SMALL_SAMPLE: 유사 입찰이 {len(matches)}건뿐입니다."] if 0 < len(matches) < 10 else []),
    }
