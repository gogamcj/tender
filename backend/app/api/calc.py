"""계산 API. 금액·비율은 문자열(또는 정수)로 받는다. float 는 받지 않는다."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.engines import calc
from app.engines.calc import PriceStatus, RateBasis, RateUnit, RoundingMode, RoundingRule

router = APIRouter(prefix="/api/calc", tags=["계산"])

Num = str | int


class RoundingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: RoundingMode
    unit: int = 1
    source: str | None = None

    def to_rule(self) -> RoundingRule:
        return RoundingRule(self.mode, self.unit, self.source)


def _r(r: RoundingIn | None) -> RoundingRule | None:
    return r.to_rule() if r else None


class LowerLimitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_price: Num
    lower_limit_rate: Num
    rate_unit: RateUnit = RateUnit.PERCENT
    reference_basis: RateBasis = RateBasis.ESTIMATED_PRICE
    price_status: PriceStatus
    rounding: RoundingIn | None = None


class SajeongIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_amount: Num
    estimated_price: Num
    price_status: PriceStatus = PriceStatus.ACTUAL


class AssumedPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_amount: Num
    sajeong_rate: Num
    rate_unit: RateUnit = RateUnit.PERCENT
    price_status: PriceStatus = PriceStatus.SCENARIO
    rounding: RoundingIn | None = None


class BidRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bid_amount: Num
    reference_amount: Num
    basis: RateBasis
    price_status: PriceStatus


class BidAmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_amount: Num
    rate: Num
    rate_unit: RateUnit = RateUnit.PERCENT
    basis: RateBasis
    price_status: PriceStatus
    rounding: RoundingIn | None = None


class VatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Num
    vat_included: bool | None
    vat_rate_pct: Num = "10"
    stated_vat_amount: Num | None = None
    rounding: RoundingIn | None = None


@router.post("/lower-limit", summary="낙찰하한금액 = 기준가격 × 낙찰하한율")
def post_lower_limit(body: LowerLimitIn) -> dict:
    return calc.lower_limit_amount(
        body.reference_price,
        body.lower_limit_rate,
        rate_unit=body.rate_unit,
        reference_basis=body.reference_basis,
        price_status=body.price_status,
        rounding=_r(body.rounding),
    ).to_dict()


@router.post("/sajeong-rate", summary="사정률(%) = (예정가격 − 기초금액) ÷ 기초금액 × 100")
def post_sajeong(body: SajeongIn) -> dict:
    return calc.sajeong_rate(body.base_amount, body.estimated_price, price_status=body.price_status).to_dict()


@router.post("/assumed-estimated-price", summary="가정 예정가격 = 기초금액 × (1 + 사정률 ÷ 100)")
def post_assumed_price(body: AssumedPriceIn) -> dict:
    return calc.estimated_price_from_sajeong(
        body.base_amount, body.sajeong_rate, rate_unit=body.rate_unit, price_status=body.price_status, rounding=_r(body.rounding)
    ).to_dict()


@router.post("/bid-rate", summary="투찰률(%) = 투찰금액 ÷ 기준금액 × 100")
def post_bid_rate(body: BidRateIn) -> dict:
    return calc.bid_rate(body.bid_amount, body.reference_amount, basis=body.basis, price_status=body.price_status).to_dict()


@router.post("/bid-amount", summary="후보 투찰금액 = 기준금액 × 투찰률 ÷ 100")
def post_bid_amount(body: BidAmountIn) -> dict:
    return calc.bid_amount_from_rate(
        body.reference_amount,
        body.rate,
        rate_unit=body.rate_unit,
        basis=body.basis,
        price_status=body.price_status,
        rounding=_r(body.rounding),
    ).to_dict()


@router.post("/vat", summary="공급가액·부가가치세 분리")
def post_vat(body: VatIn) -> dict:
    return calc.split_vat(
        body.amount,
        vat_included=body.vat_included,
        vat_rate_pct=body.vat_rate_pct,
        stated_vat_amount=body.stated_vat_amount,
        rounding=_r(body.rounding),
    ).to_dict()
