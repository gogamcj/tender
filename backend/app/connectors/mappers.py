"""API 응답 항목 → 정규화 값.

값을 해석할 수 없으면 None 으로 두고 경고를 남긴다. 다른 필드로 추정해 채우지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.engines.calc import RateUnit
from app.importers.parsing import ParseError, parse_date, parse_datetime, parse_int, parse_money, parse_rate

from .specs import AWARD_FIELD_MAP, AWARD_RATE_BASIS, AWARD_RATE_FIELD, BASIS_FIELD_MAP, NOTICE_FIELD_MAP, OPENING_STATUS_MAP

MONEY = {"presumed_price", "vat_amount", "base_amount", "winning_bid_amount"}
RATE = {"lower_limit_rate", "reserve_range_begin_rate", "reserve_range_end_rate"}
DATE = {"announcement_date"}
DATETIME = {"bid_deadline", "opening_date", "opening_datetime"}
INT = {"bid_count"}


@dataclass
class Mapped:
    values: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # 응답에 필드 자체가 없음


def _raw(item: dict, name: str) -> str | None:
    v = item.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _convert(key: str, raw: str) -> Any:
    if key in MONEY:
        return parse_money(raw)
    if key in RATE:
        return parse_rate(raw, RateUnit.PERCENT)[0]
    if key in DATE:
        return parse_date(raw)
    if key in DATETIME:
        return parse_datetime(raw)
    if key in INT:
        return parse_int(raw)
    return raw


def _apply(item: dict, fmap: dict[str, tuple[str, str]], out: Mapped) -> None:
    for key, (src, _evidence) in fmap.items():
        if src not in item:
            out.missing.append(src)
            out.values[key] = None
            continue
        raw = _raw(item, src)
        if raw is None:
            out.values[key] = None
            continue
        try:
            out.values[key] = _convert(key, raw)
        except ParseError as e:
            out.values[key] = None
            out.warnings.append(f"{src}: {e}")


def notice_key(item: dict) -> tuple[str | None, str]:
    return _raw(item, "bidNtceNo"), _raw(item, "bidNtceOrd") or "000"


def rebid_number(item: dict) -> int:
    raw = _raw(item, "rbidNo")
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def map_notice(item: dict, procurement_type: str | None) -> Mapped:
    out = Mapped()
    _apply(item, NOTICE_FIELD_MAP, out)
    out.values["notice_revision"] = out.values.get("notice_revision") or "000"
    if procurement_type:
        out.values["procurement_type"] = procurement_type
    return out


def map_basis(item: dict) -> Mapped:
    out = Mapped()
    _apply(item, BASIS_FIELD_MAP, out)
    return out


def map_award(item: dict) -> Mapped:
    out = Mapped()
    _apply(item, AWARD_FIELD_MAP, out)
    out.values["opening_status"] = "awarded" if out.values.get("winning_vendor_name") or out.values.get("winning_bid_amount") else None
    rate_raw = _raw(item, AWARD_RATE_FIELD)
    if rate_raw is not None:
        out.values["external_metrics"] = {AWARD_RATE_FIELD: rate_raw}
        if AWARD_RATE_BASIS is not None:
            try:
                out.values["winning_rate"] = parse_rate(rate_raw, RateUnit.PERCENT)[0]
                out.values["winning_rate_basis"] = AWARD_RATE_BASIS
            except ParseError as e:
                out.warnings.append(f"{AWARD_RATE_FIELD}: {e}")
    out.values["rebid_number"] = rebid_number(item)
    return out


def map_opening(item: dict) -> Mapped:
    out = Mapped()
    status_raw = _raw(item, "progrsDivCdNm")
    if status_raw is None:
        out.values["opening_status"] = "unconfirmed"
    elif status_raw in OPENING_STATUS_MAP:
        out.values["opening_status"] = OPENING_STATUS_MAP[status_raw]
    else:
        out.values["opening_status"] = "unconfirmed"
        out.warnings.append(f"알 수 없는 진행구분 '{status_raw}' → 결과 미확인으로 둡니다.")
    for key, src in (("bid_count", "prtcptCnum"), ("opening_datetime", "opengDt")):
        raw = _raw(item, src)
        try:
            out.values[key] = _convert(key, raw) if raw else None
        except ParseError as e:
            out.values[key] = None
            out.warnings.append(f"{src}: {e}")
    out.values["rebid_number"] = rebid_number(item)
    return out


@dataclass
class PreparGroup:
    estimated_price: Decimal | None
    base_amount: Decimal | None
    total_count: int | None
    reserves: list[dict[str, Any]]
    warnings: list[str]


def map_prepar(items: list[dict]) -> PreparGroup:
    """한 공고(같은 재입찰 번호)의 예비가격 상세 행들을 묶는다. 예정가격·기초금액이 행마다 다르면 경고."""
    warnings: list[str] = []
    reserves: list[dict[str, Any]] = []
    plnprcs, bssamts, totals = set(), set(), set()
    for it in items:
        for name, bucket in (("plnprc", plnprcs), ("bssamt", bssamts)):
            raw = _raw(it, name)
            if raw:
                try:
                    bucket.add(parse_money(raw))
                except ParseError as e:
                    warnings.append(f"{name}: {e}")
        if raw := _raw(it, "totRsrvtnPrceNum"):
            try:
                totals.add(parse_int(raw))
            except ParseError as e:
                warnings.append(f"totRsrvtnPrceNum: {e}")
        seq_raw, amt_raw = _raw(it, "compnoRsrvtnPrceSno"), _raw(it, "bsisPlnprc")
        if seq_raw and amt_raw:
            try:
                drawn_raw = _raw(it, "drwtYn")
                reserves.append(
                    {"seq": parse_int(seq_raw), "amount": parse_money(amt_raw),
                     "drawn": None if drawn_raw is None else drawn_raw.upper() == "Y"}
                )
            except ParseError as e:
                warnings.append(f"예비가격 행: {e}")
    for label, bucket in (("예정가격", plnprcs), ("기초금액", bssamts), ("예비가격 총수", totals)):
        if len(bucket) > 1:
            warnings.append(f"{label} 값이 행마다 다릅니다: {sorted(bucket)} → 저장하지 않습니다.")
    return PreparGroup(
        estimated_price=next(iter(plnprcs)) if len(plnprcs) == 1 else None,
        base_amount=next(iter(bssamts)) if len(bssamts) == 1 else None,
        total_count=next(iter(totals)) if len(totals) == 1 else None,
        reserves=sorted(reserves, key=lambda r: r["seq"]),
        warnings=warnings,
    )


def map_bidder(item: dict) -> Mapped:
    out = Mapped()
    out.values["vendor_name"] = _raw(item, "prcbdrNm")
    out.values["vendor_identifier"] = _raw(item, "prcbdrBizno")
    for key, src, conv in (("ranking", "opengRank", parse_int), ("bid_amount", "bidprcAmt", parse_money)):
        raw = _raw(item, src)
        try:
            out.values[key] = conv(raw) if raw else None
        except ParseError as e:
            out.values[key] = None
            out.warnings.append(f"{src}: {e}")
    out.values["qualification_status"] = _raw(item, "rmrk")
    out.values["rebid_number"] = rebid_number(item)
    # 투찰률(bidprcrt)의 기준 금액이 확인되지 않아 bid_rate 는 비워 둔다(원문은 raw 레코드에 보존).
    return out
