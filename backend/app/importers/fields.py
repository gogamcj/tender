"""업로드 대상 필드 목록과 열 이름 자동 추천.

자동 추천은 편의 기능일 뿐이며, 사용자가 미리보기 전에 매핑을 확인·수정한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class FieldKind(StrEnum):
    TEXT = "text"
    MONEY = "money"
    RATE = "rate"
    DATE = "date"
    DATETIME = "datetime"
    INT = "int"
    ENUM = "enum"


PROCUREMENT_TYPE_VALUES = {
    "공사": "construction",
    "시설공사": "construction",
    "용역": "service",
    "일반용역": "service",
    "기술용역": "service",
    "물품": "goods",
    "외자": "foreign",
    "기타": "other",
}

AUTHORITY_TYPE_VALUES = {
    "국가기관": "national",
    "국가": "national",
    "지방자치단체": "local",
    "지자체": "local",
    "공기업": "public_corp",
    "준정부기관": "public_corp",
    "기타": "other",
}

OPENING_STATUS_VALUES = {
    "개찰완료": "opened",
    "개찰": "opened",
    "낙찰": "awarded",
    "낙찰자결정": "awarded",
    "유찰": "failed",
    "재입찰": "rebid",
    "미확인": "unconfirmed",
    "결과미확인": "unconfirmed",
}

RATE_BASIS_VALUES = {
    "예정가격": "estimated_price",
    "예가": "estimated_price",
    "기초금액": "base_amount",
    "추정가격": "presumed_price",
}

VAT_INCLUDED_VALUES = {"포함": "true", "부가세포함": "true", "별도": "false", "미포함": "false", "Y": "true", "N": "false"}


@dataclass(frozen=True)
class TargetField:
    key: str
    label: str
    kind: FieldKind
    group: str  # notice / result
    required: bool = False
    max_len: int = 500
    synonyms: tuple[str, ...] = ()
    enum_values: dict[str, str] | None = None


TARGET_FIELDS: tuple[TargetField, ...] = (
    TargetField("notice_number", "공고번호", FieldKind.TEXT, "notice", True, 40, ("공고번호", "입찰공고번호", "bidntceno", "공고no")),
    TargetField("notice_revision", "공고차수", FieldKind.TEXT, "notice", False, 10, ("차수", "공고차수", "bidntceord")),
    TargetField("title", "공고명", FieldKind.TEXT, "notice", True, 500, ("공고명", "입찰공고명", "건명", "사업명", "bidntcenm")),
    TargetField("agency_code", "공고기관코드", FieldKind.TEXT, "notice", False, 20, ("공고기관코드", "ntceinsttcd")),
    TargetField("agency_name", "공고기관", FieldKind.TEXT, "notice", False, 200, ("공고기관", "공고기관명", "발주기관", "발주처", "ntceinsttnm")),
    TargetField("demand_agency_code", "수요기관코드", FieldKind.TEXT, "notice", False, 20, ("수요기관코드", "dminsttcd")),
    TargetField("demand_agency_name", "수요기관", FieldKind.TEXT, "notice", False, 200, ("수요기관", "수요기관명", "dminsttnm")),
    TargetField("issuing_authority_type", "발주기관 유형", FieldKind.ENUM, "notice", False, synonyms=("기관유형", "발주기관유형"), enum_values=AUTHORITY_TYPE_VALUES),
    TargetField("procurement_type", "입찰 대분류", FieldKind.ENUM, "notice", False, synonyms=("업무구분", "입찰구분", "대분류"), enum_values=PROCUREMENT_TYPE_VALUES),
    TargetField("contract_method", "계약방법", FieldKind.TEXT, "notice", False, 60, ("계약방법", "계약방식", "cntrctcnclsmthdnm")),
    TargetField("award_method", "낙찰자 결정방법", FieldKind.TEXT, "notice", False, 60, ("낙찰방법", "낙찰자결정방법", "낙찰방식", "sucsfbidmthdnm")),
    TargetField("region_code", "지역코드", FieldKind.TEXT, "notice", False, 20, ("지역코드",)),
    TargetField("region_name", "지역", FieldKind.TEXT, "notice", False, 100, ("지역", "지역명", "참가가능지역", "지역제한")),
    TargetField("industry_code", "업종코드", FieldKind.TEXT, "notice", False, 20, ("업종코드", "공종코드")),
    TargetField("industry_name", "업종", FieldKind.TEXT, "notice", False, 200, ("업종", "업종명", "공종", "공종명")),
    TargetField("announcement_date", "공고일", FieldKind.DATE, "notice", False, synonyms=("공고일", "공고일자", "게시일", "bidntcedt")),
    TargetField("bid_deadline", "입찰마감일시", FieldKind.DATETIME, "notice", False, synonyms=("입찰마감일시", "마감일시", "입찰마감", "bidclsedt")),
    TargetField("opening_date", "개찰일시", FieldKind.DATETIME, "notice", False, synonyms=("개찰일시", "개찰일", "opengdt")),
    TargetField("base_amount", "기초금액", FieldKind.MONEY, "notice", False, synonyms=("기초금액", "기초가격", "bssamt")),
    TargetField("presumed_price", "추정가격", FieldKind.MONEY, "notice", False, synonyms=("추정가격", "presmptprce")),
    TargetField("estimated_cost", "설계금액·추정금액", FieldKind.MONEY, "notice", False, synonyms=("설계금액", "추정금액", "배정예산")),
    TargetField("vat_amount", "부가가치세", FieldKind.MONEY, "notice", False, synonyms=("부가가치세", "부가세", "vat")),
    TargetField("vat_included", "부가세 포함 여부", FieldKind.ENUM, "notice", False, synonyms=("부가세포함여부", "부가세포함"), enum_values=VAT_INCLUDED_VALUES),
    TargetField("lower_limit_rate", "낙찰하한율(%)", FieldKind.RATE, "notice", False, synonyms=("낙찰하한율", "하한율", "sucsfbidlwltrate")),
    TargetField("notice_url", "공고 URL", FieldKind.TEXT, "notice", False, 1000, ("url", "공고url", "링크")),
    TargetField("estimated_price", "예정가격", FieldKind.MONEY, "result", False, synonyms=("예정가격", "예가", "plnprc")),
    TargetField("opening_status", "개찰 상태", FieldKind.ENUM, "result", False, synonyms=("진행상태", "개찰상태", "결과"), enum_values=OPENING_STATUS_VALUES),
    TargetField("bid_count", "참가업체수", FieldKind.INT, "result", False, synonyms=("참가업체수", "참여업체수", "투찰업체수", "prtcptcnum")),
    TargetField("winning_vendor_name", "낙찰업체", FieldKind.TEXT, "result", False, 200, ("낙찰업체", "낙찰자", "1순위업체", "bidwinnrnm")),
    TargetField("winning_bid_amount", "낙찰금액", FieldKind.MONEY, "result", False, synonyms=("낙찰금액", "sucsfbidamt")),
    TargetField("winning_rate", "낙찰률(%)", FieldKind.RATE, "result", False, synonyms=("낙찰률", "낙찰율", "sucsfbidrate")),
    TargetField("winning_rate_basis", "낙찰률 기준", FieldKind.ENUM, "result", False, synonyms=("낙찰률기준",), enum_values=RATE_BASIS_VALUES),
)

FIELDS_BY_KEY = {f.key: f for f in TARGET_FIELDS}


def _norm(name: str) -> str:
    n = re.sub(r"[\s_\-()（）\[\]/·.]", "", name).lower()
    # '기초금액(원)', '낙찰률(%)' 은 같은 필드로 본다. '(천원)', '(백만원)' 처럼 단위가 다른 열은 자동 추천하지 않는다.
    if n.endswith(("천원", "백만원", "만원", "억원")):
        return n
    return re.sub(r"(원|%)$", "", n)


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    """{target_field: source_column} 자동 추천. 정확히 일치하는 이름만 추천한다(부분 일치로 잘못 붙이지 않음)."""
    normalized = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for f in TARGET_FIELDS:
        for syn in (f.label, *f.synonyms):
            col = normalized.get(_norm(syn))
            if col and col not in used:
                mapping[f.key] = col
                used.add(col)
                break
    return mapping
