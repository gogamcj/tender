import httpx
import pytest

from app.connectors.client import (
    ApiAuthError,
    ApiInputError,
    ApiQuotaError,
    ApiRateLimitError,
    ApiResponseError,
    DataGoKrClient,
    mask_key,
    parse_response,
)
from tests.fakes import AUTH_XML, FakeApi, error, ok

KEY = "SECRET+KEY/=="
URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk"


def client(api: FakeApi, **kw) -> DataGoKrClient:
    sleeps: list[float] = []
    c = DataGoKrClient(KEY, transport=api.transport(), sleeper=sleeps.append, min_interval=0, **kw)
    c.sleeps = sleeps  # type: ignore[attr-defined]
    return c


def resp(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body)


def test_parse_items_list_and_item_dict_forms():
    import json

    a = parse_response(resp(json.dumps(ok([{"bidNtceNo": "1"}]))))
    assert a.items == [{"bidNtceNo": "1"}] and a.total_count == 1
    b = parse_response(resp(json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"bidNtceNo": "2"}}, "totalCount": 1}}})))
    assert b.items == [{"bidNtceNo": "2"}]
    c = parse_response(resp(json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}})))
    assert c.items == []


@pytest.mark.parametrize(
    ("body", "exc"),
    [
        (AUTH_XML, ApiAuthError),
        ('{"response":{"header":{"resultCode":"22","resultMsg":"LIMITED"}}}', ApiQuotaError),
        ('{"response":{"header":{"resultCode":"23"}}}', ApiRateLimitError),
        ('{"response":{"header":{"resultCode":"07","resultMsg":"입력범위값 초과"}}}', ApiInputError),
        ("not json", ApiResponseError),
        ('{"foo": 1}', ApiResponseError),
        ('{"response":{"header":{"resultCode":"00"},"body":{"items":[1,2]}}}', ApiResponseError),
        ("<broken", ApiResponseError),
    ],
)
def test_error_classification(body, exc):
    with pytest.raises(exc):
        parse_response(resp(body))


def test_no_data_code_is_empty_page():
    import json

    assert parse_response(resp(json.dumps(error("03", "NODATA")))).items == []


def test_missing_key_rejected():
    with pytest.raises(ApiAuthError):
        DataGoKrClient(None)


def test_key_and_type_sent_and_none_params_dropped():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([]))
    with client(api) as c:
        c.get_page(URL, {"inqryDiv": "1", "bidNtceNo": None, "pageNo": 1})
    q = api.requests[0].url.params
    assert q["serviceKey"] == KEY and q["type"] == "json" and "bidNtceNo" not in q


def test_retry_on_server_error_then_success():
    api = FakeApi()
    calls = {"n": 0}

    def h(_):
        calls["n"] += 1
        return httpx.Response(503, text="{}") if calls["n"] < 3 else ok([{"a": 1}])

    api.on("getBidPblancListInfoCnstwk", h)
    with client(api, backoff_base=1.0) as c:
        page = c.get_page(URL, {})
        assert page.items == [{"a": 1}]
        assert c.stats.retries == 2
        assert c.sleeps == [1.0, 2.0]  # 지수 백오프


def test_retry_on_rate_limit_and_timeout():
    api = FakeApi()
    seq = iter(["timeout", "rate", "ok"])

    def h(req):
        s = next(seq)
        if s == "timeout":
            raise httpx.ReadTimeout("t", request=req)
        if s == "rate":
            return error("23")
        return ok([])

    api.on("getBidPblancListInfoCnstwk", h)
    with client(api) as c:
        c.get_page(URL, {})
        assert c.stats.request_count == 3


def test_retries_exhausted_and_key_masked_in_errors():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", lambda r: (_ for _ in ()).throw(httpx.ConnectError(f"fail {r.url}", request=r)))
    with client(api, max_retries=2) as c:
        with pytest.raises(Exception) as e:
            c.get_page(URL, {})
        assert c.stats.request_count == 3
        assert KEY not in str(e.value)
        assert all(KEY not in m for m in c.stats.errors)


def test_auth_error_not_retried():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", lambda r: httpx.Response(200, text=AUTH_XML))
    with client(api) as c:
        with pytest.raises(ApiAuthError):
            c.get_page(URL, {})
        assert c.stats.request_count == 1


def test_pagination_reads_all_pages():
    api = FakeApi()

    def h(req):
        p = int(req.url.params["pageNo"])
        items = [{"bidNtceNo": f"N{(p - 1) * 2 + i}"} for i in range(2) if (p - 1) * 2 + i < 5]
        return ok(items, total=5, page_no=p, rows=2)

    api.on("getBidPblancListInfoCnstwk", h)
    with client(api) as c:
        pages = list(c.iter_pages(URL, {}, num_of_rows=2))
    assert [len(p.items) for p in pages] == [2, 2, 1]
    assert [i["bidNtceNo"] for p in pages for i in p.items] == [f"N{i}" for i in range(5)]


def test_pagination_detects_repeating_pages():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", lambda r: ok([{"bidNtceNo": "SAME"}, {"bidNtceNo": "X"}], total=10, rows=2))
    with client(api) as c, pytest.raises(ApiResponseError):
        list(c.iter_pages(URL, {}, num_of_rows=2))


def test_pagination_max_pages_guard():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", lambda r: ok([{"n": r.url.params["pageNo"]}], total=1000, rows=1))
    with client(api) as c, pytest.raises(ApiResponseError):
        list(c.iter_pages(URL, {}, num_of_rows=1, max_pages=3))


def test_before_request_hook_can_stop():
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([]))

    def stop():
        raise ApiQuotaError("stop", code="local_quota")

    with client(api, before_request=stop) as c, pytest.raises(ApiQuotaError):
        c.get_page(URL, {})
    assert api.requests == []


def test_mask_key_variants():
    assert mask_key("https://x?serviceKey=abc%2B&x=1", None) == "https://x?serviceKey=***&x=1"
    assert "SECRET" not in mask_key("err SECRET+KEY/== here", KEY)
