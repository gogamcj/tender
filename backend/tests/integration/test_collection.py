from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.connectors.client import DataGoKrClient
from app.connectors.specs import QueryMode
from app.db.enums import CollectionStatus, DataStatus, LookupStatus, OpeningStatus, PriceStatus, RateBasis
from app.db.models import (
    ApiCallCounter,
    BidCandidate,
    BidResult,
    NoticeChangeLog,
    NoticeRawRecord,
    ProcurementNotice,
    ReservePrice,
)
from app.services import collection as svc
from app.services.quota import DailyQuota
from tests.fakes import AUTH_XML, FakeApi, error, ok

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)


def notice_item(no="R24BK00000001", ord_="000", **kw):
    item = {
        "bidNtceNo": no, "bidNtceOrd": ord_, "bidNtceNm": "가상 도로 보수공사", "ntceInsttNm": "가상시", "dminsttNm": "가상시",
        "bidNtceDt": "2024-06-03 09:00:00", "bidClseDt": "2024-06-18 10:00:00", "opengDt": "2024-06-18 11:00:00",
        "presmptPrce": "136363636", "bidNtceDtlUrl": "https://example.invalid/n", "cntrctCnclsMthdNm": "제한경쟁",
    }
    item.update(kw)
    return item


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_client_factory(api: FakeApi):
    def _f(before):
        return DataGoKrClient("TESTKEY", transport=api.transport(), sleeper=lambda _s: None, min_interval=0, before_request=before)

    return _f


def run(session, factory, api, req, limit=1000):
    quota = DailyQuota(factory, svc.OPERATIONS[req.operation_key].source_name, limit, clock=lambda: NOW)
    return svc.run_collection(session, req, make_client_factory(api), quota.check_and_increment, now=NOW)


def date_req(op="notice_list_construction", **kw):
    return svc.CollectionRequest(operation_key=op, date_from=date(2024, 6, 1), date_to=date(2024, 6, 30), **kw)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_date_windows_split():
    w = svc.date_windows(date(2024, 1, 1), date(2024, 3, 5), 31)
    assert len(w) == 3
    assert w[0][0].strftime("%Y%m%d%H%M") == "202401010000"
    assert w[0][1].strftime("%Y%m%d%H%M") == "202401312359"
    assert w[-1][1].date() == date(2024, 3, 5)


def test_request_validation():
    with pytest.raises(svc.CollectionRequestError):
        svc.validate_request(svc.CollectionRequest(operation_key="nope"))
    with pytest.raises(svc.CollectionRequestError):
        svc.validate_request(svc.CollectionRequest(operation_key="notice_list_construction", date_from=date(2024, 2, 1), date_to=date(2024, 1, 1)))
    with pytest.raises(svc.CollectionRequestError):
        svc.validate_request(svc.CollectionRequest(operation_key="basis_construction", date_from=date(2024, 1, 1), date_to=date(2024, 1, 2)))
    with pytest.raises(svc.CollectionRequestError):
        svc.validate_request(date_req(search={"bidNtceNm": "도로"}))  # 기본 목록은 검색어 미지원
    svc.validate_request(date_req(op="notice_search_construction", search={"bidNtceNm": "도로"}))


