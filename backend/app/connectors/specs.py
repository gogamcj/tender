"""공식 API 오퍼레이션 명세(설정).

근거 수준(evidence)
- "portal": 공공데이터포털 상세 페이지에서 직접 확인(2026-10-27)
- "secondary": 공개 오픈소스 클라이언트(MIT, opendata-kr/narajangteo-*-mcp)의 구현에서 확인. 포털 참고문서(docx)와 실응답으로 재확인 필요
- "unverified": 일반적으로 알려진 이름이나 이 프로젝트에서 출처를 확인하지 못함

실제 응답 구조는 scripts/probe_api.py 로 사용자 인증키를 써서 점검한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

BID_NOTICE_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"  # portal
SCSBID_BASE = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"  # portal
OPEN_STD_BASE = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"  # portal

KIND_SUFFIX = {"construction": "Cnstwk", "service": "Servc", "goods": "Thng", "foreign": "Frgcpt"}
KIND_LABEL = {"construction": "공사", "service": "용역", "goods": "물품", "foreign": "외자"}


class Handler(StrEnum):
    NOTICE = "notice"  # 공고 기본정보
    BASIS = "basis"  # 기초금액·예비가격 범위
    AWARD = "award"  # 최종 낙찰자
    OPENING = "opening"  # 개찰 진행 상태
    PREPAR = "prepar"  # 복수예비가격 상세
    BIDDER = "bidder"  # 투찰업체별 결과


class QueryMode(StrEnum):
    DATE_RANGE = "date_range"
    NOTICE_NUMBER = "notice_number"


@dataclass(frozen=True)
class OperationSpec:
    key: str
    source_name: str
    label: str
    base_url: str
    operation: str
    handler: Handler
    procurement_type: str | None
    evidence: str
    # 조회 방식별 inqryDiv 값. 날짜 기준은 posted(공고게시)·opened(개찰)·registered(등록)
    inqry_div: dict[str, str] = field(default_factory=dict)
    date_params: tuple[str, str] = ("inqryBgnDt", "inqryEndDt")
    date_format: str = "%Y%m%d%H%M"
    max_window_days: int = 31
    search_params: tuple[str, ...] = ()  # 검색어 등 추가 파라미터(PPSSrch)
    num_of_rows: int = 100

    @property
    def url(self) -> str:
        return f"{self.base_url}/{self.operation}"

    def supports(self, mode: QueryMode, date_type: str | None = None) -> bool:
        if mode is QueryMode.NOTICE_NUMBER:
            return "notice" in self.inqry_div
        return (date_type or "posted") in self.inqry_div


def _build() -> dict[str, OperationSpec]:
    specs: list[OperationSpec] = []
    for ptype, sfx in KIND_SUFFIX.items():
        specs += [
            OperationSpec(
                key=f"notice_list_{ptype}",
                source_name="g2b_bid_notice",
                label=f"{KIND_LABEL[ptype]} 입찰공고 목록",
                base_url=BID_NOTICE_BASE,
                operation=f"getBidPblancListInfo{sfx}",
                handler=Handler.NOTICE,
                procurement_type=ptype,
                evidence="portal" if ptype == "construction" else "secondary",
                inqry_div={"posted": "1", "notice": "2"},
            ),
            OperationSpec(
                key=f"notice_search_{ptype}",
                source_name="g2b_bid_notice",
                label=f"{KIND_LABEL[ptype]} 입찰공고 검색",
                base_url=BID_NOTICE_BASE,
                operation=f"getBidPblancListInfo{sfx}PPSSrch",
                handler=Handler.NOTICE,
                procurement_type=ptype,
                evidence="secondary",
                inqry_div={"posted": "1"},
                search_params=("bidNtceNm", "ntceInsttNm", "dminsttNm", "prtcptLmtRgnNm", "indstrytyNm", "presmptPrceBgn", "presmptPrceEnd"),
            ),
            OperationSpec(
                key=f"award_{ptype}",
                source_name="g2b_scsbid",
                label=f"{KIND_LABEL[ptype]} 최종 낙찰자",
                base_url=SCSBID_BASE,
                operation=f"getScsbidListSttus{sfx}",
                handler=Handler.AWARD,
                procurement_type=ptype,
                evidence="portal" if ptype == "goods" else "secondary",
                inqry_div={"registered": "1", "posted": "2", "opened": "3", "notice": "4"},
            ),
            OperationSpec(
                key=f"opening_{ptype}",
                source_name="g2b_scsbid",
                label=f"{KIND_LABEL[ptype]} 개찰 결과 목록",
                base_url=SCSBID_BASE,
                operation=f"getOpengResultListInfo{sfx}",
                handler=Handler.OPENING,
                procurement_type=ptype,
                evidence="secondary",
                inqry_div={"registered": "1", "posted": "2", "opened": "3", "notice": "4"},
                num_of_rows=20,  # 응답이 무거워 큰 페이지는 타임아웃 사례가 보고됨
            ),
            OperationSpec(
                key=f"prepar_{ptype}",
                source_name="g2b_scsbid",
                label=f"{KIND_LABEL[ptype]} 복수예비가격 상세",
                base_url=SCSBID_BASE,
                operation=f"getOpengResultListInfo{sfx}PreparPcDetail",
                handler=Handler.PREPAR,
                procurement_type=ptype,
                evidence="secondary",
                inqry_div={"registered": "1", "notice": "2"},
            ),
        ]
    for ptype in ("construction", "service", "goods"):
        sfx = KIND_SUFFIX[ptype]
        specs.append(
            OperationSpec(
                key=f"basis_{ptype}",
                source_name="g2b_bid_notice",
                label=f"{KIND_LABEL[ptype]} 기초금액",
                base_url=BID_NOTICE_BASE,
                operation=f"getBidPblancListInfo{sfx}BsisAmount",
                handler=Handler.BASIS,
                procurement_type=ptype,
                evidence="secondary",
                inqry_div={"notice": "2"},
            )
        )
    specs.append(
        OperationSpec(
            key="bidders_completed",
            source_name="g2b_scsbid",
            label="개찰완료 투찰업체 목록",
            base_url=SCSBID_BASE,
            operation="getOpengResultListInfoOpengCompt",
            handler=Handler.BIDDER,
            procurement_type=None,
            evidence="secondary",
            inqry_div={"notice": ""},  # 공고번호만 전달(inqryDiv 없음)
        )
    )
    specs.append(
        OperationSpec(
            key="open_std_notices",
            source_name="g2b_open_std",
            label="개방표준 입찰공고",
            base_url=OPEN_STD_BASE,
            operation="getDataSetOpnStdBidPblancInfo",
            handler=Handler.NOTICE,
            procurement_type=None,
            evidence="portal",
            inqry_div={"posted": ""},
            date_params=("bidNtceBgnDt", "bidNtceEndDt"),
            max_window_days=7,  # 포털 공지: 조회기간 1개월 → 임시로 1주 단축
        )
    )
    return {s.key: s for s in specs}


OPERATIONS: dict[str, OperationSpec] = _build()
_LABEL_BY_OPERATION = {(s.source_name, s.operation): s.label for s in OPERATIONS.values()}


def operation_label(source_name: str, operation: str) -> str:
    """수집 이력 표시용 한글 이름. 모르는 오퍼레이션이면 원래 이름을 돌려준다."""
    return _LABEL_BY_OPERATION.get((source_name, operation), operation)

# 공식 API 가 제공하지 않는 값은 채우지 않는다. 아래 맵에 없는 필드는 None 으로 둔다.
# 값: (응답 필드명, 근거 수준)
NOTICE_FIELD_MAP: dict[str, tuple[str, str]] = {
    "notice_number": ("bidNtceNo", "secondary"),
    "notice_revision": ("bidNtceOrd", "secondary"),
    "title": ("bidNtceNm", "secondary"),
    "agency_code": ("ntceInsttCd", "unverified"),
    "agency_name": ("ntceInsttNm", "secondary"),
    "demand_agency_code": ("dminsttCd", "unverified"),
    "demand_agency_name": ("dminsttNm", "secondary"),
    "contract_method": ("cntrctCnclsMthdNm", "secondary"),
    "award_method": ("sucsfbidMthdNm", "unverified"),
    "region_name": ("prtcptLmtRgnNm", "secondary"),
    "industry_name": ("mainCnsttyNm", "unverified"),
    "announcement_date": ("bidNtceDt", "secondary"),
    "bid_deadline": ("bidClseDt", "secondary"),
    "opening_date": ("opengDt", "secondary"),
    "presumed_price": ("presmptPrce", "secondary"),
    "vat_amount": ("VAT", "unverified"),
    "lower_limit_rate": ("sucsfbidLwltRate", "unverified"),
    "notice_url": ("bidNtceDtlUrl", "secondary"),
}
BASIS_FIELD_MAP = {
    "base_amount": ("bssamt", "secondary"),
    "reserve_range_begin_rate": ("rsrvtnPrceRngBgnRate", "secondary"),
    "reserve_range_end_rate": ("rsrvtnPrceRngEndRate", "secondary"),
}
AWARD_FIELD_MAP = {
    "bid_count": ("prtcptCnum", "secondary"),
    "winning_vendor_name": ("bidwinnrNm", "secondary"),
    "winning_vendor_id": ("bidwinnrBizno", "secondary"),
    "winning_bid_amount": ("sucsfbidAmt", "secondary"),
    "opening_datetime": ("rlOpengDt", "secondary"),
}
# 응답의 낙찰률(sucsfbidRate)이 무엇을 기준으로 한 비율인지 확인되지 않았으므로 기본값은 None.
# 참고문서로 확인되면 "estimated_price" 등으로 설정한다. None 이면 원문 값은 external_metrics 에만 보관한다.
AWARD_RATE_FIELD = "sucsfbidRate"
AWARD_RATE_BASIS: str | None = None
OPENING_STATUS_MAP = {"개찰완료": "opened", "유찰": "failed", "재입찰": "rebid"}
