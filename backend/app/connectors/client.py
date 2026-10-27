"""공공데이터포털(data.go.kr) 공통 HTTP 클라이언트.

- 인증키는 서버 환경변수에서만 읽고, 로그·오류 메시지에는 가린 값만 남긴다.
- 요청 간 최소 간격(초당 호출 제한 보호), 타임아웃, 재시도(지수 백오프)를 적용한다.
- JSON 응답의 header.resultCode 와, 인증 오류 때 오는 XML(OpenAPI_ServiceResponse)을 모두 해석한다.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

# data.go.kr 공통 오류 코드(포털 상세 페이지 기재)
AUTH_CODES = {"20", "30", "31", "32", "33"}  # 권한 없음, 미등록 키, 기한 만료 등
QUOTA_CODES = {"22"}  # 일일 호출 한도 초과
RATE_CODES = {"23"}  # 초당 호출 한도 초과
NO_DATA_CODES = {"03"}  # 데이터 없음(일부 서비스)
SUCCESS_CODES = {"00", "0", "000"}


class ApiError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ApiAuthError(ApiError):
    pass


class ApiQuotaError(ApiError):
    pass


class ApiRateLimitError(ApiError):
    pass


class ApiInputError(ApiError):
    pass


class ApiResponseError(ApiError):
    """응답 형식이 예상과 다름(명세 변경 가능성)."""


def mask_key(text: str, key: str | None) -> str:
    if not text:
        return text
    if key:
        text = text.replace(key, "***")
        from urllib.parse import quote

        text = text.replace(quote(key, safe=""), "***")
    return re.sub(r"(serviceKey=)[^&\s]+", r"\1***", text, flags=re.IGNORECASE)


@dataclass
class Page:
    items: list[dict[str, Any]]
    total_count: int
    page_no: int
    num_of_rows: int
    raw: dict[str, Any]


@dataclass
class CallStats:
    request_count: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


def parse_response(resp: httpx.Response) -> Page:
    text = resp.text.strip()
    if text.startswith("<"):
        _raise_from_xml(text)
    if resp.status_code >= 500:
        raise ApiError(f"서버 오류 HTTP {resp.status_code}", code=str(resp.status_code), retryable=True)
    if resp.status_code >= 400:
        raise ApiError(f"요청 오류 HTTP {resp.status_code}", code=str(resp.status_code))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiResponseError("JSON 이 아닌 응답입니다.") from exc
    root = data.get("response") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        raise ApiResponseError("응답에 response 객체가 없습니다.")
    header = root.get("header") or {}
    code = str(header.get("resultCode", "")).strip()
    msg = str(header.get("resultMsg", "")).strip()
    if code in NO_DATA_CODES:
        return Page([], 0, 1, 0, data)
    if code not in SUCCESS_CODES:
        _raise_for_code(code, msg)
    body = root.get("body") or {}
    items = body.get("items")
    if items in (None, "", []):
        items_list: list = []
    elif isinstance(items, list):
        items_list = items
    elif isinstance(items, dict) and "item" in items:
        inner = items["item"]
        items_list = inner if isinstance(inner, list) else [inner]
    else:
        raise ApiResponseError("body.items 형식을 해석할 수 없습니다.")
    if not all(isinstance(i, dict) for i in items_list):
        raise ApiResponseError("items 원소가 객체가 아닙니다.")
    try:
        total = int(body.get("totalCount", len(items_list)))
        page_no = int(body.get("pageNo", 1))
        rows = int(body.get("numOfRows", len(items_list)))
    except (TypeError, ValueError) as exc:
        raise ApiResponseError("페이지 정보(totalCount/pageNo/numOfRows)를 해석할 수 없습니다.") from exc
    return Page(items_list, total, page_no, rows, data)


def _raise_for_code(code: str, msg: str) -> None:
    text = f"API 오류 {code}: {msg}"
    if code in AUTH_CODES:
        raise ApiAuthError(text, code=code)
    if code in QUOTA_CODES:
        raise ApiQuotaError(text, code=code)
    if code in RATE_CODES:
        raise ApiRateLimitError(text, code=code, retryable=True)
    if code in {"01", "02", "04", "05", "99"}:
        raise ApiError(text, code=code, retryable=True)  # 시스템 오류 계열: 재시도
    raise ApiInputError(text, code=code)  # 07(입력범위 초과) 등 요청 문제


def _raise_from_xml(text: str) -> None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ApiResponseError("XML 응답을 해석할 수 없습니다.") from exc
    code = (root.findtext(".//returnReasonCode") or root.findtext(".//resultCode") or "").strip()
    msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or root.findtext(".//resultMsg") or "").strip()
    _raise_for_code(code or "XML", msg or "XML 오류 응답")


Sleeper = Callable[[float], None]


class DataGoKrClient:
    def __init__(
        self,
        service_key: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        min_interval: float = 0.2,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        sleeper: Sleeper = time.sleep,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        if not service_key:
            raise ApiAuthError("공공데이터포털 인증키(BID_DATA_GO_KR_SERVICE_KEY)가 설정되어 있지 않습니다.")
        self._key = service_key
        self._http = httpx.Client(transport=transport, timeout=timeout)
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff = backoff_base
        self._sleep = sleeper
        self._last = 0.0
        self._before = before_request
        self.stats = CallStats()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DataGoKrClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    def get_page(self, url: str, params: dict[str, Any]) -> Page:
        query = {k: v for k, v in params.items() if v not in (None, "")}
        query.update({"serviceKey": self._key, "type": "json"})
        attempt = 0
        while True:
            if self._before is not None:
                self._before()  # 일일 한도 확인(초과 시 ApiQuotaError)
            self._throttle()
            self.stats.request_count += 1
            try:
                resp = self._http.get(url, params=query)
                return parse_response(resp)
            except httpx.TimeoutException as exc:
                err: ApiError = ApiError("응답 시간 초과", code="timeout", retryable=True)
                cause: BaseException = exc
            except httpx.TransportError as exc:
                err = ApiError(f"네트워크 오류: {type(exc).__name__}", code="network", retryable=True)
                cause = exc
            except ApiError as exc:
                err, cause = exc, exc
            message = mask_key(str(err), self._key)
            self.stats.errors.append(message)
            if not err.retryable or attempt >= self._max_retries:
                raise type(err)(message, code=err.code, retryable=err.retryable) from cause
            attempt += 1
            self.stats.retries += 1
            self._sleep(self._backoff * (2 ** (attempt - 1)))

    def iter_pages(self, url: str, params: dict[str, Any], *, num_of_rows: int = 100, max_pages: int = 500) -> Iterator[Page]:
        """totalCount 기준으로 끝까지 페이지를 넘긴다. 같은 페이지가 반복되면 중단한다."""
        page_no = 1
        seen_first: str | None = None
        while page_no <= max_pages:
            page = self.get_page(url, {**params, "pageNo": page_no, "numOfRows": num_of_rows})
            yield page
            if not page.items:
                return
            fingerprint = json.dumps(page.items[0], sort_keys=True, ensure_ascii=False)
            if page_no > 1 and fingerprint == seen_first:
                raise ApiResponseError("페이지를 넘겨도 같은 데이터가 반복됩니다(페이지 처리 이상).")
            if page_no == 1:
                seen_first = fingerprint
            if page_no * num_of_rows >= page.total_count:
                return
            page_no += 1
        raise ApiResponseError(f"최대 페이지 수({max_pages})를 넘었습니다. 조회 범위를 좁혀 주세요.")