def test_collect_notices_insert_then_skip_then_update(session, factory):
    api = FakeApi()
    items = [notice_item(), notice_item("R24BK00000002", opengDt="2099-01-01 11:00:00")]
    api.on("getBidPblancListInfoCnstwk", lambda r: ok(items))
    job = run(session, factory, api, date_req())
    assert job.status is CollectionStatus.SUCCEEDED
    assert (job.inserted_count, job.updated_count, job.skipped_count) == (2, 0, 0)
    q = api.requests[0].url.params
    assert q["inqryDiv"] == "1" and q["inqryBgnDt"] == "202406010000" and q["inqryEndDt"] == "202406302359"

    n1 = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "R24BK00000001"))
    assert n1.source_name == "g2b_bid_notice"
    assert n1.presumed_price == Decimal("136363636")
    assert n1.procurement_type == "construction"
    assert n1.announcement_date == date(2024, 6, 3)
    assert n1.opening_date == datetime(2024, 6, 18, 2, 0, tzinfo=UTC)  # KST 11:00
    assert n1.data_status is DataStatus.RESULT_UNCONFIRMED  # 개찰일 지남 + 결과 없음
    assert n1.base_amount is None  # 제공되지 않은 값은 채우지 않음
    n2 = session.scalar(select(ProcurementNotice).where(ProcurementNotice.notice_number == "R24BK00000002"))
    assert n2.data_status is DataStatus.COLLECTED
    assert count(session, NoticeRawRecord) == 2

    job2 = run(session, factory, api, date_req())  # 같은 응답 → 건너뜀
    assert (job2.inserted_count, job2.updated_count, job2.skipped_count) == (0, 0, 2)
    assert count(session, NoticeRawRecord) == 2

    items[0] = notice_item(presmptPrce="140000000")  # 공식 값 변경 → 반영 + 이력
    job3 = run(session, factory, api, date_req())
    assert job3.updated_count == 1
    session.expire_all()
    n1 = session.get(ProcurementNotice, n1.id)
    assert n1.presumed_price == Decimal("140000000")
    log = session.scalar(select(NoticeChangeLog).where(NoticeChangeLog.field_name == "presumed_price"))
    assert (log.old_value, log.new_value, log.applied) == ("136363636", "140000000", True)


def test_official_value_does_not_overwrite_user_upload(session, factory):
    session.add(ProcurementNotice(notice_number="R24BK00000001", notice_revision="000", title="사용자 입력", source_name="upload",
                                  presumed_price=Decimal("100")))
    session.commit()
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    job = run(session, factory, api, date_req())
    assert job.status is CollectionStatus.SUCCEEDED
    session.expire_all()
    n = session.scalar(select(ProcurementNotice))
    assert n.presumed_price == Decimal("100") and n.title == "사용자 입력"
    assert n.data_status is DataStatus.SOURCE_MISMATCH
    pending = list(session.scalars(select(NoticeChangeLog).where(NoticeChangeLog.applied.is_(False))))
    assert {p.field_name for p in pending} >= {"presumed_price", "title"}
    assert any("확인이 필요" in w for w in job.error_summary["warnings"])


def test_revision_creates_new_row_and_flags(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item(), notice_item(ord_="001", bidNtceNm="가상 도로 보수공사(정정)")]))
    run(session, factory, api, date_req())
    rows = list(session.scalars(select(ProcurementNotice).order_by(ProcurementNotice.notice_revision)))
    assert [r.notice_revision for r in rows] == ["000", "001"]
    assert [r.is_latest_revision for r in rows] == [False, True]
    assert rows[1].data_status is DataStatus.REVISION_CHECK_NEEDED


