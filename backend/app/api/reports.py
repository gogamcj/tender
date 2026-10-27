"""보고서 내보내기(XLSX·CSV)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user
from app.api.notices import notice_summary, search_order, search_params, search_statement
from app.api.recommend import _cost_row
from app.db.models import AnalysisRun, ProcurementNotice, User
from app.db.session import get_session
from app.engines.recommend import COST_ITEMS, break_even, cost_summary, evaluate_profit
from app.reports.writer import Report, Table, to_csv, to_xlsx
from app.services.recommend import cost_sheet_from_row
from app.services.rules import list_rules

router = APIRouter(prefix="/api/reports", tags=["보고서"])

MAX_EXPORT_ROWS = 20000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ESTIMATE_NOTE = "가정 기반 분석 값(가정 예정가격·후보금액·이익 등)은 확정값이 아닙니다. 낙찰을 보장하지 않습니다."


def _send(report: Report, fmt: str, filename: str) -> Response:
    if fmt == "xlsx":
        body, media = to_xlsx(report), XLSX
    elif fmt == "csv":
        body, media = to_csv(report), "text/csv; charset=utf-8"
    else:
        raise HTTPException(400, "형식은 xlsx 또는 csv 입니다.")
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
    name = f"{filename}_{stamp}.{fmt}"
    return Response(body, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


NOTICE_COLUMNS = [
    ("notice_number", "공고번호"), ("notice_revision", "차수"), ("title", "공고명"), ("agency_name", "공고기관"),
    ("demand_agency_name", "수요기관"), ("procurement_type", "업무구분"), ("issuing_authority_type", "기관유형"),
    ("contract_method", "계약방법"), ("award_method", "낙찰자 결정방법"), ("region_name", "지역"), ("industry_name", "업종"),
    ("announcement_date", "공고일"), ("bid_deadline", "입찰마감(UTC)"), ("opening_date", "개찰일시(UTC)"),
    ("base_amount", "기초금액"), ("presumed_price", "추정가격"), ("estimated_price", "예정가격"),
    ("estimated_price_status", "예정가격 상태"), ("lower_limit_rate", "낙찰하한율(%)"), ("data_status_label", "데이터 상태"),
    ("opening_status", "개찰 상태"), ("bid_count", "참가업체수"), ("winning_vendor_name", "낙찰업체"),
    ("winning_bid_amount", "낙찰금액"), ("winning_rate", "낙찰률(%)"), ("winning_rate_basis", "낙찰률 기준"),
    ("actual_sajeong_rate", "사정률(%)"), ("source_name", "출처"),
]
NOTICE_KINDS = {"base_amount": "money", "presumed_price": "money", "estimated_price": "money", "winning_bid_amount": "money",
                "lower_limit_rate": "rate", "winning_rate": "rate", "actual_sajeong_rate": "rate", "bid_count": "int"}


@router.get("/notices.{fmt}", summary="공고 목록(검색 조건 그대로) XLSX·CSV")
def export_notices(fmt: str, params: dict = Depends(search_params), session: Session = Depends(get_session)) -> Response:
    stmt = search_statement(params)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = []
    for n in session.scalars(stmt.options(selectinload(ProcurementNotice.results)).order_by(*search_order(params)).limit(MAX_EXPORT_ROWS)):
        d = notice_summary(n)
        rows.append({**d, **(d.pop("result") or {})})
    cond = {k: str(v) for k, v in params.items() if v is not None}
    info = [("검색 조건", cond), ("건수", f"{len(rows)} / 전체 {total}" + (" (최대 건수까지만 저장)" if total > len(rows) else "")),
            ("일시 기준", "일시는 UTC 로 저장된 값입니다(한국 시간 = UTC + 9시간)."),
            ("추정값 여부", "예정가격 상태가 actual 이 아닌 값은 확정 예정가격이 아닙니다.")]
    return _send(Report("공고 목록", info, [Table("공고 목록", NOTICE_COLUMNS, rows, NOTICE_KINDS)]), fmt, "notices")


SUMMARY_COLUMNS = [("label", "조건"), ("n", "건수"), ("mean", "평균"), ("median", "중앙값"), ("q1", "1사분위"), ("q3", "3사분위"),
                   ("std", "표준편차"), ("min", "최소"), ("max", "최대"), ("outliers", "이상치 수"), ("warnings", "경고")]
SUMMARY_KINDS = {k: "rate" for k in ("mean", "median", "q1", "q3", "std", "min", "max")} | {"n": "int", "outliers": "int"}


def _stats_tables(res: dict) -> list[Table]:
    strata = [{"label": s["label"], **s["summary"]} for s in res.get("strata", [])]
    groups = [{"label": s["label"], "group": ", ".join(f"{k}={v}" for k, v in g["key"].items()), **g["summary"]}
              for s in res.get("strata", []) for g in s.get("groups", [])]
    trend = [{"label": s["label"], **t} for s in res.get("strata", []) for t in s.get("trend", [])]
    return [
        Table("조건별 요약", SUMMARY_COLUMNS, strata, SUMMARY_KINDS),
        Table("묶음별", [("label", "조건"), ("group", "묶음"), *SUMMARY_COLUMNS[1:]], groups, SUMMARY_KINDS),
        Table("추세", [("label", "조건"), ("period", "기간"), ("n", "건수"), ("median", "중앙값"), ("mean", "평균")], trend,
              {"n": "int", "median": "rate", "mean": "rate"}),
    ]


def _similar_tables(res: dict) -> list[Table]:
    rows = [{**m, "components": m.get("components"), "reasons": m.get("reasons")} for m in res.get("matches", [])]
    cols = [("notice_id", "공고ID"), ("title", "공고명"), ("agency_name", "기관"), ("opening_date", "개찰일시(UTC)"),
            ("base_amount", "기초금액"), ("score", "유사도 점수"), ("components", "항목별 점수"), ("reasons", "선정 이유"),
            ("unknown_conditions", "미상 조건"), ("sajeong_rate", "사정률(%)"), ("winning_rate", "낙찰률(%)"), ("rate_basis", "낙찰률 기준"),
            ("bid_count", "참가업체수")]
    return [Table("유사 입찰", cols, rows, {"base_amount": "money", "score": "rate", "sajeong_rate": "rate", "winning_rate": "rate", "bid_count": "int"})]


def _recommend_tables(res: dict) -> list[Table]:
    rows = []
    for s in res.get("scenarios", []):
        hc, pf = s.get("historical_check") or {}, s.get("profit") or {}
        rows.append({**s, "hc_n": hc.get("n"), "hc_below": hc.get("below_lower_limit"), "hc_above": hc.get("above_estimated_price"),
                     "profit": pf.get("profit"), "margin": pf.get("margin_pct"), "profit_status": pf.get("status"),
                     "steps": (s.get("explanation") or {}).get("steps")})
    cols = [("label", "시나리오"), ("method", "방법"), ("assumed_sajeong_rate", "가정 사정률(%)"), ("assumed_estimated_price", "가정 예정가격"),
            ("assumed_lower_limit", "가정 하한금액"), ("candidate_amount", "후보 투찰금액"), ("bid_rate_vs_base_amount", "기초금액 대비(%)"),
            ("hc_n", "과거 사정률 건수"), ("hc_below", "하한 미달 건수"), ("hc_above", "예정가격 초과 건수"),
            ("profit", "예상 이익"), ("margin", "이익률(%)"), ("profit_status", "이익 계산 상태"), ("risk_flags", "위험 표시"), ("steps", "계산 과정")]
    kinds = {"assumed_sajeong_rate": "rate", "assumed_estimated_price": "rate", "assumed_lower_limit": "rate", "candidate_amount": "money",
             "bid_rate_vs_base_amount": "rate", "hc_n": "int", "hc_below": "int", "hc_above": "int", "profit": "money", "margin": "rate"}
    tables = [Table("시나리오 비교", cols, rows, kinds)]
    if res.get("cost"):
        c = res["cost"]
        tables.append(Table("원가", [("label", "항목"), ("value", "금액")],
                            [{"label": v["label"], "value": v["value"]} for v in c["items"].values()]
                            + [{"label": "총원가(공급가액)", "value": c.get("supply_total")}], {"value": "money"}))
    return tables


@router.get("/runs/{run_id}.{fmt}", summary="저장된 분석 결과 보고서(통계·유사 입찰·투찰 시나리오)")
def export_run(run_id: int, fmt: str, session: Session = Depends(get_session), user: User = Depends(current_user)) -> Response:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "분석 실행 기록이 없습니다.")
    res = run.result_summary or {}
    builders = {"stats": ("개찰 결과 분석", _stats_tables), "similar": ("유사 입찰 비교", _similar_tables),
                "recommend": ("투찰 시나리오 비교", _recommend_tables)}
    if run.analysis_type not in builders:
        raise HTTPException(400, f"보고서를 지원하지 않는 분석 종류입니다: {run.analysis_type}")
    if run.analysis_type == "recommend" and res.get("cost") and run.created_by not in (None, user.id) and user.role.value != "admin":
        res = {**res, "cost": None, "scenarios": [{**s, "profit": None} for s in res.get("scenarios", [])]}  # 남의 원가는 빼고
    title, build = builders[run.analysis_type]
    period = res.get("period") or (res.get("sample") or {}).get("period")
    info = [
        ("분석 종류", run.analysis_type), ("분석 실행 ID", run.id), ("분석 시각", run.created_at.isoformat()),
        ("분석 기준일·기간", period), ("데이터 버전", run.dataset_version), ("적용 규칙", run.rule_version or "없음"),
        ("하한 산식", (res.get("lower_limit") or {}).get("formula")), ("지표 정의", res.get("metric_definition") or res.get("definition")),
        ("결과 상태", run.confidence_status), ("가정·경고", run.assumptions or res.get("warnings")),
        ("추정값 여부", ESTIMATE_NOTE if run.analysis_type == "recommend" else "과거 관측값의 요약입니다."),
        ("안내", res.get("disclaimer")),
    ]
    return _send(Report(title, [(k, v) for k, v in info if v is not None], build(res)), fmt, f"{run.analysis_type}_{run.id}")


@router.get("/costs/{cost_id}.{fmt}", summary="원가·수익성 보고서(작성자·관리자만)")
def export_cost(cost_id: int, fmt: str, bid_amounts: list[Decimal] = Query([]), bid_vat_included: bool | None = None,
                session: Session = Depends(get_session), user: User = Depends(current_user)) -> Response:
    row = _cost_row(session, cost_id, user)
    sheet = cost_sheet_from_row(row)
    summ, be = cost_summary(sheet), break_even(sheet, bid_vat_included=bid_vat_included)
    items = [{"label": COST_ITEMS[k], "value": v["value"], "status": "입력" if v["value"] is not None else "미입력"} for k, v in summ["items"].items()]
    profits = []
    for amt in bid_amounts[:50]:
        p = evaluate_profit(amt, sheet, bid_vat_included=bid_vat_included)
        profits.append({"bid": str(amt), **p, "flags": p.get("flags")})
    info = [("원가 ID", row.id), ("공고 ID", row.notice_id), ("부가세 처리(원가)", summ["vat_treatment"]),
            ("투찰금액 부가세 포함", bid_vat_included), ("총원가(공급가액)", summ["supply_total"] or "미확정(미입력 항목 있음)"),
            ("손익분기 투찰금액", be.get("break_even_bid")), ("목표 이익 최소 투찰금액", be.get("min_bid_for_target_profit")),
            ("목표 이익률 최소 투찰금액", be.get("min_bid_for_target_margin")), ("산식", be.get("formula")),
            ("경고", summ["warnings"] + be.get("warnings", [])), ("추정값 여부", "업체 내부 예상 원가 기준이며 법정 원가계산이 아닙니다.")]
    tables = [Table("원가 항목", [("label", "항목"), ("value", "금액"), ("status", "상태")], items, {"value": "money"}),
              Table("투찰금액별 손익", [("bid", "투찰금액"), ("bid_supply_amount", "공급가액"), ("cost_supply_total", "총원가"),
                                    ("profit", "이익"), ("margin_pct", "이익률(%)"), ("status", "상태"), ("flags", "표시")], profits,
                    {"bid": "money", "bid_supply_amount": "rate", "cost_supply_total": "rate", "profit": "money", "margin_pct": "rate"})]
    return _send(Report("원가·수익성 분석", [(k, v) for k, v in info if v is not None], tables), fmt, f"cost_{row.id}")


@router.get("/rules.{fmt}", summary="계산 규칙 요약(유효기간·검증 상태·근거)")
def export_rules(fmt: str, session: Session = Depends(get_session)) -> Response:
    rows = [{"rule_code": r.rule_code, "rule_name": r.rule_name, "version": r.source_version, "procurement_type": r.procurement_type,
             "issuing_authority_type": r.issuing_authority_type, "contract_method": r.contract_method, "award_method": r.award_method,
             "effective_from": r.effective_from.isoformat(), "effective_until": r.effective_until.isoformat() if r.effective_until else "현재",
             "module": r.formula_definition.get("module"), "params": r.formula_definition.get("params"), "rounding": r.rounding_rule,
             "verification": r.verification_status.value, "source_document": r.source_document, "source_url": r.source_url}
            for r in list_rules(session)]
    cols = [("rule_code", "규칙 코드"), ("rule_name", "이름"), ("version", "버전"), ("procurement_type", "대분류"), ("issuing_authority_type", "기관유형"),
            ("contract_method", "계약방법"), ("award_method", "결정방법"), ("effective_from", "시행일"), ("effective_until", "종료일"),
            ("module", "산식 모듈"), ("params", "파라미터"), ("rounding", "단수처리"), ("verification", "검증 상태"),
            ("source_document", "근거 문서"), ("source_url", "근거 URL")]
    info = [("안내", "미검증 규칙(verification=unverified)으로 낸 계산은 확정 결과가 아닙니다.")]
    return _send(Report("계산 규칙 요약", info, [Table("규칙", cols, rows)]), fmt, "rules")
