"""규칙 저장소: DB 의 bid_rules 와 엔진의 RuleDefinition 을 서로 변환한다."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BidRule
from app.engines.rules import RuleDefinition, VerificationStatus


def to_definition(row: BidRule) -> RuleDefinition:
    return RuleDefinition.model_validate(
        {
            "rule_code": row.rule_code,
            "rule_name": row.rule_name,
            "procurement_type": row.procurement_type,
            "issuing_authority_type": row.issuing_authority_type,
            "contract_method": row.contract_method,
            "award_method": row.award_method,
            "effective_from": row.effective_from,
            "effective_until": row.effective_until,
            "source_document": row.source_document,
            "source_url": row.source_url,
            "source_version": row.source_version,
            "formula_definition": row.formula_definition,
            "rounding_rule": row.rounding_rule,
            "applicability": row.applicability or {},
            "verification_status": row.verification_status,
            "verified_at": row.verified_at.date() if row.verified_at else None,
            "notes": row.notes,
        }
    )


def create_rule(session: Session, rule: RuleDefinition) -> BidRule:
    data = rule.model_dump(mode="json", exclude={"verified_at"})
    row = BidRule(
        **{k: v for k, v in data.items() if k not in {"effective_from", "effective_until", "verification_status"}},
        effective_from=rule.effective_from,
        effective_until=rule.effective_until,
        verification_status=rule.verification_status,
        verified_at=datetime.now(UTC) if rule.verification_status is VerificationStatus.VERIFIED else None,
    )
    session.add(row)
    session.flush()
    return row


def list_rules(session: Session) -> list[BidRule]:
    return list(session.scalars(select(BidRule).order_by(BidRule.rule_code, BidRule.source_version)))


def set_verification(session: Session, row: BidRule, status: VerificationStatus) -> BidRule:
    """검증 상태 변경. 검증됨으로 바꾸려면 근거 문서가 있어야 한다(RuleDefinition 검증 재사용)."""
    candidate = to_definition(row).model_copy(update={"verification_status": status})
    RuleDefinition.model_validate(candidate.model_dump())
    row.verification_status = status
    row.verified_at = datetime.now(UTC) if status is VerificationStatus.VERIFIED else None
    session.flush()
    return row
