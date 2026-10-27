"""적격심사·참가자격 점검표 평가.

- 항목 상태: 확인(confirmed) / 예상(expected) / 미확인(unknown).
- 미확인 항목은 0점이나 만점으로 처리하지 않는다. 미확인 항목이 있으면 총점은 한 값이 아니라 범위로만 낸다.
- 통과 기준점을 주면 범위 전체가 기준 이상일 때만 '통과', 범위 전체가 기준 미만일 때만 '미달', 그 밖은 '판단 불가'.
- 배점은 공고·적용 심사기준마다 다르므로 기본 배점을 넣지 않는다. 템플릿은 항목 이름만 제공한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..calc import to_decimal
from ..calc.errors import CalcInputError

STATUSES = ("confirmed", "expected", "unknown")

# 흔히 쓰이는 심사 항목 이름(배점 없음). 실제 항목·배점은 해당 공고의 심사기준에서 확인해 입력한다.
TEMPLATE_ITEMS = (
    ("experience", "시공(수행)실적"),
    ("technical", "기술능력"),
    ("financial", "경영상태(신용평가)"),
    ("credibility", "신인도"),
    ("price", "입찰가격"),
    ("subcontract", "하도급관리계획 적정성"),
    ("materials", "자재·인력 조달가격 적정성"),
    ("eligibility_license", "참가자격: 면허·업종 등록"),
    ("eligibility_region", "참가자격: 지역 제한"),
)


@dataclass
class QualItem:
    item_code: str
    item_name: str
    max_score: Decimal | None
    score: Decimal | None
    status: str
    basis: str | None = None
    source_reference: str | None = None

    def validate(self) -> None:
        if self.status not in STATUSES:
            raise CalcInputError(f"{self.item_code}.status", f"상태는 {STATUSES} 중 하나여야 합니다.")
        if self.max_score is not None:
            self.max_score = to_decimal(self.max_score, f"{self.item_code}.max_score")
            if self.max_score < 0:
                raise CalcInputError(f"{self.item_code}.max_score", "배점은 음수일 수 없습니다.")
        if self.status == "unknown":
            if self.score is not None:
                raise CalcInputError(f"{self.item_code}.score", "미확인 항목에는 점수를 넣지 않습니다(0점·만점으로 보지 않음).")
            return
        if self.score is None:
            raise CalcInputError(f"{self.item_code}.score", "확인·예상 항목은 점수를 입력해야 합니다.")
        self.score = to_decimal(self.score, f"{self.item_code}.score")
        if self.score < 0 or (self.max_score is not None and self.score > self.max_score):
            raise CalcInputError(f"{self.item_code}.score", "점수는 0 이상 배점 이하여야 합니다.")


def _verdict(lo: Decimal, hi: Decimal | None, threshold: Decimal | None) -> str | None:
    if threshold is None:
        return None
    if lo >= threshold:
        return "pass"
    if hi is not None and hi < threshold:
        return "fail"
    return "undetermined"


def evaluate_items(items: Sequence[QualItem], *, pass_threshold: object | None = None) -> dict[str, Any]:
    codes = [i.item_code for i in items]
    if len(set(codes)) != len(codes):
        raise CalcInputError("items", "항목 코드가 중복되었습니다.")
    for i in items:
        i.validate()
    threshold = to_decimal(pass_threshold, "pass_threshold") if pass_threshold is not None else None
    confirmed = sum((i.score for i in items if i.status == "confirmed" and i.score is not None), Decimal(0))
    expected = sum((i.score for i in items if i.status == "expected" and i.score is not None), Decimal(0))
    unknown = [i for i in items if i.status == "unknown"]
    pending = [i for i in items if i.status != "confirmed"]  # 확정되지 않은 항목(예상+미확인)

    def upper(extra: Sequence[QualItem]) -> Decimal | None:
        if any(i.max_score is None for i in extra):
            return None
        return sum((i.max_score for i in extra if i.max_score is not None), Decimal(0))

    unk_max = upper(unknown)
    with_expected_hi = None if unk_max is None else confirmed + expected + unk_max
    pend_max = upper(pending)
    confirmed_only_hi = None if pend_max is None else confirmed + pend_max
    total_max = upper(items)
    warnings: list[str] = []
    if unknown:
        warnings.append(f"UNKNOWN_ITEMS: 미확인 항목 {len(unknown)}개가 있어 총점을 범위로만 표시합니다.")
    if any(i.max_score is None for i in items):
        warnings.append("MAX_SCORE_UNKNOWN: 배점이 입력되지 않은 항목이 있어 최고점·상한을 계산하지 못한 부분이 있습니다.")
    return {
        "confirmed_score": str(confirmed),
        "expected_score": str(expected),
        "total_max_score": str(total_max) if total_max is not None else None,
        "unknown_items": [{"item_code": i.item_code, "item_name": i.item_name, "max_score": str(i.max_score) if i.max_score is not None else None} for i in unknown],
        "range_with_expected": {
            "min": str(confirmed + expected), "max": str(with_expected_hi) if with_expected_hi is not None else None,
            "meaning": "확인 점수 + 예상 점수, 미확인 항목은 0점~배점 범위",
            "verdict": _verdict(confirmed + expected, with_expected_hi, threshold),
        },
        "range_confirmed_only": {
            "min": str(confirmed), "max": str(confirmed_only_hi) if confirmed_only_hi is not None else None,
            "meaning": "확인 점수만 인정, 예상·미확인 항목은 0점~배점 범위",
            "verdict": _verdict(confirmed, confirmed_only_hi, threshold),
        },
        "pass_threshold": str(threshold) if threshold is not None else None,
        "warnings": warnings,
        "note": "통과 여부는 범위 전체가 기준 이상(통과)이거나 미만(미달)일 때만 판정합니다. 공고의 심사기준과 반드시 대조하세요.",
    }
