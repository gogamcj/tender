"""투찰 시나리오, 원가·수익성, 적격심사 점검표 API.

투찰 시나리오는 분석용 후보 금액이다. 이 시스템은 투찰을 제출하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.enums import ScoreStatus
from app.db.models import AnalysisRun, BidScenario, CompanyCost, ProcurementNotice, QualificationCheck
from app.db.session import get_session
from app.engines.calc import CalcInputError, RateBasis
from app.engines.recommend import (
    COST_ITEMS,
    SCENARIO_PRESETS,
    TEMPLATE_ITEMS,
    CostSheet,
    CustomScenario,
    QualItem,
    ScenarioRequest,
    break_even,
    build_scenarios,
    cost_summary,
    evaluate_items,
    evaluate_profit,
)
from app.services.analysis import dataset_version
from app.services.recommend import LowerLimitOverride, cost_sheet_from_row, history_for, resolve_lower_limit

router = APIRouter(tags=["투찰 시나리오·원가·적격심사"])

HISTORY_FILTER_KEYS = {"agency_name", "demand_agency_name", "industry_name", "region_name", "amount_min", "amount_max"}


class CostIn(BaseModel):
    notice_id: int | None = None
    material_cost: Decimal | None = None
    labor_cost: Decimal | None = None
    equipment_cost: Decimal | None = None
    subcontract_cost: Decimal | None = None
    transport_cost: Decimal | None = None
    site_overhead: Decimal | None = None
    general_overhead: Decimal | None = None
    statutory_costs: Decimal | None = None
    other_costs: Decimal | None = None
    vat_treatment: str | None = None
    target_profit: Decimal | None = None
    target_profit_rate: Decimal | None = None
    notes: str | None = None

    def sheet(self) -> CostSheet:
        for k in (*COST_ITEMS, "target_profit"):
            v = getattr(self, k)
            if v is not None and v != v.to_integral_value():
                raise CalcInputError(k, "원가는 원 단위 정수로 입력하세요.")
        return CostSheet(items={k: getattr(self, k) for k in COST_ITEMS}, vat_treatment=self.vat_treatment,
                         target_profit=self.target_profit, target_profit_rate=self.target_profit_rate)


class CustomIn(BaseModel):
    name: str = Field("custom", max_length=60)
    sajeong_rate_pct: Decimal | None = None
    percentile: Decimal | None = None
    bid_amount: Decimal | None = None


class RecommendIn(BaseModel):
    notice_id: int
    period: str | None = "3y"
    history_filters: dict[str, Any] = Field(default_factory=dict)
    lower_limit_rate_pct: Decimal | None = None
    a_value: Decimal | None = None
    presets: dict[str, Decimal] | None = None
    custom: list[CustomIn] = Field(default_factory=list)
    cost_id: int | None = None
    cost: CostIn | None = None
    bid_vat_included: bool | None = None
    save: bool = False


def run_recommend(body: RecommendIn, session: Session) -> tuple[dict, list]:
    n = session.get(ProcurementNotice, body.notice_id)
    if n is None:
        raise HTTPException(404, "공고가 없습니다.")
    if n.base_amount is None:
        raise CalcInputError("base_amount", "기초금액이 확인되지 않은 공고는 시나리오를 계산하지 않습니다.")
    bad = set(body.history_filters) - HISTORY_FILTER_KEYS
    if bad:
        raise HTTPException(400, f"쓸 수 없는 과거 자료 조건: {sorted(bad)}")
    extra = dict(body.history_filters)
    for k in ("amount_min", "amount_max"):
        if extra.get(k) is not None:
            extra[k] = Decimal(str(extra[k]))
    spec, rule_info = resolve_lower_limit(session, n, LowerLimitOverride(body.lower_limit_rate_pct, body.a_value))
    try:
        records, samples, f = history_for(session, n, period=body.period, extra=extra)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    sheet = None
    if body.cost_id is not None:
        row = session.get(CompanyCost, body.cost_id)
        if row is None:
            raise HTTPException(404, "원가 자료가 없습니다.")
        sheet = cost_sheet_from_row(row)
    elif body.cost is not None:
        sheet = body.cost.sheet()
    vat = body.bid_vat_included if body.bid_vat_included is not None else n.vat_included
    req = ScenarioRequest(
        base_amount=n.base_amount, lower_limit=spec, sajeong_samples=samples,
        presets=dict(body.presets) if body.presets is not None else dict(SCENARIO_PRESETS),
        custom=[CustomScenario(**c.model_dump()) for c in body.custom], cost=sheet, bid_vat_included=vat,
    )
    result = build_scenarios(req)
    result["notice"] = {"id": n.id, "notice_number": n.notice_number, "title": n.title, "bid_deadline": n.bid_deadline.isoformat() if n.bid_deadline else None}
    result["rule_selection"] = rule_info
    result["sample"]["period"] = f.describe()
    result["sample"]["conditions"] = {k: getattr(n, k) for k in ("procurement_type", "issuing_authority_type", "contract_method", "award_method")} | {
        "lower_limit_rate": str(n.lower_limit_rate) if n.lower_limit_rate is not None else None}
    result["sample"]["notice_ids"] = sorted(r.notice_id for r in records)
    result["bid_vat_included"] = vat
    if sheet is not None:
        result["cost"] = cost_summary(sheet) | {"break_even": break_even(sheet, bid_vat_included=vat)}
    result["dataset_version"] = dataset_version(records, f.as_of)
    return result, records


@router.post("/api/recommend", summary="투찰 시나리오(보수·중립·공격·사용자 정의) 계산")
def recommend(body: RecommendIn, session: Session = Depends(get_session)) -> dict:
    result, _ = run_recommend(body, session)
    if body.save:
        spec = result["lower_limit"]
        run = AnalysisRun(
            notice_id=body.notice_id, analysis_type="recommend", input_snapshot=body.model_dump(mode="json"),
            rule_version={spec["rule_code"]: spec["rule_version"]} if spec["rule_code"] else None,
            dataset_version=result["dataset_version"], assumptions=result["warnings"], result_summary=result,
            confidence_status=result["status"],
        )
        session.add(run)
        session.flush()
        for s in result["scenarios"]:
            est = Decimal(s["assumed_estimated_price"]) if s.get("assumed_estimated_price") else None
            profit = s.get("profit") or {}
            session.add(BidScenario(
                analysis_run_id=run.id, scenario_name=s["name"], target_rate=Decimal(s["bid_rate_vs_base_amount"]),
                rate_basis=RateBasis.BASE_AMOUNT, candidate_amount=Decimal(s["candidate_amount"]),
                # 원 미만이 있는 가정 예정가격은 금액 칸에 반올림해 넣지 않고 explanation 에 원래 값으로 둔다.
                assumed_estimated_price=est if est is not None and est == est.to_integral_value() else None,
                estimated_profit=Decimal(profit["profit"]) if profit.get("profit") is not None else None,
                estimated_margin=Decimal(profit["margin_pct"]) if profit.get("margin_pct") is not None else None,
                risk_flags=s["risk_flags"], explanation=s,
            ))
        session.commit()
        result["analysis_run_id"] = run.id
    return result


# ------------------------------------------------------------------ 원가


def _cost_out(row: CompanyCost) -> dict:
    sheet = cost_sheet_from_row(row)
    return {"id": row.id, "notice_id": row.notice_id, "notes": row.notes,
            "target_profit": str(row.target_profit) if row.target_profit is not None else None,
            "target_profit_rate": str(row.target_profit_rate) if row.target_profit_rate is not None else None,
            "summary": cost_summary(sheet), "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.post("/api/costs", status_code=201, summary="원가 자료 등록(민감 자료)")
def create_cost(body: CostIn, session: Session = Depends(get_session)) -> dict:
    body.sheet()
    if body.notice_id is not None and session.get(ProcurementNotice, body.notice_id) is None:
        raise HTTPException(404, "공고가 없습니다.")
    row = CompanyCost(**body.model_dump())
    session.add(row)
    session.commit()
    return _cost_out(row)


@router.get("/api/costs/{cost_id}")
def get_cost(cost_id: int, session: Session = Depends(get_session)) -> dict:
    row = session.get(CompanyCost, cost_id)
    if row is None:
        raise HTTPException(404, "원가 자료가 없습니다.")
    return _cost_out(row)


@router.put("/api/costs/{cost_id}", summary="원가 자료 수정(전체 교체)")
def update_cost(cost_id: int, body: CostIn, session: Session = Depends(get_session)) -> dict:
    row = session.get(CompanyCost, cost_id)
    if row is None:
        raise HTTPException(404, "원가 자료가 없습니다.")
    body.sheet()
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    session.commit()
    return _cost_out(row)


class CostEvalIn(BaseModel):
    cost_id: int | None = None
    cost: CostIn | None = None
    bid_amount: Decimal | None = None
    bid_vat_included: bool | None = None


@router.post("/api/costs/evaluate", summary="투찰금액별 이익·이익률, 손익분기 금액")
def evaluate_cost(body: CostEvalIn, session: Session = Depends(get_session)) -> dict:
    if body.cost_id is not None:
        row = session.get(CompanyCost, body.cost_id)
        if row is None:
            raise HTTPException(404, "원가 자료가 없습니다.")
        sheet = cost_sheet_from_row(row)
    elif body.cost is not None:
        sheet = body.cost.sheet()
    else:
        raise HTTPException(400, "cost_id 또는 cost 를 지정하세요.")
    out = {"summary": cost_summary(sheet), "break_even": break_even(sheet, bid_vat_included=body.bid_vat_included)}
    if body.bid_amount is not None:
        out["profit"] = evaluate_profit(body.bid_amount, sheet, bid_vat_included=body.bid_vat_included)
    return out


# ------------------------------------------------------------------ 적격심사


class QualItemIn(BaseModel):
    item_code: str = Field(min_length=1, max_length=60)
    item_name: str = Field(min_length=1, max_length=200)
    max_score: Decimal | None = None
    score: Decimal | None = None
    status: str = "unknown"
    basis: str | None = None
    source_reference: str | None = Field(None, max_length=300)


class QualIn(BaseModel):
    items: list[QualItemIn]
    pass_threshold: Decimal | None = None


@router.get("/api/qualification/templates", summary="점검 항목 이름 템플릿(배점 없음)")
def qualification_templates() -> dict:
    return {"items": [{"item_code": c, "item_name": n} for c, n in TEMPLATE_ITEMS],
            "note": "배점과 통과 기준은 공고의 심사기준마다 다르므로 직접 입력해야 합니다."}


def _qual_items(rows: list[QualificationCheck]) -> list[QualItem]:
    return [QualItem(item_code=r.item_code, item_name=r.item_name, max_score=r.max_score, score=r.score,
                     status=r.score_status.value, basis=r.basis, source_reference=r.source_reference) for r in rows]


def _qual_out(notice_id: int, rows: list[QualificationCheck], threshold: Decimal | None) -> dict:
    return {
        "notice_id": notice_id,
        "items": [{"item_code": r.item_code, "item_name": r.item_name,
                   "max_score": str(r.max_score) if r.max_score is not None else None,
                   "score": str(r.score) if r.score is not None else None, "status": r.score_status.value,
                   "basis": r.basis, "source_reference": r.source_reference} for r in rows],
        "evaluation": evaluate_items(_qual_items(rows), pass_threshold=threshold),
    }


@router.get("/api/notices/{notice_id}/qualification", summary="공고별 적격심사 점검표와 점수 범위")
def get_qualification(notice_id: int, pass_threshold: Decimal | None = None, session: Session = Depends(get_session)) -> dict:
    if session.get(ProcurementNotice, notice_id) is None:
        raise HTTPException(404, "공고가 없습니다.")
    rows = list(session.scalars(select(QualificationCheck).where(QualificationCheck.notice_id == notice_id).order_by(QualificationCheck.id)))
    return _qual_out(notice_id, rows, pass_threshold)


@router.put("/api/notices/{notice_id}/qualification", summary="공고별 적격심사 점검표 저장(전체 교체)")
def put_qualification(notice_id: int, body: QualIn, session: Session = Depends(get_session)) -> dict:
    if session.get(ProcurementNotice, notice_id) is None:
        raise HTTPException(404, "공고가 없습니다.")
    items = [QualItem(**i.model_dump()) for i in body.items]
    evaluate_items(items, pass_threshold=body.pass_threshold)  # 저장 전에 검증
    session.execute(delete(QualificationCheck).where(QualificationCheck.notice_id == notice_id))
    rows = [QualificationCheck(notice_id=notice_id, item_code=i.item_code, item_name=i.item_name, max_score=i.max_score,
                               score=i.score, score_status=ScoreStatus(i.status), basis=i.basis, source_reference=i.source_reference)
            for i in items]
    session.add_all(rows)
    session.commit()
    return _qual_out(notice_id, rows, body.pass_threshold)
