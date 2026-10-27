"""명령줄 도구.

  python -m app.cli collect --op notice_list_construction --from 2024-06-01 --to 2024-06-30
  python -m app.cli collect --op prepar_construction --notice R24BK00000001
  python -m app.cli probe --notice R24BK00000001 --out ./probe_samples
  python -m app.cli ops

운영체제 스케줄러(cron, 작업 스케줄러)에 collect 명령을 등록해 정기 수집할 수 있다.
호출 한도는 DB 의 일일 카운터로 보호되므로 여러 번 실행해도 한도의 90% 에서 멈춘다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.connectors.client import ApiError, DataGoKrClient, mask_key
from app.connectors.specs import AWARD_FIELD_MAP, BASIS_FIELD_MAP, NOTICE_FIELD_MAP, OPERATIONS, Handler, QueryMode
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services import collection as svc
from app.services.quota import DEFAULT_DAILY_LIMITS, DailyQuota

EXPECTED_FIELDS = {
    Handler.NOTICE: {f for f, _ in NOTICE_FIELD_MAP.values()},
    Handler.BASIS: {f for f, _ in BASIS_FIELD_MAP.values()} | {"bidNtceNo", "bidNtceOrd"},
    Handler.AWARD: {f for f, _ in AWARD_FIELD_MAP.values()} | {"bidNtceNo", "bidNtceOrd", "sucsfbidRate", "rbidNo"},
    Handler.OPENING: {"bidNtceNo", "bidNtceOrd", "progrsDivCdNm", "prtcptCnum", "opengDt", "rbidNo"},
    Handler.PREPAR: {"bidNtceNo", "bidNtceOrd", "plnprc", "bssamt", "totRsrvtnPrceNum", "compnoRsrvtnPrceSno", "bsisPlnprc", "drwtYn"},
    Handler.BIDDER: {"bidNtceNo", "bidNtceOrd", "opengRank", "prcbdrNm", "prcbdrBizno", "bidprcAmt", "bidprcrt"},
}


def _key() -> str | None:
    k = get_settings().data_go_kr_service_key
    return k.get_secret_value() if k else None


def _limits() -> dict[str, int]:
    return {**DEFAULT_DAILY_LIMITS, **get_settings().api_daily_limits}


def cmd_ops(_: argparse.Namespace) -> int:
    for s in OPERATIONS.values():
        modes = ", ".join(sorted(s.inqry_div))
        print(f"{s.key:28} {s.operation:45} 근거={s.evidence:10} 조회기준={modes}")
    return 0


def cmd_collect(a: argparse.Namespace) -> int:
    req = svc.CollectionRequest(
        operation_key=a.op,
        mode=QueryMode.NOTICE_NUMBER if a.notice else QueryMode.DATE_RANGE,
        date_from=date.fromisoformat(a.date_from) if a.date_from else None,
        date_to=date.fromisoformat(a.date_to) if a.date_to else None,
        date_type=a.date_type,
        notice_number=a.notice,
        search=dict(kv.split("=", 1) for kv in a.search or []),
        max_pages=a.max_pages,
    )
    try:
        spec = svc.validate_request(req)
    except svc.CollectionRequestError as e:
        print(f"요청 오류: {e}", file=sys.stderr)
        return 2
    factory = get_session_factory()
    quota = DailyQuota(factory, spec.source_name, _limits().get(spec.source_name, 1000))
    with factory() as s:
        job = svc.run_collection(s, req, svc.default_client_factory(_key()), quota.check_and_increment)
        print(json.dumps({"job_id": job.id, "status": job.status.value, "requests": job.request_count,
                          "inserted": job.inserted_count, "updated": job.updated_count, "skipped": job.skipped_count,
                          "error": (job.error_summary or {}).get("error")}, ensure_ascii=False))
        return 0 if job.status.value in ("succeeded", "partial") else 1


def cmd_probe(a: argparse.Namespace) -> int:
    """오퍼레이션별로 1페이지(3행)만 호출해 실제 응답 필드와 프로그램이 기대하는 필드를 비교한다."""
    key = _key()
    out_dir = Path(a.out) if a.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    factory = get_session_factory()
    keys = a.ops or [k for k in OPERATIONS if k.endswith("_construction")] + ["bidders_completed", "open_std_notices"]
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=min(6, a.days))
    report = []
    for k in keys:
        spec = OPERATIONS[k]
        quota = DailyQuota(factory, spec.source_name, _limits().get(spec.source_name, 1000))
        if "notice" in spec.inqry_div and a.notice:
            params = {"inqryDiv": spec.inqry_div["notice"] or None, "bidNtceNo": a.notice}
        elif "posted" in spec.inqry_div or "opened" in spec.inqry_div:
            dt = "posted" if "posted" in spec.inqry_div else "opened"
            params = {"inqryDiv": spec.inqry_div[dt] or None,
                      spec.date_params[0]: datetime.combine(start, datetime.min.time()).strftime(spec.date_format),
                      spec.date_params[1]: datetime.combine(end, datetime.max.time()).strftime(spec.date_format)}
        else:
            report.append({"op": k, "skipped": "공고번호(--notice)가 필요합니다."})
            continue
        try:
            with DataGoKrClient(key, before_request=quota.check_and_increment, max_retries=1) as c:
                page = c.get_page(spec.url, {**params, "pageNo": 1, "numOfRows": 3})
        except ApiError as e:
            report.append({"op": k, "error": mask_key(str(e), key), "code": e.code})
            continue
        present = set().union(*(i.keys() for i in page.items)) if page.items else set()
        expected = EXPECTED_FIELDS[spec.handler]
        report.append({
            "op": k, "operation": spec.operation, "total_count": page.total_count, "items": len(page.items),
            "expected_missing": sorted(expected - present) if page.items else "응답 항목 없음(판단 불가)",
            "unmapped_fields": sorted(present - expected),
        })
        if out_dir and page.items:
            (out_dir / f"{k}.json").write_text(json.dumps(page.raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"probed_at": datetime.now(UTC).isoformat(), "results": report}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ops", help="수집 가능한 오퍼레이션 목록").set_defaults(fn=cmd_ops)
    c = sub.add_parser("collect", help="공식 API 수집 실행")
    c.add_argument("--op", required=True)
    c.add_argument("--from", dest="date_from")
    c.add_argument("--to", dest="date_to")
    c.add_argument("--date-type", default="posted", choices=["posted", "opened", "registered"])
    c.add_argument("--notice")
    c.add_argument("--search", nargs="*", help="예: bidNtceNm=도로 ntceInsttNm=○○시")
    c.add_argument("--max-pages", type=int, default=50)
    c.set_defaults(fn=cmd_collect)
    pr = sub.add_parser("probe", help="실제 API 응답 구조 점검")
    pr.add_argument("--ops", nargs="*")
    pr.add_argument("--notice")
    pr.add_argument("--days", type=int, default=3)
    pr.add_argument("--out")
    pr.set_defaults(fn=cmd_probe)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
