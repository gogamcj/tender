from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.engines.stats import Record, Target, compute_stats, filter_as_of, find_similar, histogram, summarize

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def rec(i, sajeong="0", days=0, **kw) -> Record:
    base = dict(
        notice_id=i, opening_date=T0 + timedelta(days=days), announcement_date=None, procurement_type="construction",
        issuing_authority_type="local", contract_method="제한경쟁", award_method="적격심사", agency_name="가상시",
        demand_agency_name="가상시", industry_name="토목", region_name="가상도", base_amount=Decimal("100000000"),
        presumed_price=None, estimated_price=None, sajeong_rate=Decimal(sajeong) if sajeong is not None else None,
        winning_rate=None, rate_basis=None, bid_count=100, lower_limit_rate=None, source_name="sample", title=f"공고{i}",
    )
    base.update(kw)
    return Record(**base)


def test_summarize_matches_numpy():
    vals = [Decimal(x) for x in ("-1.5", "-0.5", "0", "0.25", "0.5", "1.0", "1.5")]
    s = summarize(vals)
    arr = np.array([float(v) for v in vals])
    assert s.n == 7
    assert s.mean == pytest.approx(arr.mean(), abs=1e-6)
    assert s.median == 0.25
    assert s.q1 == pytest.approx(np.percentile(arr, 25), abs=1e-6)
    assert s.q3 == pytest.approx(np.percentile(arr, 75), abs=1e-6)
    assert s.std == pytest.approx(arr.std(ddof=1), abs=1e-6)
    assert (s.min, s.max) == (-1.5, 1.5)
    assert any(w.startswith("TINY_SAMPLE") for w in s.warnings)


def test_summarize_empty_and_single():
    assert summarize([]).n == 0
    one = summarize([Decimal("1")])
    assert one.n == 1 and one.std is None


def test_outliers_counted_and_optionally_excluded():
    vals = [Decimal("0")] * 20 + [Decimal("0.1")] * 20 + [Decimal("15")]
    keep = summarize(vals)
    assert keep.outliers == 1 and keep.max == 15 and not keep.outliers_excluded
    drop = summarize(vals, exclude_outliers=True)
    assert drop.n == 40 and drop.max == 0.1 and drop.outliers_excluded
    assert drop.warnings == []  # 40건: 표본 경고 기준(30건) 이상


def test_no_mixing_of_different_conditions():
    rows = [rec(i, "-0.5") for i in range(10)] + [rec(100 + i, "1.0", award_method="최저가") for i in range(5)]
    r = compute_stats(rows, "sajeong_rate")
    assert len(r.strata) == 2
    assert r.pooled is None  # 합친 통계는 내지 않음
    assert any(w.startswith("MIXED_CONDITIONS") for w in r.warnings)
    medians = sorted(s["summary"]["median"] for s in r.strata)
    assert medians == [-0.5, 1.0]


def test_different_lower_limit_rates_are_separate_strata():
    rows = [rec(1, lower_limit_rate=Decimal("87.745")), rec(2, lower_limit_rate=Decimal("89.745"))]
    assert len(compute_stats(rows, "sajeong_rate").strata) == 2


def test_winning_rate_requires_basis_and_splits_by_basis():
    rows = [
        rec(1, winning_rate=Decimal("87.8"), rate_basis="estimated_price"),
        rec(2, winning_rate=Decimal("87.9"), rate_basis="estimated_price"),
        rec(3, winning_rate=Decimal("87.1"), rate_basis="base_amount"),
        rec(4, winning_rate=Decimal("88.0"), rate_basis=None),
    ]
    r = compute_stats(rows, "winning_rate")
    assert len(r.strata) == 2
    assert any(w.startswith("RATE_BASIS_MISSING") for w in r.warnings)
    assert r.missing_count == 1


def test_missing_rate_and_sources():
    rows = [rec(1, "0.1"), rec(2, None), rec(3, "0.2", source_name="upload")]
    r = compute_stats(rows, "sajeong_rate")
    assert r.missing_rate == pytest.approx(1 / 3, abs=1e-6)
    assert r.sources == {"sample": 1, "upload": 1}


def test_no_data_warning():
    r = compute_stats([], "sajeong_rate")
    assert r.strata == [] and any(w.startswith("NO_DATA") for w in r.warnings)


