"""저장된 분석 실행 조회와 재현.

재현은 저장된 입력(input_snapshot)으로 같은 계산을 다시 돌려 데이터셋 버전과 결과가 같은지 비교한다.
기준 시각(as_of)을 지정하지 않은 통계는 실행 시점마다 기간이 달라지므로 데이터가 같아도 결과가 달라질 수 있다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import AnalysisRun, BidScenario, User
from app.db.session import get_session

from . import analysis as analysis_api
from . import recommend as recommend_api

router = APIRouter(prefix="/api/analysis/runs", tags=["분석 실행 기록"])

VOLATILE = {"analysis_run_id", "dataset_version"}


def _brief(run: AnalysisRun) -> dict:
    return {"id": run.id, "analysis_type": run.analysis_type, "notice_id": run.notice_id, "confidence_status": run.confidence_status,
            "dataset_version": run.dataset_version, "rule_version": run.rule_version, "created_at": run.created_at.isoformat()}


@router.get("", summary="분석 실행 목록")
def list_runs(notice_id: int | None = None, analysis_type: str | None = None, limit: int = 50,
              session: Session = Depends(get_session)) -> list[dict]:
    q = select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(min(max(limit, 1), 200))
    if notice_id is not None:
        q = q.where(AnalysisRun.notice_id == notice_id)
    if analysis_type is not None:
        q = q.where(AnalysisRun.analysis_type == analysis_type)
    return [_brief(r) for r in session.scalars(q)]


@router.get("/{run_id}", summary="분석 실행 상세(입력·가정·결과·시나리오)")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "분석 실행 기록이 없습니다.")
    scenarios = session.scalars(select(BidScenario).where(BidScenario.analysis_run_id == run_id).order_by(BidScenario.id))
    return _brief(run) | {
        "input_snapshot": run.input_snapshot, "assumptions": run.assumptions, "result_summary": run.result_summary,
        "scenarios": [{"scenario_name": s.scenario_name, "candidate_amount": str(s.candidate_amount) if s.candidate_amount is not None else None,
                       "target_rate": str(s.target_rate) if s.target_rate is not None else None,
                       "rate_basis": s.rate_basis.value if s.rate_basis else None,
                       "estimated_profit": str(s.estimated_profit) if s.estimated_profit is not None else None,
                       "risk_flags": s.risk_flags} for s in scenarios],
    }


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in VOLATILE}


@router.post("/{run_id}/reproduce", summary="저장된 입력으로 다시 계산해 결과 비교")
def reproduce(run_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "분석 실행 기록이 없습니다.")
    snap = dict(run.input_snapshot) | {"save": False}
    if run.analysis_type == "stats":
        current = analysis_api.stats(analysis_api.StatsIn.model_validate(snap), session)
    elif run.analysis_type == "similar":
        current = analysis_api.similar(analysis_api.SimilarIn.model_validate(snap), session)
    elif run.analysis_type == "recommend":
        current, _ = recommend_api.run_recommend(recommend_api.RecommendIn.model_validate(snap), session, user)
    else:
        raise HTTPException(400, f"재현을 지원하지 않는 분석 종류입니다: {run.analysis_type}")
    data_changed = current.get("dataset_version") != run.dataset_version
    identical = _strip(current) == _strip(run.result_summary or {})
    return {
        "run_id": run.id, "analysis_type": run.analysis_type, "original_dataset_version": run.dataset_version,
        "current_dataset_version": current.get("dataset_version"), "data_changed": data_changed, "result_identical": identical,
        "note": "데이터가 바뀌지 않았는데 결과가 다르면 규칙 또는 계산 방식이 바뀐 것입니다." if not data_changed and not identical else None,
        "current_result": current,
    }
