"""공식 API 자동 수집.

수집 원칙
- 원본 응답 항목을 그대로 notice_raw_records 에 보존하고, 같은 원본이 다시 오면 건너뛴다.
- 같은 출처가 보낸 새 값은 반영하되 필드별 변경 이력을 남긴다.
- 사용자가 업로드·입력한 공고와 공식 값이 다르면 덮어쓰지 않고 '원본과 불일치'로 표시해 확인하게 한다.
- 결과를 조회했는데 응답에 없으면 '응답 없음'으로 기록한다(유찰이나 부존재로 간주하지 않음).
- API 장애는 수집 작업만 실패시키며, 이미 저장된 데이터는 페이지 단위로 커밋되어 보존된다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.client import ApiError, ApiQuotaError, DataGoKrClient
from app.connectors.mappers import map_award, map_basis, map_bidder, map_notice, map_opening, map_prepar, notice_key, rebid_number
from app.connectors.specs import OPERATIONS, Handler, OperationSpec, QueryMode
from app.db.enums import CollectionStatus, DataStatus, LookupStatus, NoticePhase, OpeningStatus, PriceStatus, RateBasis
from app.db.models import BidCandidate, BidResult, DataCollectionJob, NoticeChangeLog, NoticeRawRecord, ProcurementNotice, ReservePrice
from app.engines.calc import CalcInputError, sajeong_rate
from app.importers.parsing import KST
from app.importers.validate import FieldDiff

from . import notices as notice_service

USER_SOURCES = {"upload", "manual"}
_Q = Decimal("0.000001")

ClientFactory = Callable[[Callable[[], None]], DataGoKrClient]


@dataclass
class CollectionRequest:
    operation_key: str
    mode: QueryMode = QueryMode.DATE_RANGE
    date_from: date | None = None
    date_to: date | None = None
    date_type: str = "posted"  # posted / opened / registered
    notice_number: str | None = None
    search: dict[str, str] = field(default_factory=dict)
    max_pages: int = 50

    def to_dict(self) -> dict:
        return {
            "operation_key": self.operation_key,
            "mode": self.mode.value,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "date_type": self.date_type,
            "notice_number": self.notice_number,
            "search": self.search,
            "max_pages": self.max_pages,
        }


class CollectionRequestError(ValueError):
    pass


def validate_request(req: CollectionRequest) -> OperationSpec:
    spec = OPERATIONS.get(req.operation_key)
    if spec is None:
        raise CollectionRequestError(f"알 수 없는 수집 대상: {req.operation_key}")
    if req.mode is QueryMode.NOTICE_NUMBER:
        if not req.notice_number:
            raise CollectionRequestError("공고번호를 입력하세요.")
        if not spec.supports(QueryMode.NOTICE_NUMBER):
            raise CollectionRequestError(f"{spec.label} 은(는) 공고번호 조회를 지원하지 않습니다.")
    else:
        if not (req.date_from and req.date_to):
            raise CollectionRequestError("조회 시작일과 종료일을 입력하세요.")
        if req.date_from > req.date_to:
            raise CollectionRequestError("시작일이 종료일보다 늦습니다.")
        if (req.date_to - req.date_from).days > 366:
            raise CollectionRequestError("한 번에 1년을 넘는 기간은 수집할 수 없습니다. 기간을 나눠 주세요.")
        if not spec.supports(QueryMode.DATE_RANGE, req.date_type):
            raise CollectionRequestError(f"{spec.label} 은(는) '{req.date_type}' 기준 기간 조회를 지원하지 않습니다.")
    unknown = set(req.search) - set(spec.search_params)
    if unknown:
        raise CollectionRequestError(f"{spec.label} 에서 쓸 수 없는 검색 조건: {', '.join(sorted(unknown))}")
    return spec


def date_windows(start: date, end: date, max_days: int) -> list[tuple[datetime, datetime]]:
    """[start, end] 를 max_days 일 이하 구간으로 나눈다. 각 구간은 KST 00:00 ~ 23:59."""
    out = []
    cur = start
    while cur <= end:
        last = min(end, cur + timedelta(days=max_days - 1))
        out.append((datetime.combine(cur, time(0, 0), KST), datetime.combine(last, time(23, 59), KST)))
        cur = last + timedelta(days=1)
    return out


def _payload_hash(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _fmt(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime | date):
        return v.isoformat()
    return str(v.value if hasattr(v, "value") else v)


@dataclass
class _Ctx:
    session: Session
    job: DataCollectionJob
    spec: OperationSpec
    now: datetime
    counts: dict[str, int]
    warnings: list[str]

    def warn(self, text: str) -> None:
        if len(self.warnings) < 200:
            self.warnings.append(text)


def _save_raw(ctx: _Ctx, item: dict, notice_id: int | None, result_id: int | None, kind: str) -> bool:
    """원본 저장. 같은 출처·레코드·내용이 이미 있으면 False."""
    no, ord_ = notice_key(item)
    record_id = f"{no}-{ord_}-{rebid_number(item)}-{item.get('compnoRsrvtnPrceSno') or item.get('opengRank') or ''}"
    h = _payload_hash(item)
    exists = ctx.session.scalar(
        select(NoticeRawRecord.id).where(
            NoticeRawRecord.source_name == ctx.spec.source_name,
            NoticeRawRecord.record_kind == kind,
            NoticeRawRecord.source_record_id == record_id,
            NoticeRawRecord.payload_hash == h,
        )
    )
    if exists:
        return False
    ctx.session.add(
        NoticeRawRecord(
            notice_id=notice_id, result_id=result_id, source_name=ctx.spec.source_name, source_record_id=record_id,
            record_kind=kind, payload={"operation": ctx.spec.operation, "item": item}, payload_hash=h,
            collection_job_id=ctx.job.id,
        )
    )
    return True


def _merge_notice_values(ctx: _Ctx, notice: ProcurementNotice, values: dict[str, Any]) -> str:
    """기존 공고에 공식 값을 반영. 반환: updated / unchanged / conflict"""
    current = notice_service.existing_values(notice)
    diffs = []
    for key, new in values.items():
        if new is None or key in {"notice_number", "notice_revision"} or not hasattr(notice, key):
            continue
        old = current.get(key, getattr(notice, key))
        if _fmt(old) != _fmt(new):
            diffs.append(FieldDiff(key, key, _fmt(old), _fmt(new)))
    if not diffs:
        return "unchanged"
    if notice.source_name in USER_SOURCES:
        for d in diffs:
            ctx.session.add(
                NoticeChangeLog(notice_id=notice.id, field_name=d.field, old_value=d.old, new_value=d.new,
                                change_source=f"collection:{ctx.job.id}", applied=False)
            )
        notice.data_status = DataStatus.SOURCE_MISMATCH
        ctx.warn(f"{notice.notice_number}-{notice.notice_revision}: 사용자 자료와 공식 값이 달라 확인이 필요합니다({', '.join(d.field for d in diffs)}).")
        return "conflict"
    notice_service.apply_diffs(ctx.session, notice, diffs, values, change_source=f"collection:{ctx.job.id}")
    return "updated"


def _phase_and_status(values: dict[str, Any], now: datetime, has_result: bool, missing_required: bool) -> tuple[NoticePhase, DataStatus]:
    opening = values.get("opening_date")
    phase = NoticePhase.POST_OPENING if has_result or (opening is not None and opening <= now) else NoticePhase.PRE_OPENING
    if missing_required:
        status = DataStatus.PARTIAL
    elif values.get("notice_revision") not in (None, "000", "00", "0"):
        status = DataStatus.REVISION_CHECK_NEEDED
    elif phase is NoticePhase.POST_OPENING and not has_result:
        status = DataStatus.RESULT_UNCONFIRMED
    else:
        status = DataStatus.COLLECTED
    return phase, status


def _handle_notice(ctx: _Ctx, item: dict) -> str:
    mapped = map_notice(item, ctx.spec.procurement_type)
    v = mapped.values
    for w in mapped.warnings:
        ctx.warn(f"{v.get('notice_number')}: {w}")
    if not v.get("notice_number"):
        ctx.warn("공고번호가 없는 항목을 건너뜁니다.")
        return "skipped"
    existing = notice_service.find_notice(ctx.session, v["notice_number"], v["notice_revision"])
    if existing is None:
        phase, status = _phase_and_status(v, ctx.now, False, not v.get("title"))
        v["title"] = v.get("title") or "(공고명 미제공)"
        notice = notice_service.create_notice(
            ctx.session, v, source_name=ctx.spec.source_name, data_status=status, phase=phase, has_result=False
        )
        _save_raw(ctx, item, notice.id, None, "notice")
        return "inserted"
    if not _save_raw(ctx, item, existing.id, None, "notice"):
        return "skipped"
    outcome = _merge_notice_values(ctx, existing, {k: val for k, val in v.items() if k != "procurement_type" or existing.procurement_type is None})
    return {"updated": "updated", "unchanged": "skipped", "conflict": "skipped"}[outcome]


def _find_for_result(ctx: _Ctx, item: dict, *, create_minimal: bool) -> ProcurementNotice | None:
    no, ord_ = notice_key(item)
    if not no:
        return None
    n = notice_service.find_notice(ctx.session, no, ord_)
    if n is None and create_minimal and item.get("bidNtceNm"):
        values = {"notice_number": no, "notice_revision": ord_, "title": str(item["bidNtceNm"]),
                  "demand_agency_name": item.get("dminsttNm") or None, "agency_name": item.get("ntceInsttNm") or None,
                  "procurement_type": ctx.spec.procurement_type}
        n = notice_service.create_notice(
            ctx.session, values, source_name=ctx.spec.source_name, data_status=DataStatus.PARTIAL,
            phase=NoticePhase.POST_OPENING, has_result=False,
        )
        ctx.counts["inserted"] += 1
    return n


def _result_for(ctx: _Ctx, notice: ProcurementNotice, rebid: int) -> BidResult:
    res = ctx.session.scalar(
        select(BidResult).where(
            BidResult.notice_id == notice.id, BidResult.source_name == ctx.spec.source_name, BidResult.rebid_number == rebid
        )
    )
    if res is None:
        res = BidResult(notice_id=notice.id, source_name=ctx.spec.source_name, rebid_number=rebid)
        ctx.session.add(res)
        ctx.session.flush()
    return res


def _set_result(ctx: _Ctx, notice: ProcurementNotice, res: BidResult, values: dict[str, Any]) -> bool:
    changed = False
    for key, val in values.items():
        if val is None or not hasattr(res, key) or key == "rebid_number":
            continue
        if key == "opening_status":
            val = OpeningStatus(val)
            # 공식 결과가 이미 '낙찰자 결정'이면 개찰 목록의 '개찰완료'로 낮추지 않는다.
            if res.opening_status is OpeningStatus.AWARDED and val is OpeningStatus.OPENED:
                continue
        if key == "winning_rate_basis":
            val = RateBasis(val)
        old = getattr(res, key)
        if _fmt(old) != _fmt(val):
            if old is not None:
                ctx.session.add(NoticeChangeLog(notice_id=notice.id, field_name=f"result.{key}", old_value=_fmt(old),
                                                new_value=_fmt(val), change_source=f"collection:{ctx.job.id}", applied=True))
            setattr(res, key, val)
            changed = True
    res.lookup_status = LookupStatus.FOUND
    notice.phase = NoticePhase.POST_OPENING
    if notice.data_status is DataStatus.RESULT_UNCONFIRMED and res.opening_status is not OpeningStatus.UNCONFIRMED:
        notice.data_status = DataStatus.COLLECTED
    _derive_rate(res)
    ctx.session.flush()
    return changed


def _derive_rate(res: BidResult) -> None:
    """확정 예정가격과 낙찰금액이 모두 있으면 예정가격 대비 낙찰률을 계산한다(기준 명시)."""
    if res.winning_rate is None and res.winning_bid_amount and res.actual_estimated_price:
        res.winning_rate = (res.winning_bid_amount / res.actual_estimated_price * 100).quantize(_Q)
        res.winning_rate_basis = RateBasis.ESTIMATED_PRICE


def _handle_result(ctx: _Ctx, item: dict, mapped_values: dict[str, Any], kind: str) -> str:
    notice = _find_for_result(ctx, item, create_minimal=True)
    if notice is None:
        ctx.warn(f"{item.get('bidNtceNo')}: 공고가 없어 결과를 저장하지 못했습니다.")
        return "skipped"
    res = _result_for(ctx, notice, mapped_values.get("rebid_number", 0))
    new_raw = _save_raw(ctx, item, notice.id, res.id, kind)
    changed = _set_result(ctx, notice, res, mapped_values)
    if not new_raw and not changed:
        return "skipped"
    return "updated" if changed else "skipped"


def _handle_basis(ctx: _Ctx, item: dict) -> str:
    notice = _find_for_result(ctx, item, create_minimal=False)
    if notice is None:
        ctx.warn(f"{item.get('bidNtceNo')}: 공고를 먼저 수집해야 기초금액을 저장할 수 있습니다.")
        return "skipped"
    mapped = map_basis(item)
    for w in mapped.warnings:
        ctx.warn(f"{notice.notice_number}: {w}")
    _save_raw(ctx, item, notice.id, None, "basis")
    outcome = _merge_notice_values(ctx, notice, mapped.values)
    return "updated" if outcome == "updated" else "skipped"


def _handle_prepar(ctx: _Ctx, items: list[dict]) -> None:
    groups: dict[tuple[str | None, str, int], list[dict]] = {}
    for it in items:
        no, ord_ = notice_key(it)
        groups.setdefault((no, ord_, rebid_number(it)), []).append(it)
    for (no, _ord, rebid), group in groups.items():
        with ctx.session.begin_nested():
            notice = _find_for_result(ctx, group[0], create_minimal=False)
            if notice is None:
                ctx.warn(f"{no}: 공고가 없어 예비가격을 저장하지 못했습니다.")
                ctx.counts["skipped"] += 1
                continue
            res = _result_for(ctx, notice, rebid)
            fresh = [_save_raw(ctx, it, notice.id, res.id, "reserve_price") for it in group]
            if not any(fresh):
                ctx.counts["skipped"] += 1
                continue
            pg = map_prepar(group)
            for w in pg.warnings:
                ctx.warn(f"{no}: {w}")
            values: dict[str, Any] = {}
            if pg.estimated_price is not None:
                values["actual_estimated_price"] = pg.estimated_price
            if pg.base_amount is not None:
                values["actual_base_price"] = pg.base_amount
            if pg.estimated_price is not None and pg.base_amount is not None:
                try:
                    values["actual_sajeong_rate"] = sajeong_rate(pg.base_amount, pg.estimated_price).value
                except CalcInputError as e:
                    ctx.warn(f"{no}: 사정률 계산 불가 - {e.message}")
            _set_result(ctx, notice, res, values)
            if pg.estimated_price is not None and notice.estimated_price_status is not PriceStatus.ACTUAL:
                notice.estimated_price = pg.estimated_price
                notice.estimated_price_status = PriceStatus.ACTUAL
            if pg.reserves:
                for old in list(res.reserve_prices):
                    ctx.session.delete(old)
                ctx.session.flush()
                for r in pg.reserves:
                    ctx.session.add(ReservePrice(result_id=res.id, seq=r["seq"], amount=r["amount"], drawn=r["drawn"],
                                                 source_name=ctx.spec.source_name))
            ctx.session.flush()
            ctx.counts["updated"] += 1


def _handle_bidders(ctx: _Ctx, items: list[dict]) -> None:
    groups: dict[tuple[str | None, str, int], list[dict]] = {}
    for it in items:
        no, ord_ = notice_key(it)
        groups.setdefault((no, ord_, rebid_number(it)), []).append(it)
    for (no, _ord, rebid), group in groups.items():
        with ctx.session.begin_nested():
            notice = _find_for_result(ctx, group[0], create_minimal=False)
            if notice is None:
                ctx.warn(f"{no}: 공고가 없어 투찰업체 결과를 저장하지 못했습니다.")
                ctx.counts["skipped"] += 1
                continue
            res = _result_for(ctx, notice, rebid)
            fresh = [_save_raw(ctx, it, notice.id, res.id, "candidate") for it in group]
            if not any(fresh):
                ctx.counts["skipped"] += 1
                continue
            for old in [c for c in res.candidates if c.source_name == ctx.spec.source_name]:
                ctx.session.delete(old)
            ctx.session.flush()
            for it in group:
                m = map_bidder(it)
                for w in m.warnings:
                    ctx.warn(f"{no}: {w}")
                vals = {k: m.values[k] for k in ("vendor_name", "vendor_identifier", "ranking", "bid_amount", "qualification_status")}
                ctx.session.add(BidCandidate(result_id=res.id, source_name=ctx.spec.source_name, **vals))
            if res.bid_count is None:
                res.bid_count = len(group)
            res.lookup_status = LookupStatus.FOUND
            ctx.session.flush()
            ctx.counts["updated"] += 1


def _process_page(ctx: _Ctx, items: list[dict]) -> None:
    h = ctx.spec.handler
    if h is Handler.PREPAR:
        _handle_prepar(ctx, items)
        return
    if h is Handler.BIDDER:
        _handle_bidders(ctx, items)
        return
    for item in items:
        try:
            with ctx.session.begin_nested():
                if h is Handler.NOTICE:
                    outcome = _handle_notice(ctx, item)
                elif h is Handler.BASIS:
                    outcome = _handle_basis(ctx, item)
                elif h is Handler.AWARD:
                    m = map_award(item)
                    for w in m.warnings:
                        ctx.warn(f"{item.get('bidNtceNo')}: {w}")
                    outcome = _handle_result(ctx, item, m.values, "award")
                else:
                    m = map_opening(item)
                    for w in m.warnings:
                        ctx.warn(f"{item.get('bidNtceNo')}: {w}")
                    outcome = _handle_result(ctx, item, m.values, "opening")
        except Exception as exc:  # 항목 하나의 오류가 전체 수집을 멈추지 않게 한다
            ctx.warn(f"{item.get('bidNtceNo')}: 저장 실패 - {type(exc).__name__}: {exc}")
            outcome = "skipped"
        ctx.counts[outcome] += 1


def _mark_not_returned(ctx: _Ctx, notice_number: str) -> None:
    """공고번호로 결과를 조회했는데 응답이 비었을 때: 존재하지 않음이 아니라 '응답 없음'으로 기록."""
    if ctx.spec.handler not in (Handler.AWARD, Handler.OPENING, Handler.PREPAR, Handler.BIDDER):
        return
    for n in ctx.session.scalars(select(ProcurementNotice).where(ProcurementNotice.notice_number == notice_number)):
        if n.opening_date is not None and n.opening_date > ctx.now:
            ctx.warn(f"{notice_number}: 개찰 전이라 결과가 없습니다.")
            continue
        res = _result_for(ctx, n, 0)
        if res.lookup_status is not LookupStatus.FOUND:
            res.lookup_status = LookupStatus.NOT_RETURNED
            res.opening_status = OpeningStatus.UNCONFIRMED
        if n.data_status is DataStatus.COLLECTED:
            n.data_status = DataStatus.RESULT_UNCONFIRMED
    ctx.session.flush()


def run_collection(
    session: Session,
    req: CollectionRequest,
    client_factory: ClientFactory,
    quota_check: Callable[[], None],
    *,
    now: datetime | None = None,
    job: DataCollectionJob | None = None,
) -> DataCollectionJob:
    spec = validate_request(req)
    if job is None:
        job = DataCollectionJob(source_name=spec.source_name, operation=spec.operation, query_parameters=req.to_dict())
        session.add(job)
    job.status = CollectionStatus.RUNNING
    session.commit()
    ctx = _Ctx(session, job, spec, now or datetime.now(UTC),
               {"inserted": 0, "updated": 0, "skipped": 0}, [])
    total_returned = 0
    error: ApiError | None = None
    client = None
    try:
        client = client_factory(quota_check)
        if req.mode is QueryMode.NOTICE_NUMBER:
            div = spec.inqry_div["notice"]
            calls = [{"inqryDiv": div or None, "bidNtceNo": req.notice_number}]
        else:
            div = spec.inqry_div[req.date_type]
            calls = [
                {"inqryDiv": div or None, spec.date_params[0]: a.strftime(spec.date_format), spec.date_params[1]: b.strftime(spec.date_format), **req.search}
                for a, b in date_windows(req.date_from, req.date_to, spec.max_window_days)  # type: ignore[arg-type]
            ]
        for params in calls:
            for page in client.iter_pages(spec.url, params, num_of_rows=spec.num_of_rows, max_pages=req.max_pages):
                total_returned += len(page.items)
                _process_page(ctx, page.items)
                session.commit()  # 페이지 단위로 저장해 장애 시에도 받은 데이터는 보존
        if req.mode is QueryMode.NOTICE_NUMBER and total_returned == 0 and req.notice_number:
            _mark_not_returned(ctx, req.notice_number)
            session.commit()
    except ApiError as exc:
        session.rollback()
        error = exc
    finally:
        if client is not None:
            client.close()
    job = session.merge(job)
    job.finished_at = datetime.now(UTC)
    job.request_count = client.stats.request_count if client else 0
    job.inserted_count = ctx.counts["inserted"]
    job.updated_count = ctx.counts["updated"]
    job.skipped_count = ctx.counts["skipped"]
    summary: dict[str, Any] = {"returned_items": total_returned, "warnings": ctx.warnings}
    if client is not None and client.stats.errors:
        summary["request_errors"] = client.stats.errors[-20:]
    if error is not None:
        summary["error"] = str(error)
        summary["error_code"] = error.code
        if isinstance(error, ApiQuotaError):
            job.status = CollectionStatus.QUOTA_STOPPED
        elif total_returned > 0:
            job.status = CollectionStatus.PARTIAL
        else:
            job.status = CollectionStatus.FAILED
    else:
        job.status = CollectionStatus.SUCCEEDED
    job.error_summary = summary
    session.commit()
    return job


def default_client_factory(service_key: str | None) -> ClientFactory:
    def _make(before: Callable[[], None]) -> DataGoKrClient:
        return DataGoKrClient(service_key, before_request=before)

    return _make


def collect_in_new_session(factory: sessionmaker[Session], job_id: int, req: CollectionRequest, client_factory: ClientFactory, quota_check: Callable[[], None]) -> None:
    """백그라운드 실행용: 자체 세션으로 수집하고, 예상치 못한 오류도 작업 기록에 남긴다."""
    with factory() as s:
        job = s.get(DataCollectionJob, job_id)
        assert job is not None
        try:
            run_collection(s, req, client_factory, quota_check, job=job)
        except Exception as exc:  # pragma: no cover - 방어 코드
            s.rollback()
            job = s.get(DataCollectionJob, job_id)
            if job is not None:
                job.status = CollectionStatus.FAILED
                job.finished_at = datetime.now(UTC)
                job.error_summary = {"error": f"{type(exc).__name__}: {exc}"}
                s.commit()
