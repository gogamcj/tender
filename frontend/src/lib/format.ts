// 표시용 서식. 금액 문자열은 숫자로 바꾸지 않고 자릿수만 끊는다.

export function won(v: string | number | null | undefined, unit = "원"): string {
  if (v === null || v === undefined || v === "") return "-";
  const s = String(v);
  const m = /^(-?)(\d+)(\.\d+)?$/.exec(s);
  if (!m) return s;
  const [, sign, int, frac] = m;
  return `${sign}${int.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${frac ?? ""}${unit}`;
}

export function pct(v: string | number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || v === "") return "-";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  // 표시만 반올림한다(원값은 툴팁·표에 그대로).
  return `${n.toFixed(digits).replace(/\.?0+$/, "")}%`;
}

export function num(v: number | string | null | undefined, digits = 3): string {
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("ko-KR", { maximumFractionDigits: digits }) : String(v);
}

const KST = "Asia/Seoul";

export function dt(v: string | null | undefined): string {
  if (!v) return "-";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString("ko-KR", { timeZone: KST, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function day(v: string | null | undefined): string {
  if (!v) return "-";
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("ko-KR", { timeZone: KST });
}

/** 입력란의 "1,234,000" 을 서버로 보낼 정수 문자열로. 숫자가 아니면 null. */
export function parseWonInput(s: string): string | null {
  const t = s.replace(/[,\s원]/g, "");
  if (t === "") return null;
  return /^\d+$/.test(t) ? t.replace(/^0+(?=\d)/, "") : null;
}

export function parseRateInput(s: string): string | null {
  const t = s.replace(/[%\s]/g, "");
  if (t === "") return null;
  return /^-?\d+(\.\d+)?$/.test(t) ? t : null;
}

export const LABELS: Record<string, string> = {
  construction: "공사", service: "용역", goods: "물품", foreign: "외자", other: "기타",
  national: "국가기관", local: "지방자치단체", public_corp: "공기업·준정부기관",
  estimated_price: "예정가격", base_amount: "기초금액", presumed_price: "추정가격",
  actual: "확정", user_assumed: "사용자 가정", historical_estimate: "과거 기반 예상", scenario: "시나리오", unknown: "미상",
  pre_opening: "개찰 전", post_opening: "개찰 후", "*": "전체", any: "전체",
  confirmed: "확인", expected: "예상", unreviewed: "미검토", corrected: "수정", rejected: "기각",
  verified: "검증됨", unverified: "미검증", retired: "사용 중지",
  admin: "관리자", user: "일반", viewer: "조회 전용",
  committed: "저장 완료", rolled_back: "되돌림", succeeded: "성공", partial: "일부 실패", failed: "실패", running: "진행 중", quota_stopped: "한도 보호 중단", pending: "대기",
  pass: "통과", fail: "미달", undetermined: "판단 불가",
  assumption_based: "가정 기반 분석", insufficient_data: "자료 부족", observational: "관측 요약",
};

// 같은 영문 값이 맥락마다 뜻이 달라(예: partial, failed) 항목별 사전을 따로 둔다.
export const DATA_STATUS: Record<string, string> = {
  collected: "수집 완료", verified: "검증 완료", partial: "일부 항목 누락", duplicate_suspected: "중복 의심", source_mismatch: "원본과 불일치",
  revision_check_needed: "수정 공고 확인 필요", result_unconfirmed: "개찰 결과 미확인", excluded: "분석 제외",
};
export const OPENING_STATUS: Record<string, string> = { opened: "개찰 완료", awarded: "낙찰자 결정", failed: "유찰", rebid: "재입찰", unconfirmed: "결과 미확인" };
export const LOOKUP_STATUS: Record<string, string> = {
  found: "조회됨", not_queried: "아직 조회 안 함", out_of_period: "조회 기간 밖", out_of_scope: "API 제공 범위 밖",
  not_returned: "응답에 없음(없다는 뜻은 아님)", confirmed_absent: "없음 확인", source_error: "API 오류로 확인 못 함",
};
export const IMPORT_STATUS: Record<string, string> = {
  analyzing: "분석 중", mapping: "열 연결 대기", preview: "미리보기", committed: "저장 완료", cancelled: "취소", failed: "실패", rolled_back: "되돌림",
};
export const SOURCE_NAME: Record<string, string> = {
  g2b_bid_notice: "나라장터 입찰공고", g2b_scsbid: "나라장터 낙찰정보", g2b_open_std: "나라장터 개방표준", upload: "엑셀 업로드", manual: "직접 입력",
};
export const APPLY_STATUS: Record<string, string> = { applied: "반영", pending: "보류(확인 필요)", skipped: "건너뜀", unchanged: "변경 없음" };
export const PROFIT_STATUS: Record<string, string> = { computed: "계산됨", cost_incomplete: "원가 미완성", vat_unknown: "부가세 미확인", not_computed: "계산 안 함" };
export const EVIDENCE: Record<string, string> = { portal: "포털 문서로 확인", secondary: "보조 자료 기준(미검증)" };
export const RULE_MODULE: Record<string, string> = { simple_lower_limit: "기준가격 × 하한율", a_value_lower_limit: "A값 적용 하한율" };

// 공고 항목(DB 열) 이름
export const FIELD_LABEL: Record<string, string> = {
  notice_number: "공고번호", title: "공고명", agency_name: "공고기관", demand_agency_name: "수요기관", base_amount: "기초금액",
  presumed_price: "추정가격", estimated_price: "예정가격", lower_limit_rate: "낙찰하한율", a_value: "A값", bid_deadline: "입찰마감일시",
  opening_date: "개찰일시", contract_method: "계약방법", award_method: "낙찰자 결정방법", reserve_range: "예비가격 범위",
  reserve_range_begin_rate: "예비가격 범위 하한(%)", reserve_range_end_rate: "예비가격 범위 상한(%)", vat_included: "부가세 포함 여부",
  region_restriction: "지역제한", qualification: "참가자격",
};
/** PDF 등에서 온 참/거짓 값 표시 */
export const yesNo = (v: string | null | undefined) => (v === "True" || v === "true" ? "예(포함)" : v === "False" || v === "false" ? "아니오(별도)" : v);

/** 사전에 있으면 한글, 없으면 원래 값(빈 값은 "-"). */
export const ko = (dict: Record<string, string>, v: string | null | undefined) => (v ? dict[v] ?? v : "-");

export const label = (v: string | null | undefined) => (v ? LABELS[v] ?? v : "-");