def test_results_award_prepar_bidders(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    run(session, factory, api, date_req())
    api.on("getBidPblancListInfoCnstwkBsisAmount", ok([{"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "bssamt": "150000000",
                                                        "rsrvtnPrceRngBgnRate": "-2", "rsrvtnPrceRngEndRate": "+2"}]))
    run(session, factory, api, svc.CollectionRequest(operation_key="basis_construction", mode=QueryMode.NOTICE_NUMBER, notice_number="R24BK00000001"))
    api.on("getScsbidListSttusCnstwk", ok([{"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "rbidNo": "000", "prtcptCnum": "212",
                                           "bidwinnrNm": "가상건설", "bidwinnrBizno": "0000000000", "sucsfbidAmt": "131086275",
                                           "sucsfbidRate": "87.83", "rlOpengDt": "2024-06-18 11:00:00"}]))
    job = run(session, factory, api, date_req(op="award_construction", date_type="opened"))
    assert job.status is CollectionStatus.SUCCEEDED, job.error_summary
    assert api.requests[-1].url.params["inqryDiv"] == "3"
    reserves = [{"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "plnprc": "149250000", "bssamt": "150000000",
                 "totRsrvtnPrceNum": "15", "compnoRsrvtnPrceSno": str(i), "bsisPlnprc": str(147000000 + i * 300000),
                 "drwtYn": "Y" if i in (2, 5, 7, 11) else "N"} for i in range(1, 16)]
    api.on("getOpengResultListInfoCnstwkPreparPcDetail", ok(reserves))
    run(session, factory, api, svc.CollectionRequest(operation_key="prepar_construction", mode=QueryMode.NOTICE_NUMBER, notice_number="R24BK00000001"))
    api.on("getOpengResultListInfoOpengCompt", ok([
        {"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "opengRank": "1", "prcbdrNm": "가상건설", "prcbdrBizno": "0000000000", "bidprcAmt": "131086275", "bidprcrt": "87.83"},
        {"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "opengRank": "2", "prcbdrNm": "가상토건", "prcbdrBizno": "1111111111", "bidprcAmt": "131200000", "bidprcrt": "87.90"},
    ]))
    run(session, factory, api, svc.CollectionRequest(operation_key="bidders_completed", mode=QueryMode.NOTICE_NUMBER, notice_number="R24BK00000001"))
    assert "inqryDiv" not in api.requests[-1].url.params

    session.expire_all()
    n = session.scalar(select(ProcurementNotice))
    assert n.base_amount == Decimal("150000000")
    assert n.reserve_range_begin_rate == Decimal("-2") and n.reserve_range_end_rate == Decimal("2")
    assert n.estimated_price == Decimal("149250000") and n.estimated_price_status is PriceStatus.ACTUAL
    res = session.scalar(select(BidResult))
    assert res.opening_status is OpeningStatus.AWARDED
    assert res.bid_count == 212 and res.winning_vendor_name == "가상건설"
    assert res.actual_sajeong_rate == Decimal("-0.500000")
    # 응답의 낙찰률은 기준 미확인이라 별도 보관, 낙찰률은 확정 예정가격으로 계산하고 기준을 기록
    assert res.external_metrics == {"sucsfbidRate": "87.83"}
    assert res.winning_rate == Decimal("87.830000") and res.winning_rate_basis is RateBasis.ESTIMATED_PRICE
    rp = list(session.scalars(select(ReservePrice).order_by(ReservePrice.seq)))
    assert len(rp) == 15 and sum(1 for r in rp if r.drawn) == 4
    cands = list(session.scalars(select(BidCandidate).order_by(BidCandidate.ranking)))
    assert [c.vendor_name for c in cands] == ["가상건설", "가상토건"]
    assert all(c.bid_rate is None for c in cands)  # 기준 미확인 투찰률은 저장하지 않음
    assert n.data_status is DataStatus.COLLECTED


def test_opening_failed_status_only_from_official_value(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    run(session, factory, api, date_req())
    api.on("getOpengResultListInfoCnstwk", ok([{"bidNtceNo": "R24BK00000001", "bidNtceOrd": "000", "progrsDivCdNm": "유찰", "prtcptCnum": "1"},
                                              {"bidNtceNo": "R24BK00000009", "bidNtceOrd": "000", "progrsDivCdNm": "이상한값", "bidNtceNm": "가상"}]))
    job = run(session, factory, api, date_req(op="opening_construction", date_type="opened"))
    session.expire_all()
    r1 = session.scalar(select(BidResult).join(ProcurementNotice).where(ProcurementNotice.notice_number == "R24BK00000001"))
    r9 = session.scalar(select(BidResult).join(ProcurementNotice).where(ProcurementNotice.notice_number == "R24BK00000009"))
    assert r1.opening_status is OpeningStatus.FAILED
    assert r9.opening_status is OpeningStatus.UNCONFIRMED
    assert any("알 수 없는 진행구분" in w for w in job.error_summary["warnings"])


def test_empty_result_lookup_is_not_returned_not_failed(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    run(session, factory, api, date_req())
    api.on("getScsbidListSttusCnstwk", ok([]))
    job = run(session, factory, api, svc.CollectionRequest(operation_key="award_construction", mode=QueryMode.NOTICE_NUMBER, notice_number="R24BK00000001"))
    assert job.status is CollectionStatus.SUCCEEDED
    res = session.scalar(select(BidResult))
    assert res.lookup_status is LookupStatus.NOT_RETURNED
    assert res.opening_status is OpeningStatus.UNCONFIRMED


def test_quota_protection_stops_collection(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", lambda r: ok([notice_item(f"N{r.url.params['pageNo']}")], total=5000, page_no=int(r.url.params["pageNo"]), rows=100))
    req = date_req()
    req.max_pages = 100
    # 한도 10 → 보호 한도 9회
    job = run(session, factory, api, req, limit=10)
    assert job.status is CollectionStatus.QUOTA_STOPPED
    assert len(api.requests) == 9
    assert job.inserted_count == 9  # 멈추기 전까지 받은 데이터는 보존
    assert count(session, ProcurementNotice) == 9
    counter = session.scalar(select(ApiCallCounter))
    assert counter.call_count == 9


def test_api_failure_keeps_existing_data(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    run(session, factory, api, date_req())
    api.on("getBidPblancListInfoCnstwk", lambda r: httpx.Response(200, text=AUTH_XML))
    job = run(session, factory, api, date_req())
    assert job.status is CollectionStatus.FAILED
    assert "30" in job.error_summary["error"]
    assert count(session, ProcurementNotice) == 1


def test_partial_when_error_mid_way(session, factory):
    api = FakeApi()

    def h(r):
        p = int(r.url.params["pageNo"])
        return ok([notice_item(f"P{p}")], total=300, page_no=p, rows=100) if p == 1 else error("07", "입력범위값 초과")

    api.on("getBidPblancListInfoCnstwk", h)
    job = run(session, factory, api, date_req())
    assert job.status is CollectionStatus.PARTIAL
    assert count(session, ProcurementNotice) == 1


def test_bad_item_does_not_stop_page(session, factory):
    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([{"bidNtceNm": "번호 없음"}, notice_item(presmptPrce="1.2억")]))
    job = run(session, factory, api, date_req())
    assert job.status is CollectionStatus.SUCCEEDED
    assert job.skipped_count == 1 and job.inserted_count == 1
    n = session.scalar(select(ProcurementNotice))
    assert n.presumed_price is None  # 해석 불가 값은 비움
    assert any("presmptPrce" in w for w in job.error_summary["warnings"])


def test_collections_api_runs_in_background(client, engine, monkeypatch):
    from app.api import collections as api_mod
    from app.db.session import get_session_factory

    api = FakeApi()
    api.on("getBidPblancListInfoCnstwk", ok([notice_item()]))
    client.app.dependency_overrides[api_mod.get_client_factory] = lambda: make_client_factory(api)
    client.app.dependency_overrides[get_session_factory] = lambda: sessionmaker(bind=engine, expire_on_commit=False)
    src = client.get("/api/collections/sources").json()
    assert any(o["key"] == "notice_list_construction" and o["evidence"] == "portal" for o in src["operations"])
    bad = client.post("/api/collections", json={"operation_key": "notice_list_construction"})
    assert bad.status_code == 400
    r = client.post("/api/collections", json={"operation_key": "notice_list_construction", "date_from": "2024-06-01", "date_to": "2024-06-30"})
    assert r.status_code == 202
    job = client.get(f"/api/collections/{r.json()['job_id']}").json()
    assert job["status"] == "succeeded" and job["inserted_count"] == 1
    assert client.get("/api/collections").json()[0]["id"] == job["id"]
    usage = client.get("/api/collections/sources").json()["usage_today"]
    assert any(u["source_name"] == "g2b_bid_notice" and u["used"] == 1 for u in usage)
