import { parseWonInput } from "../lib/format";

export interface AF {
  period: string;
  as_of: string;
  procurement_type: string;
  issuing_authority_type: string;
  contract_method: string;
  award_method: string;
  agency_name: string;
  industry_name: string;
  region_name: string;
  amount_min: string;
  amount_max: string;
}

export const EMPTY_AF: AF = {
  period: "1y", as_of: "", procurement_type: "", issuing_authority_type: "", contract_method: "", award_method: "",
  agency_name: "", industry_name: "", region_name: "", amount_min: "", amount_max: "",
};

/** 서버 Filters 형식으로 변환. 빈 값은 보내지 않는다. */
export function toFilters(f: AF): Record<string, unknown> {
  const out: Record<string, unknown> = { period: f.period || null };
  for (const k of ["procurement_type", "issuing_authority_type", "contract_method", "award_method", "agency_name", "industry_name", "region_name"] as const) {
    if (f[k]) out[k] = f[k];
  }
  if (f.as_of) out.as_of = `${f.as_of}T23:59:59+09:00`;
  const lo = parseWonInput(f.amount_min);
  const hi = parseWonInput(f.amount_max);
  if (lo) out.amount_min = lo;
  if (hi) out.amount_max = hi;
  return out;
}

export function periodText(p?: { from: string | null; to: string; preset?: string }): string {
  if (!p) return "";
  const d = (s: string | null) => (s ? s.slice(0, 10) : "처음");
  return `${d(p.from)} ~ ${d(p.to)}${p.preset ? ` (${p.preset})` : ""}`;
}

export function AnalysisFilters({ value, onChange }: { value: AF; onChange: (f: AF) => void }) {
  const set = (k: keyof AF) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4" aria-label="분석 조건">
      <label><span className="label">분석 기간</span>
        <select className="input" value={value.period} onChange={set("period")}>
          <option value="3m">최근 3개월</option><option value="6m">최근 6개월</option><option value="1y">최근 1년</option><option value="3y">최근 3년</option><option value="">전체</option>
        </select>
      </label>
      <label><span className="label">분석 기준일(이후 자료 제외)</span><input className="input" type="date" value={value.as_of} onChange={set("as_of")} /></label>
      <label><span className="label">업무구분</span>
        <select className="input" value={value.procurement_type} onChange={set("procurement_type")}>
          <option value="">전체</option><option value="construction">공사</option><option value="service">용역</option><option value="goods">물품</option>
        </select>
      </label>
      <label><span className="label">기관유형</span>
        <select className="input" value={value.issuing_authority_type} onChange={set("issuing_authority_type")}>
          <option value="">전체</option><option value="national">국가기관</option><option value="local">지방자치단체</option><option value="public_corp">공기업·준정부기관</option>
        </select>
      </label>
      <label><span className="label">계약방법</span><input className="input" value={value.contract_method} onChange={set("contract_method")} placeholder="예: 제한경쟁" /></label>
      <label><span className="label">낙찰자 결정방법</span><input className="input" value={value.award_method} onChange={set("award_method")} placeholder="예: 적격심사" /></label>
      <label><span className="label">발주기관(포함)</span><input className="input" value={value.agency_name} onChange={set("agency_name")} /></label>
      <label><span className="label">업종(포함)</span><input className="input" value={value.industry_name} onChange={set("industry_name")} /></label>
      <label><span className="label">지역(포함)</span><input className="input" value={value.region_name} onChange={set("region_name")} /></label>
      <label><span className="label">기초금액 이상(원)</span><input className="input" inputMode="numeric" value={value.amount_min} onChange={set("amount_min")} /></label>
      <label><span className="label">기초금액 이하(원)</span><input className="input" inputMode="numeric" value={value.amount_max} onChange={set("amount_max")} /></label>
    </div>
  );
}
