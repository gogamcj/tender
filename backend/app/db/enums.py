"""DB 에 저장하는 상태값. 값은 영문 코드, 화면 표시는 LABELS 의 한국어를 쓴다."""

from enum import StrEnum

from app.engines.calc import PriceStatus, RateBasis
from app.engines.rules import AuthorityType, ProcurementCategory, VerificationStatus

__all__ = [
    "AuthorityType",
    "CollectionStatus",
    "DataStatus",
    "ImportStatus",
    "LinkSource",
    "LookupStatus",
    "NoticePhase",
    "OpeningStatus",
    "PriceStatus",
    "ProcurementCategory",
    "RateBasis",
    "ReviewStatus",
    "ScoreStatus",
    "UserRole",
    "VerificationStatus",
    "LABELS",
]


class DataStatus(StrEnum):
    COLLECTED = "collected"  # 수집 완료
    VERIFIED = "verified"  # 검증 완료
    PARTIAL = "partial"  # 일부 항목 누락
    DUPLICATE_SUSPECTED = "duplicate_suspected"  # 중복 의심
    SOURCE_MISMATCH = "source_mismatch"  # 원본과 불일치
    REVISION_CHECK_NEEDED = "revision_check_needed"  # 수정 공고 확인 필요
    RESULT_UNCONFIRMED = "result_unconfirmed"  # 개찰 결과 미확인
    EXCLUDED = "excluded"  # 분석 제외


class NoticePhase(StrEnum):
    PRE_OPENING = "pre_opening"  # 개찰 전
    POST_OPENING = "post_opening"  # 개찰 후


class OpeningStatus(StrEnum):
    OPENED = "opened"  # 개찰 완료(낙찰자 결정 포함 여부는 winning_* 로 판단)
    AWARDED = "awarded"  # 낙찰자 결정
    FAILED = "failed"  # 유찰(공식 결과로 확인된 경우에만)
    REBID = "rebid"  # 재입찰
    UNCONFIRMED = "unconfirmed"  # 결과 미확인 — 유찰로 간주하지 않음


class LookupStatus(StrEnum):
    """API 에서 결과가 조회되지 않은 이유를 구분한다."""

    FOUND = "found"
    NOT_QUERIED = "not_queried"  # 아직 조회하지 않음
    OUT_OF_PERIOD = "out_of_period"  # 조회 기간 밖
    OUT_OF_SCOPE = "out_of_scope"  # 공급 범위 밖(해당 API 가 다루지 않는 기관·유형)
    CONFIRMED_ABSENT = "confirmed_absent"  # 공식적으로 존재하지 않음이 확인됨
    SOURCE_ERROR = "source_error"  # API 오류로 확인 못 함


class ImportStatus(StrEnum):
    ANALYZING = "analyzing"
    MAPPING = "mapping"
    PREVIEW = "preview"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class CollectionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    QUOTA_STOPPED = "quota_stopped"  # 호출 한도 보호로 중단


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ScoreStatus(StrEnum):
    CONFIRMED = "confirmed"  # 확인된 점수
    EXPECTED = "expected"  # 예상 점수
    UNKNOWN = "unknown"  # 미확인


class LinkSource(StrEnum):
    AUTO = "auto"
    USER = "user"


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


LABELS: dict[str, str] = {
    DataStatus.COLLECTED: "수집 완료",
    DataStatus.VERIFIED: "검증 완료",
    DataStatus.PARTIAL: "일부 항목 누락",
    DataStatus.DUPLICATE_SUSPECTED: "중복 의심",
    DataStatus.SOURCE_MISMATCH: "원본과 불일치",
    DataStatus.REVISION_CHECK_NEEDED: "수정 공고 확인 필요",
    DataStatus.RESULT_UNCONFIRMED: "개찰 결과 미확인",
    DataStatus.EXCLUDED: "분석 제외",
    NoticePhase.PRE_OPENING: "개찰 전",
    NoticePhase.POST_OPENING: "개찰 후",
    OpeningStatus.OPENED: "개찰 완료",
    OpeningStatus.AWARDED: "낙찰자 결정",
    OpeningStatus.FAILED: "유찰",
    OpeningStatus.REBID: "재입찰",
    OpeningStatus.UNCONFIRMED: "결과 미확인",
    PriceStatus.ACTUAL: "실제 확정 예정가격",
    PriceStatus.USER_ASSUMED: "사용자 가정값",
    PriceStatus.HISTORICAL_ESTIMATE: "과거 데이터 기반 예상값",
    PriceStatus.SCENARIO: "통계적 시나리오 값",
    PriceStatus.UNKNOWN: "미상",
    ScoreStatus.CONFIRMED: "확인된 점수",
    ScoreStatus.EXPECTED: "예상 점수",
    ScoreStatus.UNKNOWN: "미확인 점수",
}
