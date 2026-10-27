from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.engines.calc import CalcInputError, PriceStatus
from app.engines.rules import (
    MatchOutcome,
    NoticeContext,
    RuleBlockedError,
    RuleDefinition,
    evaluate_rule,
    match_rule,
    select_rules,
)


def make_rule(**overrides) -> RuleDefinition:
    data = {
        "rule_code": "TEST_LOWER_LIMIT",
        "rule_name": "테스트용 단순 하한율 규칙(실제 규정 아님)",
        "procurement_type": "construction",
        "issuing_authority_type": "national",
        "award_method": "qualification_review",
        "effective_from": date(2024, 1, 1),
        "effective_until": date(2024, 12, 31),
        "formula_definition": {"module": "simple_lower_limit", "params": {"lower_limit_rate_pct": "87.745"}},
        "rounding_rule": {"mode": "truncate", "unit": 1},
        "applicability": {"amount_basis": "presumed_price", "amount_min": "1000000000", "amount_max_exclusive": "5000000000"},
        "verification_status": "unverified",
    }
    data.update(overrides)
    return RuleDefinition.model_validate(data)


def ctx(**overrides) -> NoticeContext:
    data = {
        "announcement_date": date(2024, 6, 1),
        "procurement_type": "construction",
        "issuing_authority_type": "national",
        "award_method": "qualification_review",
        "presumed_price": Decimal("2000000000"),
    }
    data.update(overrides)
    return NoticeContext.model_validate(data)


def test_match_inside_period_and_bracket():
    m = match_rule(make_rule(), ctx())
    assert m.outcome is MatchOutcome.MATCH


def test_no_retroactive_application():
    """2025년에 시작한 새 규칙은 2024년 공고에 적용되지 않는다."""
    new_rule = make_rule(rule_code="NEW", effective_from=date(2025, 1, 1), effective_until=None)
    m = match_rule(new_rule, ctx(announcement_date=date(2024, 6, 1)))
    assert m.outcome is MatchOutcome.NO_MATCH
    assert any("유효기간 밖" in r for r in m.reasons)


def test_effective_until_is_inclusive():
    assert match_rule(make_rule(), ctx(announcement_date=date(2024, 12, 31))).outcome is MatchOutcome.MATCH
    assert match_rule(make_rule(), ctx(announcement_date=date(2025, 1, 1))).outcome is MatchOutcome.NO_MATCH


def test_missing_announcement_date_is_undetermined_not_match():
    m = match_rule(make_rule(), ctx(announcement_date=None))
    assert m.outcome is MatchOutcome.UNDETERMINED


def test_amount_bracket_boundaries():
    rule = make_rule()
    assert match_rule(rule, ctx(presumed_price=Decimal("1000000000"))).outcome is MatchOutcome.MATCH  # 이상
    assert match_rule(rule, ctx(presumed_price=Decimal("5000000000"))).outcome is MatchOutcome.NO_MATCH  # 미만
    assert match_rule(rule, ctx(presumed_price=None)).outcome is MatchOutcome.UNDETERMINED


def test_unknown_notice_field_is_undetermined():
    m = match_rule(make_rule(), ctx(award_method=None))
    assert m.outcome is MatchOutcome.UNDETERMINED


def test_mismatch_beats_undetermined():
    m = match_rule(make_rule(), ctx(award_method=None, procurement_type="goods"))
    assert m.outcome is MatchOutcome.NO_MATCH


def test_retired_rule_never_matches():
    m = match_rule(make_rule(verification_status="retired"), ctx())
    assert m.outcome is MatchOutcome.NO_MATCH


def test_selection_auto_selects_only_when_unique():
    r1 = make_rule(rule_code="A")
    r2 = make_rule(rule_code="B")
    sel = select_rules([r1, r2], ctx())
    assert sel.selected is None
    assert any(w.startswith("AMBIGUOUS_RULE") for w in sel.warnings)

    sel1 = select_rules([r1], ctx())
    assert sel1.selected is r1


def test_selection_with_undetermined_does_not_auto_select():
    r1 = make_rule(rule_code="A")
    r2 = make_rule(rule_code="B", award_method="lowest_price")
    sel = select_rules([r1, r2], ctx(award_method=None))
    assert sel.selected is None
    assert len(sel.undetermined) == 2


def test_selection_no_rule_warns():
    sel = select_rules([], ctx())
    assert sel.selected is None
    assert any(w.startswith("NO_RULE") for w in sel.warnings)


def test_unverified_rule_is_not_definitive():
    ev = evaluate_rule(make_rule(), {"reference_price": "99500000", "price_status": "actual"})
    assert ev.result.value == Decimal("87306275")
    assert ev.definitive is False
    assert any(f.startswith("UNVERIFIED_RULE") for f in ev.flags)


def test_unverified_rule_can_be_blocked():
    with pytest.raises(RuleBlockedError):
        evaluate_rule(make_rule(), {"reference_price": "1", "price_status": "actual"}, block_unverified=True)


def test_verified_rule_with_actual_price_is_definitive():
    rule = make_rule(verification_status="verified", source_document="테스트 문서 제1조")
    ev = evaluate_rule(rule, {"reference_price": "99500000", "price_status": "actual"})
    assert ev.definitive is True
    assert ev.flags == ()


def test_verified_rule_with_assumed_price_is_not_definitive():
    rule = make_rule(verification_status="verified", source_document="테스트 문서")
    ev = evaluate_rule(rule, {"reference_price": "99500000", "price_status": PriceStatus.SCENARIO.value})
    assert ev.definitive is False
    assert ev.result.status_label == "가정 기반 분석"


def test_verified_rule_without_rounding_is_not_definitive():
    rule = make_rule(verification_status="verified", source_document="테스트 문서", rounding_rule=None)
    ev = evaluate_rule(rule, {"reference_price": "123456789", "price_status": "actual"})
    assert ev.definitive is False
    assert any(f.startswith("ROUNDING_RULE_UNKNOWN") for f in ev.flags)


def test_verified_requires_source():
    with pytest.raises(ValidationError):
        make_rule(verification_status="verified")


def test_invalid_period_rejected():
    with pytest.raises(ValidationError):
        make_rule(effective_from=date(2025, 1, 1), effective_until=date(2024, 1, 1))


def test_amount_bracket_requires_basis():
    with pytest.raises(ValidationError):
        make_rule(applicability={"amount_min": "1"})


def test_unknown_formula_module():
    with pytest.raises(CalcInputError):
        evaluate_rule(make_rule(formula_definition={"module": "magic", "params": {}}), {})


def test_missing_price_status_input():
    with pytest.raises(CalcInputError) as e:
        evaluate_rule(make_rule(), {"reference_price": "100"})
    assert e.value.field == "price_status"


def test_retired_rule_cannot_be_evaluated():
    with pytest.raises(RuleBlockedError):
        evaluate_rule(make_rule(verification_status="retired"), {"reference_price": "1", "price_status": "actual"})
