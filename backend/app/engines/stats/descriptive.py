"""과거 낙찰 데이터 통계(순수 계산).

원칙
- 평균 하나로 결론 내리지 않도록 건수·중앙값·사분위수·표준편차·최소·최대·누락률·이상치를 함께 낸다.
- 계약방법·낙찰자 결정방식·발주기관 유형·비율 기준·적용 하한율이 다른 데이터는 같은 통계로 합치지 않는다(층 분리).
- 기준일(as_of) 이후에 개찰된 데이터는 쓰지 않는다(미래 정보 누출 방지).
- 표본 수 경고 기준은 데이터 점검용 경험값이며 통계적 유의성 판정이 아니다.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np

SMALL_SAMPLE = 30  # 이 미만이면 '표본 적음' 경고
TINY_SAMPLE = 10  # 이 미만이면 분포 요약을 참고용으로만 표시
IQR_K = 1.5

# 비교 가능성 키: 이 값들이 다르면 같은 통계로 합치지 않는다.
STRATUM_KEYS = ("procurement_type", "issuing_authority_type", "contract_method", "award_method", "rate_basis", "lower_limit_rate")
STRATUM_LABELS = {
    "procurement_type": "입찰 대분류",
    "issuing_authority_type": "발주기관 유형",
    "contract_method": "계약방법",
    "award_method": "낙찰자 결정방식",
    "rate_basis": "비율 기준",
    "lower_limit_rate": "낙찰하한율",
}

# 금액 구간(기초금액 기준). 화면 분류용 구간이며 법정 금액 구간이 아니다.
AMOUNT_BANDS: tuple[tuple[str, int | None, int | None], ...] = (
    ("1억 미만", None, 100_000_000),
    ("1억~3억", 100_000_000, 300_000_000),
    ("3억~10억", 300_000_000, 1_000_000_000),
    ("10억~50억", 1_000_000_000, 5_000_000_000),
    ("50억~100억", 5_000_000_000, 10_000_000_000),
    ("100억 이상", 10_000_000_000, None),
)
BID_COUNT_BANDS: tuple[tuple[str, int | None, int | None], ...] = (
    ("10개사 미만", None, 10),
    ("10~49개사", 10, 50),
    ("50~99개사", 50, 100),
    ("100~299개사", 100, 300),
    ("300개사 이상", 300, None),
)


@dataclass
class Record:
    """분석용 공고+결과 1건."""

    notice_id: int
    opening_date: datetime | None
    announcement_date: date | None
    procurement_type: str | None
    issuing_authority_type: str | None
    contract_method: str | None
    award_method: str | None
    agency_name: str | None
    demand_agency_name: str | None
    industry_name: str | None
    region_name: str | None
    base_amount: Decimal | None
    presumed_price: Decimal | None
    estimated_price: Decimal | None
    sajeong_rate: Decimal | None
    winning_rate: Decimal | None
    rate_basis: str | None
    bid_count: int | None
    lower_limit_rate: Decimal | None
    source_name: str
    title: str = ""

    def get(self, key: str) -> Any:
        return getattr(self, key)


def band_of(value: Decimal | int | None, bands: Sequence[tuple[str, int | None, int | None]]) -> str | None:
    if value is None:
        return None
    for label, lo, hi in bands:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return label
    return None


def dimension_value(r: Record, dim: str) -> str | None:
    if dim == "amount_band":
        return band_of(r.base_amount, AMOUNT_BANDS)
    if dim == "bid_count_band":
        return band_of(r.bid_count, BID_COUNT_BANDS)
    if dim == "month":
        return r.opening_date.strftime("%Y-%m") if r.opening_date else None
    if dim == "quarter":
        return f"{r.opening_date.year}-Q{(r.opening_date.month - 1) // 3 + 1}" if r.opening_date else None
    v = r.get(dim)
    return None if v is None else str(v)


ALLOWED_DIMENSIONS = {
    "agency_name": "발주기관",
    "demand_agency_name": "수요기관",
    "industry_name": "업종(공종)",
    "region_name": "지역",
    "amount_band": "금액 구간",
    "award_method": "낙찰자 결정방식",
    "contract_method": "계약방법",
    "bid_count_band": "참가업체 수 구간",
    "month": "월",
    "quarter": "분기",
    "procurement_type": "입찰 대분류",
    "issuing_authority_type": "발주기관 유형",
}

METRICS = {
    "sajeong_rate": ("사정률(%)", "(예정가격 − 기초금액) ÷ 기초금액 × 100"),
    "winning_rate": ("낙찰률(%)", "낙찰금액 ÷ 기준금액 × 100 (기준금액은 rate_basis)"),
    "bid_count": ("참가업체 수", "개찰 결과의 참가업체 수"),
}


@dataclass
class Summary:
    n: int
    mean: float | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    outliers: int = 0
    outlier_bounds: tuple[float, float] | None = None
    outliers_excluded: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in self.__dict__.items()}
        d["outlier_bounds"] = list(self.outlier_bounds) if self.outlier_bounds else None
        return d


def _r(x: float) -> float:
    return float(round(x, 6))


def summarize(values: Iterable[Decimal | float | int], *, exclude_outliers: bool = False) -> Summary:
    arr = np.array([float(v) for v in values], dtype=float)
    if arr.size == 0:
        return Summary(n=0, warnings=["NO_DATA: 분석할 데이터가 없습니다."])
    q1, q3 = np.percentile(arr, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - IQR_K * iqr, q3 + IQR_K * iqr
    is_out = (arr < lo) | (arr > hi)
    n_out = int(is_out.sum())
    used = arr[~is_out] if exclude_outliers and n_out and (~is_out).sum() > 0 else arr
    warnings: list[str] = []
    if used.size < TINY_SAMPLE:
        warnings.append(f"TINY_SAMPLE: 표본이 {used.size}건으로 매우 적습니다. 분포 요약은 참고용으로만 보세요.")
    elif used.size < SMALL_SAMPLE:
        warnings.append(f"SMALL_SAMPLE: 표본이 {used.size}건으로 적습니다. 일반화에 주의하세요.")
    uq1, uq3 = np.percentile(used, [25, 75])
    return Summary(
        n=int(used.size),
        mean=_r(used.mean()),
        median=_r(float(np.median(used))),
        q1=_r(uq1),
        q3=_r(uq3),
        std=_r(used.std(ddof=1)) if used.size > 1 else None,
        min=_r(used.min()),
        max=_r(used.max()),
        outliers=n_out,
        outlier_bounds=(_r(lo), _r(hi)),
        outliers_excluded=bool(exclude_outliers and n_out),
        warnings=warnings,
    )


def metric_value(r: Record, metric: str) -> Decimal | int | None:
    if metric == "sajeong_rate":
        return r.sajeong_rate
    if metric == "winning_rate":
        return r.winning_rate if r.rate_basis else None  # 기준 없는 낙찰률은 쓰지 않음
    if metric == "bid_count":
        return r.bid_count
    raise ValueError(f"알 수 없는 지표: {metric}")


def stratum_of(r: Record, metric: str) -> tuple:
    keys = STRATUM_KEYS if metric == "winning_rate" else tuple(k for k in STRATUM_KEYS if k != "rate_basis")
    return tuple((k, None if r.get(k) is None else str(r.get(k))) for k in keys)


def stratum_label(key: tuple) -> str:
    parts = [f"{STRATUM_LABELS[k]}={v if v is not None else '미상'}" for k, v in key]
    return ", ".join(parts)


@dataclass
class StatsResult:
    metric: str
    n_records: int
    missing_count: int
    strata: list[dict]
    pooled: dict | None
    warnings: list[str]
    sources: dict[str, int]
    period: dict

    @property
    def missing_rate(self) -> float | None:
        return None if self.n_records == 0 else _r(self.missing_count / self.n_records)

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "metric_label": METRICS[self.metric][0],
            "metric_definition": METRICS[self.metric][1],
            "n_records": self.n_records,
            "missing_count": self.missing_count,
            "missing_rate": self.missing_rate,
            "strata": self.strata,
            "pooled": self.pooled,
            "warnings": self.warnings,
            "sources": self.sources,
            "period": self.period,
        }


def filter_as_of(records: Iterable[Record], as_of: datetime | None) -> list[Record]:
    """기준 시각 이전에 개찰된 기록만 남긴다(개찰일 미상 기록은 제외)."""
    out = []
    for r in records:
        if r.opening_date is None:
            continue
        if as_of is not None and r.opening_date >= as_of:
            continue
        out.append(r)
    return out


def compute_stats(
    records: Sequence[Record],
    metric: str,
    *,
    group_by: Sequence[str] = (),
    exclude_outliers: bool = False,
    period: dict | None = None,
    trend: str | None = "month",
) -> StatsResult:
    if metric not in METRICS:
        raise ValueError(f"알 수 없는 지표: {metric}")
    for d in group_by:
        if d not in ALLOWED_DIMENSIONS:
            raise ValueError(f"알 수 없는 분류 기준: {d}")
    present = [r for r in records if metric_value(r, metric) is not None]
    warnings: list[str] = []
    if metric == "winning_rate":
        no_basis = sum(1 for r in records if r.winning_rate is not None and not r.rate_basis)
        if no_basis:
            warnings.append(f"RATE_BASIS_MISSING: 기준 금액이 기록되지 않은 낙찰률 {no_basis}건은 제외했습니다.")
    strata_map: dict[tuple, list[Record]] = defaultdict(list)
    for r in present:
        strata_map[stratum_of(r, metric)].append(r)
    if len(strata_map) > 1:
        warnings.append(
            f"MIXED_CONDITIONS: 조건이 다른 데이터 {len(strata_map)}개 묶음이 있어 합치지 않고 따로 계산했습니다."
        )
    strata = []
    for key, rows in sorted(strata_map.items(), key=lambda kv: -len(kv[1])):
        vals = [metric_value(r, metric) for r in rows]
        entry: dict[str, Any] = {
            "conditions": dict(key),
            "label": stratum_label(key),
            "summary": summarize(vals, exclude_outliers=exclude_outliers).to_dict(),  # type: ignore[arg-type]
        }
        if any(v is None for _, v in key):
            entry["summary"]["warnings"].append("CONDITION_UNKNOWN: 일부 조건이 미상인 데이터 묶음입니다.")
        if group_by:
            groups: dict[tuple, list] = defaultdict(list)
            for r in rows:
                groups[tuple(dimension_value(r, d) for d in group_by)].append(metric_value(r, metric))
            entry["groups"] = [
                {"key": dict(zip(group_by, k, strict=True)), "summary": summarize(v, exclude_outliers=exclude_outliers).to_dict()}
                for k, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))
            ]
        if trend:
            tg: dict[str, list] = defaultdict(list)
            for r in rows:
                if (p := dimension_value(r, trend)) is not None:
                    tg[p].append(metric_value(r, metric))
            entry["trend"] = [
                {"period": p, "n": len(v), "median": _r(float(np.median([float(x) for x in v]))),
                 "mean": _r(float(np.mean([float(x) for x in v])))}
                for p, v in sorted(tg.items())
            ]
        strata.append(entry)
    pooled = strata[0]["summary"] if len(strata) == 1 else None
    if not present:
        warnings.append("NO_DATA: 조건에 맞는 데이터가 없습니다. 추천이나 결론을 낼 수 없습니다.")
    sources: dict[str, int] = defaultdict(int)
    for r in present:
        sources[r.source_name] += 1
    return StatsResult(metric, len(records), len(records) - len(present), strata, pooled, warnings, dict(sources), period or {})


def histogram(values: Sequence[Decimal | float], *, bin_width: float, lo: float | None = None, hi: float | None = None) -> list[dict]:
    """고정 폭 히스토그램. 구간은 [시작, 끝)."""
    if bin_width <= 0:
        raise ValueError("bin_width 는 0보다 커야 합니다.")
    arr = np.array([float(v) for v in values], dtype=float)
    if arr.size == 0:
        return []
    start = math.floor((arr.min() if lo is None else lo) / bin_width) * bin_width
    end = (math.floor((arr.max() if hi is None else hi) / bin_width) + 1) * bin_width
    edges = np.arange(start, end + bin_width / 2, bin_width)
    counts, edges = np.histogram(arr, bins=edges)
    return [{"from": _r(edges[i]), "to": _r(edges[i + 1]), "count": int(c)} for i, c in enumerate(counts)]
