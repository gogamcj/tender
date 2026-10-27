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
  pre_opening: "개찰 전", post_opening: "개찰 후",
  confirmed: "확인", expected: "예상", unreviewed: "미검토", corrected: "수정", rejected: "기각",
  verified: "검증됨", unverified: "미검증", retired: "사용 중지",
  admin: "관리자", user: "일반", viewer: "조회 전용",
  committed: "저장 완료", rolled_back: "되돌림", succeeded: "성공", partial: "일부 실패", failed: "실패", running: "진행 중", quota_stopped: "한도 보호 중단", pending: "대기",
  pass: "통과", fail: "미달", undetermined: "판단 불가",
  assumption_based: "가정 기반 분석", insufficient_data: "자료 부족", observational: "관측 요약",
};

export const label = (v: string | null | undefined) => (v ? LABELS[v] ?? v : "-");
