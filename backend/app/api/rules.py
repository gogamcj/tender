"""규칙 관리 API: 등록, 조회, 검증 상태 변경, 공고 조건별 선택·평가."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import BidRule
from app.db.session import get_session
from app.engines.rules import NoticeContext, RuleDefinition, VerificationStatus, evaluate_rule, select_rules
from app.services import rules as rule_service

router = APIRouter(prefix="/api/rules", tags=["규칙 관리"])


def _out(row: BidRule) -> dict:
    return {"id": row.id, **rule_service.to_definition(row).model_dump(mode="json")}


@router.get("")
def get_rules(session: Session = Depends(get_session)) -> list[dict]:
    return [_out(r) for r in rule_service.list_rules(session)]


@router.post("", status_code=201)
def post_rule(rule: RuleDefinition, session: Session = Depends(get_session)) -> dict:
    row = rule_service.create_rule(session, rule)
    session.commit()
    return _out(row)


class VerificationIn(BaseModel):
    verification_status: VerificationStatus


@router.patch("/{rule_id}/verification")
def patch_verification(rule_id: int, body: VerificationIn, session: Session = Depends(get_session)) -> dict:
    row = session.get(BidRule, rule_id)
    if row is None:
        raise HTTPException(404, "규칙이 없습니다.")
    rule_service.set_verification(session, row, body.verification_status)
    session.commit()
    return _out(row)


class SelectIn(BaseModel):
    notice: NoticeContext
    inputs: dict[str, Any] | None = None  # 주면 자동 선택된 규칙으로 바로 계산


@router.post("/select", summary="공고 조건에 맞는 규칙 선택(유효기간·조건) 및 선택적 계산")
def post_select(body: SelectIn, session: Session = Depends(get_session)) -> dict:
    defs = [rule_service.to_definition(r) for r in rule_service.list_rules(session)]
    sel = select_rules(defs, body.notice)
    out: dict[str, Any] = {
        "selected_rule_code": sel.selected.rule_code if sel.selected else None,
        "matches": [{"rule_code": m.rule.rule_code, "reasons": list(m.reasons)} for m in sel.matches],
        "undetermined": [{"rule_code": m.rule.rule_code, "reasons": list(m.reasons)} for m in sel.undetermined],
        "warnings": list(sel.warnings),
        "evaluation": None,
    }
    if body.inputs is not None and sel.selected is not None:
        out["evaluation"] = evaluate_rule(
            sel.selected, body.inputs, block_unverified=get_settings().block_unverified_rules
        ).to_dict()
    return out
