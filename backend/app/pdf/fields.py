"""공고문 텍스트에서 항목 후보를 찾는다.

원칙
- 항목마다 후보를 모두 남긴다(쪽 번호·원문 줄·위치·신뢰도). 값이 서로 다르면 '불일치'로 보여 주고 고르지 않는다.
- 원 단위가 아닌 금액(천원·만원·억원), 해석할 수 없는 날짜는 값으로 바꾸지 않고 원문만 남긴다.
- 신뢰도는 추출 방식에 따른 경험적 점수(0~1)이며 통계적 정확도가 아니다. 모든 값은 사용자 검토 후에만 반영한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.importers.parsing import KST

from .extract import PageContent, PdfContent

CONF_LABELED_WITH_UNIT = 0.9
CONF_TABLE = 0.85
CONF_LABELED_NO_UNIT = 0.7
CONF_KEYWORD = 0.6
CONF_UNPARSED = 0.3


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    labels: tuple[str, ...]
    kind: str  # money / rate / datetime / text / enum / bool / range / code
    target: str | None  # 반영할 공고 컬럼(None 이면 참고용)
    choices: tuple[str, ...] = ()


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("notice_number", "공고번호", ("입찰공고번호", "공고번호"), "code", None),
    FieldSpec("title", "공고명", ("입찰건명", "공고명", "건명"), "text", "title"),
    FieldSpec("agency_name", "공고기관", ("공고기관", "발주기관"), "text", "agency_name"),
    FieldSpec("demand_agency_name", "수요기관", ("수요기관",), "text", "demand_agency_name"),
    FieldSpec("base_amount", "기초금액", ("기초금액",), "money", "base_amount"),
    FieldSpec("presumed_price", "추정가격", ("추정가격",), "money", "presumed_price"),
    FieldSpec("lower_limit_rate", "낙찰하한율", ("낙찰하한율", "낙찰하한률"), "rate", "lower_limit_rate"),
    FieldSpec("a_value", "A값", ("A값", "A 값"), "money", None),
    FieldSpec("bid_deadline", "입찰마감일시", ("입찰마감일시", "입찰서 제출 마감일시", "입찰서제출마감", "투찰마감일시", "입찰마감"), "datetime", "bid_deadline"),
    FieldSpec("opening_date", "개찰일시", ("개찰일시", "개찰 일시"), "datetime", "opening_date"),
    FieldSpec("contract_method", "계약방법", ("계약방법",), "enum", "contract_method",
              ("일반경쟁", "제한경쟁", "지명경쟁", "수의계약")),
    FieldSpec("award_method", "낙찰자 결정방법", ("낙찰자 결정방법", "낙찰자결정방법", "낙찰방법"), "enum", "award_method",
              ("적격심사", "종합심사", "최저가", "협상에 의한 계약", "2단계 경쟁", "희망수량")),
    FieldSpec("reserve_range", "예비가격 범위", ("예비가격 범위", "예비가격범위", "복수예비가격"), "range", None),
    FieldSpec("vat_included", "부가가치세 포함 여부", (), "bool", "vat_included"),
    FieldSpec("region_restriction", "지역제한", ("지역제한", "참가지역", "지역 제한"), "text", None),
    FieldSpec("qualification", "참가자격(업종)", ("참가자격", "업종제한", "업종 제한"), "text", None),
)
FIELD_BY_NAME = {f.name: f for f in FIELDS}


@dataclass
class Candidate:
    field_name: str
    raw_text: str
    value: str | None  # 정규화된 값(문자열). None 이면 해석 불가
    page_number: int
    bbox: list[float] | None
    confidence: float
    method: str  # regex / table / keyword
    table_ref: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


_MONEY_RE = re.compile(r"(?:금\s*)?(?:₩\s*)?(\d{1,3}(?:,\d{3})+|\d+)\s*(천원|만원|억원|원)?")
_RATE_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(%|퍼센트)")
_RANGE_RE = re.compile(r"([+\-−]?\s*\d+(?:\.\d+)?)\s*%\s*[~～∼]\s*([+\-−]?\s*\d+(?:\.\d+)?)\s*%")
_PM_RE = re.compile(r"±\s*(\d+(?:\.\d+)?)\s*%")
_DT_RES = (
    re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?\.?\s*(?:\([^)]*\))?\s*(\d{1,2})\s*[:시]\s*(\d{2})"),
)
_CODE_RE = re.compile(r"([A-Z0-9][A-Z0-9\-]{5,})")


def _clean(s: str) -> str:
    return s.strip(" :：-\t·|")


def parse_value(spec: FieldSpec, text: str) -> tuple[str | None, float, str | None]:
    """(정규화 값, 신뢰도, 메모). 해석 불가면 값 None."""
    t = text.strip()
    if spec.kind == "money":
        m = _MONEY_RE.search(t)
        if not m:
            return None, CONF_UNPARSED, "금액을 찾지 못했습니다."
        unit = m.group(2)
        if unit in {"천원", "만원", "억원"}:
            return None, CONF_UNPARSED, f"원 단위가 아닌 금액({unit})이라 값으로 바꾸지 않았습니다."
        digits = m.group(1).replace(",", "")
        return str(int(digits)), CONF_LABELED_WITH_UNIT if unit == "원" else CONF_LABELED_NO_UNIT, None
    if spec.kind == "rate":
        m = _RATE_RE.search(t)
        if not m:
            return None, CONF_UNPARSED, "% 표기를 찾지 못했습니다."
        try:
            v = Decimal(m.group(1))
        except InvalidOperation:
            return None, CONF_UNPARSED, None
        if not (Decimal(0) < v <= Decimal(100)):
            return None, CONF_UNPARSED, "0~100% 범위를 벗어났습니다."
        return str(v), CONF_LABELED_WITH_UNIT, None
    if spec.kind == "datetime":
        for rx in _DT_RES:
            m = rx.search(t)
            if m:
                y, mo, d, h, mi = (int(x) for x in m.groups())
                try:
                    return datetime(y, mo, d, h, mi, tzinfo=KST).isoformat(), CONF_LABELED_WITH_UNIT, "공고문 시각을 한국 시간으로 보았습니다."
                except ValueError:
                    return None, CONF_UNPARSED, "존재하지 않는 날짜입니다."
        return None, CONF_UNPARSED, "날짜·시각을 해석하지 못했습니다."
    if spec.kind == "enum":
        found = [c for c in spec.choices if c.replace(" ", "") in t.replace(" ", "")]
        if len(found) == 1:
            return found[0], CONF_LABELED_WITH_UNIT, None
        if len(found) > 1:
            return None, CONF_UNPARSED, f"여러 값이 함께 나옵니다: {found}"
        return None, CONF_UNPARSED, "알려진 값과 맞지 않아 원문만 남겼습니다."
    if spec.kind == "range":
        m = _RANGE_RE.search(t)
        if m:
            lo, hi = (Decimal(g.replace(" ", "").replace("−", "-")) for g in m.groups())
            return f"{lo}~{hi}", CONF_LABELED_WITH_UNIT, None
        m = _PM_RE.search(t)
        if m:
            v = Decimal(m.group(1))
            return f"{-v}~{v}", CONF_LABELED_WITH_UNIT, None
        return None, CONF_UNPARSED, "범위(±n% 또는 a%~b%)를 찾지 못했습니다."
    if spec.kind == "code":
        m = _CODE_RE.search(t)
        return (m.group(1), CONF_LABELED_WITH_UNIT, None) if m else (None, CONF_UNPARSED, None)
    value = _clean(t)
    return (value[:300] if value else None), CONF_LABELED_NO_UNIT, None


_BULLET = r"(?:[□■○●◎▶►※·\-]|\(?\d{1,2}[.)]|[가-하][.)])?"
_PAREN = r"(?:\([^)]{0,20}\))?"


def _label_res(spec: FieldSpec) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """(줄 머리 표제, 줄 중간 표제). 줄 중간 표제는 콜론이 있어야 인정한다."""
    alts = "|".join(re.escape(lbl).replace(r"\ ", r"\s*") for lbl in sorted(spec.labels, key=len, reverse=True))
    head = re.compile(rf"^\s*{_BULLET}\s*({alts})\s*{_PAREN}\s*([:：])?\s*(.*)$")
    mid = re.compile(rf"\s({alts})\s*{_PAREN}\s*([:：])\s*(.*)$")
    return head, mid


_NEXT_LABEL = re.compile(
    r"\s(?=(?:" + "|".join(re.escape(lbl) for f in FIELDS for lbl in f.labels) + r")\s*(?:\([^)]{0,20}\))?\s*[:：])"
)


def _bbox(page: PageContent, needle: str) -> list[float] | None:
    p = page._page
    if p is None or not needle:
        return None
    try:
        hits = p.search(re.escape(needle), regex=True)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    if not hits:
        return None
    h = hits[0]
    return [round(h["x0"], 1), round(h["top"], 1), round(h["x1"], 1), round(h["bottom"], 1)]


def _from_lines(page: PageContent, spec: FieldSpec) -> list[Candidate]:
    out: list[Candidate] = []
    head, mid = _label_res(spec)
    for line in page.lines:
        m = head.search(line) or mid.search(line)
        if not m:
            continue
        has_colon = m.group(2) is not None
        # 같은 줄에 다른 항목 표제가 "표제:" 형태로 이어지면 거기서 자른다(예: "공고기관: … 수요기관: …")
        rest = _NEXT_LABEL.split(m.group(3), maxsplit=1)[0]
        if not rest.strip():
            continue
        value, conf, note = parse_value(spec, rest)
        # 콜론 없는 줄은 문장일 수 있으므로 값이 해석될 때만, 글자 항목은 아예 쓰지 않는다
        if not has_colon and (value is None or spec.kind == "text"):
            continue
        out.append(Candidate(spec.name, line, value, page.number, _bbox(page, m.group(1)), conf, "regex", note=note))
    return out


def _from_tables(page: PageContent, spec: FieldSpec) -> list[Candidate]:
    out: list[Candidate] = []
    labels = [lbl.replace(" ", "") for lbl in spec.labels]
    for ti, table in enumerate(page.tables):
        for ri, row in enumerate(table):
            cells = [(c or "").strip() for c in row]
            for ci, cell in enumerate(cells):
                key = re.sub(r"\s+", "", cell)
                key = re.sub(r"\([^)]*\)$", "", key)
                if key and any(key == lbl for lbl in labels):
                    nxt = next((c for c in cells[ci + 1:] if c), None)
                    if nxt is None:
                        continue
                    value, conf, note = parse_value(spec, nxt.replace("\n", " "))
                    if value is not None:
                        conf = min(conf, CONF_TABLE) if spec.kind != "text" else CONF_TABLE
                    out.append(Candidate(spec.name, f"{cell} | {nxt}", value, page.number, _bbox(page, cell.split()[0] if cell.split() else cell),
                                         conf, "table", table_ref=f"t{ti + 1}r{ri + 1}", note=note))
    return out


_VAT_IN = re.compile(r"부가가치세\s*(?:\(\s*VAT\s*\))?\s*포함|부가세\s*포함|VAT\s*포함")
_VAT_EX = re.compile(r"부가가치세\s*(?:별도|불포함|제외)|부가세\s*(?:별도|불포함|제외)|VAT\s*(?:별도|불포함)")


def _vat(page: PageContent) -> list[Candidate]:
    out: list[Candidate] = []
    for line in page.lines:
        for rx, val in ((_VAT_IN, "True"), (_VAT_EX, "False")):
            m = rx.search(line)
            if m:
                out.append(Candidate("vat_included", line, val, page.number, _bbox(page, m.group(0)), CONF_KEYWORD, "keyword",
                                     note="문장 속 표현으로 찾았습니다. 어느 금액에 대한 설명인지 확인하세요."))
    return out


def extract_fields(content: PdfContent) -> list[Candidate]:
    found: list[Candidate] = []
    for page in content.pages:
        for spec in FIELDS:
            if spec.name == "vat_included":
                continue
            found.extend(_from_tables(page, spec))
            found.extend(_from_lines(page, spec))
        found.extend(_vat(page))
    # 같은 쪽·같은 값 후보는 신뢰도가 높은 것 하나만 둔다(표와 본문 텍스트에서 중복으로 잡히는 경우)
    best: dict[tuple, Candidate] = {}
    for c in found:
        key = (c.field_name, c.page_number, c.value if c.value is not None else c.raw_text)
        if key not in best or c.confidence > best[key].confidence:
            best[key] = c
    return sorted(best.values(), key=lambda c: (list(FIELD_BY_NAME).index(c.field_name), c.page_number, -c.confidence))


def summarize_candidates(cands: list[dict[str, Any]]) -> dict[str, Any]:
    """항목별 후보 묶음과 불일치 여부(값이 다른 후보가 둘 이상)."""
    out: dict[str, Any] = {}
    for spec in FIELDS:
        cs = [c for c in cands if c["field_name"] == spec.name]
        values = {c["value"] for c in cs if c["value"] is not None and c.get("review_status") != "rejected"}
        out[spec.name] = {
            "label": spec.label, "kind": spec.kind, "target": spec.target, "candidates": cs,
            "distinct_values": sorted(values), "conflict": len(values) > 1, "found": bool(cs),
        }
    return out
