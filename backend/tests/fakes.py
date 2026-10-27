"""data.go.kr 가짜 응답(httpx.MockTransport). 실제 응답 구조는 미검증이며 2차 출처의 형식을 따른다."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx


def ok(items: list[dict], total: int | None = None, page_no: int = 1, rows: int = 100) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {"items": items, "totalCount": len(items) if total is None else total, "pageNo": page_no, "numOfRows": rows},
        }
    }


def error(code: str, msg: str = "오류") -> dict:
    return {"response": {"header": {"resultCode": code, "resultMsg": msg}}}


AUTH_XML = (
    "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
    "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>"
    "</cmmMsgHeader></OpenAPI_ServiceResponse>"
)


class FakeApi:
    """오퍼레이션별 응답 함수를 등록해 쓰는 가짜 서버. 받은 요청을 기록한다."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response | dict]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, operation: str, handler: Callable[[httpx.Request], httpx.Response | dict] | dict) -> None:
        self.routes[operation] = handler if callable(handler) else (lambda _r, h=handler: h)

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            op = request.url.path.rsplit("/", 1)[-1]
            if op not in self.routes:
                return httpx.Response(404, text="no route")
            out = self.routes[op](request)
            if isinstance(out, httpx.Response):
                return out
            return httpx.Response(200, text=json.dumps(out, ensure_ascii=False))

        return httpx.MockTransport(handle)
