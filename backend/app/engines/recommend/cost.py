"""원가·수익성 계산.

- 원가 항목이 하나라도 비어 있으면(None) 총원가를 확정하지 않고 이익도 계산하지 않는다.
  해당 없는 항목은 0 으로 직접 입력해야 한다(빈칸을 0 으로 보지 않음).
- 원가와 투찰금액의 부가가치세 포함 여부가 확인되지 않으면 이익을 계산하지 않는다(중복·누락 방지).
- 이익률(%) = 이익 ÷ 투찰 공급가액 × 100 (매출 대비). 이익은 원 미만 버림(이익을 크게 보이지 않게).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from ..calc import split_vat, to_decimal
from ..calc.errors import CalcInputError

COST_ITEMS = {
    "material_cost": "재료비",
    "labor_cost": "노무비",
    "equipment_cost": "장비비",
    "subcontract_cost": "외주비",
    "transport_cost": "운반비",
    "site_overhead": "현장관리비",
    "general_overhead": "일반관리비",
    "statutory_costs": "보험료·법정비용",
    "other_costs": "기타비용",
}
VAT_TREATMENTS = {"excluded": "부가세 별도", "included": "부가세 포함"}
Q6 = Decimal("0.000001")


@dataclass
class CostSheet:
    items: dict[str, Decimal | None] = field(default_factory=dict)
    vat_treatment: str | None = None  # excluded / included
    target_profit: Decimal | None = None  # 목표 이익(원, 공급가액 기준)
    target_profit_rate: Decimal | None = None  # 목표 이익률(%, 공급가액 대비)

    def __post_init__(self) -> None:
        unknown = set(self.items) - set(COST_ITEMS)
        if unknown:
            raise CalcInputError("items", f"알 수 없는 원가 항목: {sorted(unknown)}")
        clean: dict[str, Decimal | None] = {}
        for k in COST_ITEMS:
            v = self.items.get(k)
            if v is not None:
                v = to_decimal(v, k)
                if v < 0:
                    raise CalcInputError(k, "원가는 음수일 수 없습니다.")
            clean[k] = v
        self.items = clean
        if self.vat_treatment is not None and self.vat_treatment not in VAT_TREATMENTS:
            raise CalcInputError("vat_treatment", f"부가세 처리는 {list(VAT_TREATMENTS)} 중 하나여야 합니다.")
        if self.target_profit_rate is not None:
            r = to_decimal(self.target_profit_rate, "target_profit_rate")
            if not (Decimal(0) <= r < Decimal(100)):
                raise CalcInputError("target_profit_rate", "목표 이익률은 0% 이상 100% 미만이어야 합니다.")
            self.target_profit_rate = r
        if self.target_profit is not None:
            self.target_profit = to_decimal(self.target_profit, "target_profit")

    @property
    def missing(self) -> list[str]:
        return [k for k, v in self.items.items() if v is None]

    @property
    def known_total(self) -> Decimal:
        return sum((v for v in self.items.values() if v is not None), Decimal(0))

    def supply_total(self) -> Decimal | None:
        """공급가액 기준 총원가. 미입력 항목이 있거나 부가세 처리가 미확인이면 None."""
        if self.missing or self.vat_treatment is None:
            return None
        total = self.known_total
        if self.vat_treatment == "included":
            return split_vat(total, vat_included=True).supply_amount
        return total


def cost_summary(sheet: CostSheet) -> dict[str, Any]:
    warnings: list[str] = []
    if sheet.missing:
        warnings.append("COST_INCOMPLETE: 입력하지 않은 원가 항목이 있어 총원가를 확정하지 않았습니다: "
                        + ", ".join(COST_ITEMS[k] for k in sheet.missing))
    if sheet.vat_treatment is None:
        warnings.append("COST_VAT_UNKNOWN: 원가의 부가세 포함 여부가 지정되지 않았습니다.")
    supply = sheet.supply_total()
    return {
        "items": {k: {"label": COST_ITEMS[k], "value": str(v) if v is not None else None} for k, v in sheet.items.items()},
        "known_total": str(sheet.known_total),
        "missing_items": sheet.missing,
        "complete": not sheet.missing,
        "vat_treatment": sheet.vat_treatment,
        "supply_total": str(supply) if supply is not None else None,
        "warnings": warnings,
    }


def _bid_supply(bid_amount: Decimal, bid_vat_included: bool) -> Decimal:
    return split_vat(bid_amount, vat_included=bid_vat_included).supply_amount


def evaluate_profit(bid_amount: object, sheet: CostSheet, *, bid_vat_included: bool | None) -> dict[str, Any]:
    bid = to_decimal(bid_amount, "bid_amount")
    cost = sheet.supply_total()
    if cost is None:
        return {"status": "cost_incomplete", "profit": None, "margin_pct": None, "flags": [],
                "warnings": cost_summary(sheet)["warnings"]}
    if bid_vat_included is None:
        return {"status": "vat_unknown", "profit": None, "margin_pct": None, "flags": [],
                "warnings": ["BID_VAT_UNKNOWN: 투찰금액의 부가세 포함 여부가 확인되지 않아 이익을 계산하지 않았습니다."]}
    supply = _bid_supply(bid, bid_vat_included)
    profit = (supply - cost).quantize(Decimal(1), rounding=ROUND_FLOOR)
    margin = (profit / supply * 100).quantize(Q6) if supply > 0 else None
    flags: list[str] = []
    if profit < 0:
        flags.append(f"BELOW_COST: 원가보다 {-profit}원 낮습니다.")
    if sheet.target_profit is not None and profit < sheet.target_profit:
        flags.append(f"BELOW_TARGET_PROFIT: 목표 이익 {sheet.target_profit}원에 못 미칩니다.")
    if sheet.target_profit_rate is not None and margin is not None and margin < sheet.target_profit_rate:
        flags.append(f"BELOW_TARGET_MARGIN: 목표 이익률 {sheet.target_profit_rate}%에 못 미칩니다.")
    return {
        "status": "computed", "bid_amount": str(bid), "bid_supply_amount": str(supply), "cost_supply_total": str(cost),
        "profit": str(profit), "margin_pct": str(margin) if margin is not None else None,
        "formula": "이익 = 투찰 공급가액 − 총원가(공급가액), 이익률 = 이익 ÷ 투찰 공급가액 × 100",
        "flags": flags, "warnings": [],
    }


def _bid_for_supply(supply: Decimal, bid_vat_included: bool) -> Decimal:
    gross = supply * Decimal("1.1") if bid_vat_included else supply
    return gross.quantize(Decimal(1), rounding=ROUND_CEILING)


def break_even(sheet: CostSheet, *, bid_vat_included: bool | None) -> dict[str, Any]:
    """손익분기 투찰금액과 목표 이익을 위한 최소 투찰금액(원 미만 올림). 부가세율 10% 가정."""
    cost = sheet.supply_total()
    if cost is None or bid_vat_included is None:
        return {"status": "not_computed", "warnings": cost_summary(sheet)["warnings"]
                + ([] if bid_vat_included is not None else ["BID_VAT_UNKNOWN: 투찰금액의 부가세 포함 여부가 확인되지 않았습니다."])}
    out: dict[str, Any] = {"status": "computed", "cost_supply_total": str(cost), "vat_rate_pct": "10",
                           "break_even_bid": str(_bid_for_supply(cost, bid_vat_included))}
    if sheet.target_profit is not None:
        out["min_bid_for_target_profit"] = str(_bid_for_supply(cost + sheet.target_profit, bid_vat_included))
    if sheet.target_profit_rate is not None:
        out["min_bid_for_target_margin"] = str(_bid_for_supply(cost / (1 - sheet.target_profit_rate / 100), bid_vat_included))
    out["formula"] = "공급가액 = 총원가(+목표 이익) 또는 총원가 ÷ (1 − 목표 이익률), 투찰금액 = 공급가액 × 1.1(부가세 포함 시), 원 미만 올림"
    return out