def test_group_by_and_trend():
    rows = [rec(i, str(i % 3), days=i * 20, agency_name="A" if i % 2 else "B") for i in range(12)]
    r = compute_stats(rows, "sajeong_rate", group_by=["agency_name"], trend="month")
    s = r.strata[0]
    assert {g["key"]["agency_name"] for g in s["groups"]} == {"A", "B"}
    assert sum(g["summary"]["n"] for g in s["groups"]) == 12
    assert s["trend"][0]["period"] == "2024-01"
    assert sum(t["n"] for t in s["trend"]) == 12


def test_amount_band_dimension():
    rows = [rec(1, base_amount=Decimal("50000000")), rec(2, base_amount=Decimal("100000000")), rec(3, base_amount=Decimal("2000000000"))]
    r = compute_stats(rows, "sajeong_rate", group_by=["amount_band"], trend=None)
    labels = {g["key"]["amount_band"] for g in r.strata[0]["groups"]}
    assert labels == {"1억 미만", "1억~3억", "10억~50억"}


def test_invalid_metric_and_dimension():
    with pytest.raises(ValueError):
        compute_stats([], "magic")
    with pytest.raises(ValueError):
        compute_stats([], "sajeong_rate", group_by=["drop table"])


def test_histogram():
    h = histogram([Decimal("-0.3"), Decimal("-0.1"), Decimal("0"), Decimal("0.24"), Decimal("0.25")], bin_width=0.25)
    assert sum(b["count"] for b in h) == 5
    assert h[0]["from"] == -0.5
    zero_bin = next(b for b in h if b["from"] == 0.0)
    assert zero_bin["count"] == 2  # 0, 0.24 ([0, 0.25))
    with pytest.raises(ValueError):
        histogram([1], bin_width=0)


def test_as_of_filter_prevents_leakage():
    rows = [rec(1, days=0), rec(2, days=10), rec(3, days=20), rec(4, opening_date=None)]
    kept = filter_as_of(rows, T0 + timedelta(days=10))
    assert [r.notice_id for r in kept] == [1]  # 기준 시각과 같거나 이후, 개찰일 미상 제외


# ------------------------------------------------------------------ 유사 입찰


def target(**kw) -> Target:
    base = dict(procurement_type="construction", issuing_authority_type="local", contract_method="제한경쟁",
                award_method="적격심사", agency_name="가상시", industry_name="토목", region_name="가상도",
                amount=Decimal("100000000"), as_of=T0 + timedelta(days=100))
    base.update(kw)
    return Target(**base)


def test_similar_hard_filter_and_ranking():
    rows = [
        rec(1, days=90),  # 같은 기관·업종·지역·금액, 최근
        rec(2, days=10, agency_name="다른시"),
        rec(3, days=50, award_method="최저가"),  # 결정방식 다름 → 제외
        rec(4, days=95, base_amount=Decimal("400000000")),  # 금액 4배
        rec(5, days=150),  # 기준 이후 → 제외
    ]
    out = find_similar(target(), rows)
    ids = [m["notice_id"] for m in out["matches"]]
    assert 3 not in ids and 5 not in ids
    assert ids[0] == 1
    assert out["excluded"]["hard_mismatch"] == 1
    assert out["excluded"]["after_as_of_or_no_opening_date"] == 1
    top = out["matches"][0]
    assert top["components"]["agency"] == 3.0
    assert any("발주기관 같음" in r for r in top["reasons"])
    four = next(m for m in out["matches"] if m["notice_id"] == 4)
    assert four["components"]["amount"] == pytest.approx(2.0 * 0.25, abs=1e-3)  # 4배 → 0.25
    assert "amount_rule" in out["criteria"]


def test_similar_unknown_condition_penalized_not_excluded():
    rows = [rec(1, days=90), rec(2, days=90, contract_method=None)]
    out = find_similar(target(), rows)
    by_id = {m["notice_id"]: m for m in out["matches"]}
    assert by_id[2]["unknown_conditions"] == ["계약방법"]
    assert by_id[1]["score"] > by_id[2]["score"]


def test_similar_excludes_self_and_reports_empty():
    out = find_similar(target(exclude_notice_id=1), [rec(1, days=10)])
    assert out["matches"] == [] and out["excluded"]["self"] == 1
    assert any(w.startswith("NO_SIMILAR") for w in out["warnings"])


def test_similar_custom_weights():
    rows = [rec(1, days=90, agency_name="다른시"), rec(2, days=90, industry_name="건축")]
    out = find_similar(target(), rows, weights={"agency": 0.0, "industry": 0.0})
    assert out["criteria"]["weights"]["agency"] == 0.0
    scores = [m["score"] for m in out["matches"]]
    assert scores[0] == pytest.approx(scores[1])
