"""셀 문자열 → 정규화 값 변환. 변환할 수 없으면 ParseError 를 낸다(추정하지 않음)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.engines.calc import RateUnit

KST = timezone(timedelta(hours=9), "KST")


class ParseError(ValueError):
    pass


_MONEY_RE = re.compile(r"^-?\d+(\.\d+)?$")


def parse_money(raw: str) -> Decimal:
    """'1,234,567', '1234567원', '₩1,234,567' 을 허용. '1.2억' 같은 단위 표기는 오해 소지가 있어 거부한다."""
    s = raw.strip().replace(",", "").replace("원", "").replace("₩", "").replace(" ", "")
    if re.search(r"[억만천]", s):
        raise ParseError(f"단위 표기(억·만) 금액은 지원하지 않습니다. 원 단위 숫자로 입력하세요: {raw!r}")
    if not _MONEY_RE.match(s):
        raise ParseError(f"금액 형식이 아닙니다: {raw!r}")
    value = Decimal(s)
    if value != value.to_integral_value():
        raise ParseError(f"원 미만 금액이 포함되어 있습니다: {raw!r}")
    if value < 0:
        raise ParseError(f"음수 금액입니다: {raw!r}")
    return value.quantize(Decimal(1))


def parse_rate(raw: str, unit: RateUnit) -> tuple[Decimal, list[str]]:
    """비율을 % 단위 Decimal 로. 셀에 '%' 가 붙어 있으면 지정 단위와 상관없이 % 로 본다."""
    s = raw.strip().replace(" ", "")
    warnings: list[str] = []
    has_pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ParseError(f"비율 형식이 아닙니다: {raw!r}") from exc
    if not value.is_finite():
        raise ParseError(f"비율 형식이 아닙니다: {raw!r}")
    if has_pct:
        pct = value
    elif unit is RateUnit.RATIO:
        pct = value * 100
    else:
        pct = value
        if Decimal(0) < value <= Decimal("1.5"):
            warnings.append(f"비율 {raw} 이(가) 소수(비율) 형식처럼 보입니다. 단위 설정을 확인하세요.")
    if unit is RateUnit.RATIO and not has_pct and value > Decimal("1.5"):
        warnings.append(f"비율 {raw} 이(가) 퍼센트 형식처럼 보입니다. 단위 설정을 확인하세요.")
    quantized = pct.quantize(Decimal("0.000001"))
    if quantized != pct:
        raise ParseError(f"비율의 소수 자릿수가 너무 깁니다(% 기준 최대 6자리): {raw!r}")
    return quantized, warnings


_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})\.?$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
    re.compile(r"^(\d{4})년\s?(\d{1,2})월\s?(\d{1,2})일$"),
]


def parse_date(raw: str) -> date:
    s = raw.strip()
    # "2024-06-01 00:00:00" 처럼 시간이 붙은 경우 날짜 부분만
    head = s.split(" ")[0] if re.match(r"^\d{4}[-./]\d", s) else s
    for pat in _DATE_PATTERNS:
        m = pat.match(head)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError as exc:
                raise ParseError(f"존재하지 않는 날짜입니다: {raw!r}") from exc
    raise ParseError(f"날짜 형식이 아닙니다: {raw!r}")


_DT_RE = re.compile(r"^(.+?)[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")


def parse_datetime(raw: str) -> datetime:
    """시각이 없으면 00:00 으로 둔다. 시간대 표기가 없으면 한국 표준시(KST)로 본다."""
    s = raw.strip()
    if re.match(r"^\d{12}$", s):  # 나라장터 API 형식 YYYYMMDDHHMM
        s = f"{s[:8]} {s[8:10]}:{s[10:12]}"
    m = _DT_RE.match(s)
    if m:
        d = parse_date(m.group(1))
        hh, mm, ss = int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
        if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
            raise ParseError(f"시각 형식이 잘못되었습니다: {raw!r}")
        return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=KST).astimezone(UTC)
    d = parse_date(s)
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(UTC)


def parse_int(raw: str) -> int:
    s = raw.strip().replace(",", "").replace("개", "").replace("社", "").replace("명", "")
    if not re.fullmatch(r"\d+", s):
        raise ParseError(f"정수가 아닙니다: {raw!r}")
    return int(s)


def parse_text(raw: str, max_len: int) -> str:
    s = raw.strip()
    if len(s) > max_len:
        raise ParseError(f"글자 수가 너무 깁니다(최대 {max_len}자).")
    return s


def parse_enum(raw: str, synonyms: dict[str, str]) -> str:
    key = raw.strip().replace(" ", "")
    for k, v in synonyms.items():
        if key == k.replace(" ", "") or key == v:
            return v
    raise ParseError(f"알 수 없는 값입니다: {raw!r} (허용: {', '.join(sorted(set(synonyms)))})")
