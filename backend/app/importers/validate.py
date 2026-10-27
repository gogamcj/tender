"""업로드 행 검증: 형식 변환, 필수 항목, 교차 검증, 파일 내·기존 데이터 중복, 변경 전후 비교.

DB 에 의존하지 않는다. 기존 데이터 조회는 호출자가 lookup 함수로 넣어 준다.
같은 입력이면 항상 같은 결과가 나오므로, 미리보기와 확정 저장에서 같은 검증을 다시 돌린다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.db.enums import DataStatus, NoticePhase, OpeningStatus, PriceStatus, RateBasis
from app.engines.calc import CalcInputError, RateUnit, sajeong_rate

from .fields import FIELDS_BY_KEY, FieldKind
from .parsing import ParseError, parse_date, parse_datetime, parse_enum, parse_int, parse_money, parse_rate, parse_text
from .reader import Sheet

RESULT_FIELDS = {k for k, f in FIELDS_BY_KEY.items() if f.group == "result"}
# 낙찰률 교차 검증 허용 오차(%p). 표기 반올림 차이를 감안한 값이며 법정 기준이 아니다.
RATE_TOLERANCE = Decimal("0.001")
SAJEONG_OUTLIER_PCT = Decimal("10")


class RowStatus(StrEnum):
    NEW = "new"  # 새 공고
    NEW_REVISION = "new_revision"  # 기존 공고의 새 차수
    UNCHANGED = "unchanged"  # 기존과 같음(저장 안 함)
    CHANGED = "changed"  # 기존과 다름(사용자 확인 필요)
    DUPLICATE_IN_FILE = "duplicate_in_file"  # 같은 파일 안에서 중복
    INVALID = "invalid"  # 오류로 저장 불가


@dataclass(frozen=True)
class ImportOptions:
    rate_unit: RateUnit = RateUnit.PERCENT
    default_winning_rate_basis: RateBasis | None = None
    default_revision: str = "000"
    issuing_authority_type: str | None = None  # 파일 전체에 적용할 값(열이 없을 때)
    procurement_type: str | None = None
    now: datetime | None = None  # 테스트용 기준 시각

    @classmethod
    def from_dict(cls, data: dict | None) -> ImportOptions:
        data = dict(data or {})
        if data.get("rate_unit"):
            data["rate_unit"] = RateUnit(data["rate_unit"])
        if data.get("default_winning_rate_basis"):
            data["default_winning_rate_basis"] = RateBasis(data["default_winning_rate_basis"])
        data.pop("now", None)
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "rate_unit": self.rate_unit.value,
            "default_winning_rate_basis": self.default_winning_rate_basis.value if self.default_winning_rate_basis else None,
            "default_revision": self.default_revision,
            "issuing_authority_type": self.issuing_authority_type,
            "procurement_type": self.procurement_type,
        }


@dataclass(frozen=True)
class ExistingNotice:
    notice_id: int
    source_name: str
    values: dict[str, Any]  # 비교 가능한 정규화 값(공고 + 결과 필드)


Lookup = Callable[[str, str], ExistingNotice | None]  # (공고번호, 차수) → 기존 레코드
RevisionLookup = Callable[[str], list[str]]  # 공고번호 → 기존 차수 목록


@dataclass
class FieldDiff:
    field: str
    label: str
    old: str | None
    new: str | None


@dataclass
class RowResult:
    row_number: int  # 원본 파일의 행 번호(헤더 포함, 1부터)
    raw: dict[str, str]
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: RowStatus = RowStatus.NEW
    existing_id: int | None = None
    diffs: list[FieldDiff] = field(default_factory=list)
    data_status: DataStatus = DataStatus.COLLECTED
    phase: NoticePhase = NoticePhase.PRE_OPENING
    has_result: bool = False

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "status": self.status.value,
            "data_status": self.data_status.value,
            "phase": self.phase.value,
            "existing_id": self.existing_id,
            "values": {k: _fmt(v) for k, v in self.values.items()},
            "errors": self.errors,
            "warnings": self.warnings,
            "diffs": [d.__dict__ for d in self.diffs],
            "raw": self.raw,
        }


@dataclass
class ValidationReport:
    rows: list[RowResult]
    mapping_errors: list[str]

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in RowStatus}
        for r in self.rows:
            out[r.status.value] += 1
        out["total"] = len(self.rows)
        out["with_warnings"] = sum(1 for r in self.rows if r.warnings)
        return out


def _fmt(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def check_mapping(mapping: dict[str, str], columns: list[str], options: ImportOptions) -> list[str]:
    errors = []
    for key, col in mapping.items():
        if key not in FIELDS_BY_KEY:
            errors.append(f"알 수 없는 대상 필드: {key}")
        elif col not in columns:
            errors.append(f"파일에 없는 열: {col} ({FIELDS_BY_KEY[key].label})")
    for key in ("notice_number", "title"):
        if key not in mapping:
            errors.append(f"필수 항목 '{FIELDS_BY_KEY[key].label}' 의 열을 지정해야 합니다.")
    if "winning_rate" in mapping and "winning_rate_basis" not in mapping and options.default_winning_rate_basis is None:
        errors.append("낙찰률 열을 쓰려면 낙찰률 기준(예정가격/기초금액) 열 또는 기본값을 지정해야 합니다.")
    cols = list(mapping.values())
    dup = {c for c in cols if cols.count(c) > 1}
    if dup:
        errors.append(f"한 열이 여러 필드에 지정되었습니다: {', '.join(sorted(dup))}")
    return errors


def _convert(key: str, raw: str, options: ImportOptions, warnings: list[str]) -> Any:
    f = FIELDS_BY_KEY[key]
    if f.kind is FieldKind.TEXT:
        return parse_text(raw, f.max_len)
    if f.kind is FieldKind.MONEY:
        return parse_money(raw)
    if f.kind is FieldKind.RATE:
        value, w = parse_rate(raw, options.rate_unit)
        warnings.extend(f"{f.label}: {x}" for x in w)
        return value
    if f.kind is FieldKind.DATE:
        return parse_date(raw)
    if f.kind is FieldKind.DATETIME:
        return parse_datetime(raw)
    if f.kind is FieldKind.INT:
        return parse_int(raw)
    if f.kind is FieldKind.ENUM:
        assert f.enum_values is not None
        return parse_enum(raw, f.enum_values)
    raise AssertionError(f.kind)


def _cross_checks(r: RowResult, now: datetime) -> None:
    v = r.values
    if v.get("vat_included") is not None:
        v["vat_included"] = v["vat_included"] == "true"
    if v.get("opening_status") == OpeningStatus.FAILED.value and (v.get("winning_vendor_name") or v.get("winning_bid_amount")):
        r.errors.append("개찰 상태가 '유찰'인데 낙찰업체·낙찰금액이 있습니다.")
    if v.get("bid_deadline") and v.get("opening_date") and v["opening_date"] < v["bid_deadline"]:
        r.warnings.append("개찰일시가 입찰마감일시보다 이릅니다.")

    r.has_result = any(v.get(k) is not None for k in RESULT_FIELDS if k not in {"winning_rate_basis"})
    if r.has_result and v.get("opening_status") is None:
        # 결과 정보가 있지만 상태 열이 없으면: 낙찰자 정보가 있으면 '낙찰자 결정', 아니면 '결과 미확인'. 유찰로 추정하지 않는다.
        v["opening_status"] = (
            OpeningStatus.AWARDED.value if v.get("winning_vendor_name") or v.get("winning_bid_amount") else OpeningStatus.UNCONFIRMED.value
        )
    opened = v.get("opening_status") in {OpeningStatus.OPENED.value, OpeningStatus.AWARDED.value, OpeningStatus.FAILED.value, OpeningStatus.REBID.value}
    opening_passed = v.get("opening_date") is not None and v["opening_date"] <= now
    r.phase = NoticePhase.POST_OPENING if opened or opening_passed else NoticePhase.PRE_OPENING

    if v.get("estimated_price") is not None:
        if opened:
            v["estimated_price_status"] = PriceStatus.ACTUAL.value
        else:
            v["estimated_price_status"] = PriceStatus.USER_ASSUMED.value
            r.warnings.append("개찰 결과가 없는 행의 예정가격은 확정값이 아니라 사용자 가정값으로 저장합니다.")
    if v.get("estimated_price") is not None and v.get("base_amount") is not None and opened:
        try:
            sr = sajeong_rate(v["base_amount"], v["estimated_price"]).value
            v["actual_sajeong_rate"] = sr
            if abs(sr) > SAJEONG_OUTLIER_PCT:
                r.warnings.append(f"사정률 {sr}% 가 ±{SAJEONG_OUTLIER_PCT}% 를 벗어납니다. 값을 확인하세요(이상치 후보).")
        except CalcInputError as e:
            r.errors.append(f"사정률 계산 불가: {e.message}")

    if v.get("winning_rate") is not None:
        basis = v.get("winning_rate_basis")
        ref = {"estimated_price": v.get("estimated_price"), "base_amount": v.get("base_amount"), "presumed_price": v.get("presumed_price")}.get(basis or "")
        amt = v.get("winning_bid_amount")
        if ref and amt:
            computed = (Decimal(amt) / Decimal(ref) * 100).quantize(Decimal("0.000001"))
            if abs(computed - v["winning_rate"]) > RATE_TOLERANCE:
                r.warnings.append(
                    f"낙찰률 불일치: 파일 {v['winning_rate']}% vs 계산 {computed}% (낙찰금액 ÷ {basis}). 기준 또는 값을 확인하세요."
                )

    if not r.errors:
        missing = [FIELDS_BY_KEY[k].label for k in ("base_amount", "announcement_date") if v.get(k) is None]
        if missing:
            r.warnings.append(f"일부 항목 누락: {', '.join(missing)}")
            r.data_status = DataStatus.PARTIAL
        if r.phase is NoticePhase.POST_OPENING and not r.has_result:
            r.data_status = DataStatus.RESULT_UNCONFIRMED
        if v.get("opening_status") == OpeningStatus.UNCONFIRMED.value:
            r.data_status = DataStatus.RESULT_UNCONFIRMED


def _diff(r: RowResult, existing: ExistingNotice) -> None:
    for key, new in r.values.items():
        if key in {"notice_number", "notice_revision"} or new is None:
            continue
        old = existing.values.get(key)
        if _fmt(old) != _fmt(new):
            label = FIELDS_BY_KEY[key].label if key in FIELDS_BY_KEY else key
            r.diffs.append(FieldDiff(key, label, _fmt(old), _fmt(new)))


def validate_rows(
    sheet: Sheet,
    mapping: dict[str, str],
    options: ImportOptions,
    lookup: Lookup,
    revisions: RevisionLookup,
    *,
    header_row: int = 0,
) -> ValidationReport:
    mapping_errors = check_mapping(mapping, sheet.columns, options)
    if mapping_errors:
        return ValidationReport(rows=[], mapping_errors=mapping_errors)
    now = options.now or datetime.now(UTC)
    col_index = {c: i for i, c in enumerate(sheet.columns)}
    seen: dict[tuple[str, str], int] = {}
    results: list[RowResult] = []

    for i, row in enumerate(sheet.rows):
        r = RowResult(row_number=header_row + 2 + i, raw=dict(zip(sheet.columns, row, strict=True)))
        for key, col in mapping.items():
            cell = row[col_index[col]]
            if cell.strip() == "":
                r.values[key] = None
                continue
            try:
                r.values[key] = _convert(key, cell, options, r.warnings)
            except ParseError as e:
                r.errors.append(f"{FIELDS_BY_KEY[key].label}: {e}")
                r.values[key] = None
        v = r.values
        v["notice_revision"] = v.get("notice_revision") or options.default_revision
        if options.issuing_authority_type and not v.get("issuing_authority_type"):
            v["issuing_authority_type"] = options.issuing_authority_type
        if options.procurement_type and not v.get("procurement_type"):
            v["procurement_type"] = options.procurement_type
        if v.get("winning_rate") is not None and not v.get("winning_rate_basis") and options.default_winning_rate_basis:
            v["winning_rate_basis"] = options.default_winning_rate_basis.value
        if v.get("winning_rate") is not None and not v.get("winning_rate_basis"):
            r.errors.append("낙찰률 기준이 비어 있습니다.")

        for key in ("notice_number", "title"):
            if not v.get(key) and not any(e.startswith(FIELDS_BY_KEY[key].label) for e in r.errors):
                r.errors.append(f"필수 항목 누락: {FIELDS_BY_KEY[key].label}")

        _cross_checks(r, now)

        if r.errors:
            r.status = RowStatus.INVALID
            results.append(r)
            continue

        key = (v["notice_number"], v["notice_revision"])
        if key in seen:
            r.status = RowStatus.DUPLICATE_IN_FILE
            r.warnings.append(f"같은 파일의 {seen[key]}행과 공고번호·차수가 같아 건너뜁니다.")
            results.append(r)
            continue
        seen[key] = r.row_number

        existing = lookup(*key)
        if existing is not None:
            r.existing_id = existing.notice_id
            _diff(r, existing)
            r.status = RowStatus.CHANGED if r.diffs else RowStatus.UNCHANGED
        elif revisions(v["notice_number"]):
            r.status = RowStatus.NEW_REVISION
            r.warnings.append(f"기존 차수({', '.join(revisions(v['notice_number']))})가 있는 공고의 새 차수입니다.")
        else:
            r.status = RowStatus.NEW
        results.append(r)

    return ValidationReport(rows=results, mapping_errors=[])
