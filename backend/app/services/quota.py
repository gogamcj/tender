"""API 일일 호출 한도 보호.

호출 직전에 오늘(한국 날짜) 호출 수를 확인하고 늘린다. 카운트는 별도 트랜잭션으로 즉시 저장해
수집 작업이 중간에 실패해도 사용한 호출 수가 사라지지 않게 한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.client import ApiQuotaError
from app.db.models import ApiCallCounter
from app.importers.parsing import KST

# 공공데이터포털 개발계정 기본 트래픽(포털 상세 페이지 기재). 운영계정 승인 후 환경변수로 늘린다.
DEFAULT_DAILY_LIMITS = {"g2b_bid_notice": 1000, "g2b_scsbid": 1000, "g2b_open_std": 10000}
SAFETY_RATIO = 0.9


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(KST).date()


class DailyQuota:
    def __init__(self, factory: sessionmaker[Session], source_name: str, limit: int, *, safety_ratio: float = SAFETY_RATIO, clock=None) -> None:
        self._factory = factory
        self.source_name = source_name
        self.limit = limit
        self.cap = int(limit * safety_ratio)
        self._clock = clock or (lambda: datetime.now(UTC))

    def used(self) -> int:
        with self._factory() as s:
            row = s.get(ApiCallCounter, (self.source_name, today_kst(self._clock())))
            return row.call_count if row else 0

    def check_and_increment(self) -> None:
        with self._factory() as s, s.begin():
            key = (self.source_name, today_kst(self._clock()))
            row = s.get(ApiCallCounter, key, with_for_update=True)
            if row is None:
                row = ApiCallCounter(source_name=key[0], call_date=key[1], call_count=0)
                s.add(row)
            if row.call_count >= self.cap:
                raise ApiQuotaError(
                    f"오늘 호출 수가 보호 한도({self.cap}/{self.limit})에 도달해 수집을 멈췄습니다. 내일 다시 시도하세요.",
                    code="local_quota",
                )
            row.call_count += 1


def usage_today(session: Session, limits: dict[str, int]) -> list[dict]:
    today = today_kst()
    rows = {r.source_name: r.call_count for r in session.scalars(select(ApiCallCounter).where(ApiCallCounter.call_date == today))}
    return [
        {"source_name": name, "date": today.isoformat(), "used": rows.get(name, 0), "limit": limit, "protect_at": int(limit * SAFETY_RATIO)}
        for name, limit in limits.items()
    ]
