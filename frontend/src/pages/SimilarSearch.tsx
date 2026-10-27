import { Link } from "react-router-dom";
import { useState } from "react";
import { post } from "../api/client";
import { AnalysisFilters, EMPTY_AF, periodText, toFilters, type AF } from "../components/AnalysisFilters";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Disclaimer, Empty, ErrorBox, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt, label, parseWonInput, pct, won } from "../lib/format";
import { useNoticeParam } from "../lib/useNoticeParam";

interface Match { notice_id: number; title: string; score: number; components: Record<string, number>; reasons: string[]; unknown_conditions: string[]; opening_date: string | null; agency_name: string | null; base_amount: string | null; sajeong_rate: string | null; winning_rate: string | null; rate_basis: string | null; bid_count: number | null }
interface SimilarResult { criteria: { hard_conditions: string[]; weights: Record<string, number>; amount_rule: string; recency_rule: string; as_of: string | null }; excluded: Record<string, number>; candidates_considered: number; matches: Match[]; warnings: string[]; period: { from: string | null; to: string }; analysis_run_id?: number }

const WEIGHT_LABELS: Record<string, string> = { agency: "발주기관", demand_agency: "수요기관", industry: "업종", region: "지역", amount: "금액", recency: "최근성" };
const DEFAULT_W = { agency: 3, demand_agency: 1, industry: 2, region: 1, amount: 2, recency: 1 };

export default function SimilarSearch() {
  const { canWrite } = useAuth();
  const [noticeId, setNoticeId] = useNoticeParam();
  const [mode, setMode] = useState<"notice" | "target">(noticeId ? "notice" : "notice");
  const [t, setT] = useState({ procurement_type: "construction", issuing_authority_type: "local", contract_method: "", award_method: "", agency_name: "", industry_name: "", region_name: "", amount: "" });
  const [f, setF] = useState<AF>({ ...EMPTY_AF, period: "3y" });
  const [w, setW] = useState<Record<string, number>>(DEFAULT_W);
  const [r, setR] = useState<SimilarResult | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async (save = false) => {
    setErr(null);
    setLoading(true);
    try {
      const target = Object.fromEntries(Object.entries({ ...t, amount: parseWonInput(t.amount) }).filter(([, v]) => v));
      const body = mode === "notice" ? { notice_id: noticeId, filters: toFilters(f), weights: w, save } : { target, filters: toFilters(f), weights: w, save };
      setR(await post<SimilarResult>("/api/analysis/similar", body));
    } catch (e) {
      setErr(e as Error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="h1">유사 입찰 검색</h1>
      <Section title="비교 대상">
        <div className="mb-2 flex gap-2 text-sm">
          <label><input type="radio" checked={mode === "notice"} onChange={() => setMode("notice")} /> 등록된 공고</label>
          <label><input type="radio" checked={mode === "target"} onChange={() => setMode("target")} /> 조건 직접 입력</label>
        </div>
        {mode === "notice" ? <NoticePicker value={noticeId} onChange={setNoticeId} /> : (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {(Object.keys(t) as (keyof typeof t)[]).map((k) => (
              <label key={k}><span className="label">{{ procurement_type: "업무구분(construction 등)", issuing_authority_type: "기관유형(local 등)", contract_method: "계약방법", award_method: "낙찰자 결정방법", agency_name: "발주기관", industry_name: "업종", region_name: "지역", amount: "기초금액(원)" }[k]}</span>
                <input className="input" value={t[k]} onChange={(e) => setT({ ...t, [k]: e.target.value })} /></label>
            ))}
          </div>
        )}
      </Section>
      <Section title="과거 자료 범위와 가중치">
        <AnalysisFilters value={f} onChange={setF} />
        <div className="mt-2 grid grid-cols-3 gap-2 md:grid-cols-6">
          {Object.keys(DEFAULT_W).map((k) => (
            <label key={k}><span className="label">{WEIGHT_LABELS[k]} 가중치</span>
              <input className="input" type="number" min={0} max={10} step={0.5} value={w[k]} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} /></label>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-500">가중치는 설명용 기본값이며 통계적으로 최적화한 값이 아닙니다. 업무구분·기관유형·계약방법·결정방법이 다른 공고는 후보에서 뺍니다.</p>
        <div className="mt-2 flex gap-2">
          <button className="btn-primary" disabled={loading || (mode === "notice" && !noticeId)} onClick={() => void run()}>검색</button>
          {canWrite && <button className="btn-secondary" disabled={loading || (mode === "notice" && !noticeId)} onClick={() => void run(true)}>검색 후 저장</button>}
        </div>
      </Section>
      {loading && <Loading />}
      <ErrorBox error={err} />
      {r && (
        <>
          <p className="mb-2 text-sm text-slate-700">
            기간 {periodText(r.period)} · 기준 시각 {dt(r.criteria.as_of)} 이전 개찰만 · 후보 {r.candidates_considered}건 · 조건 불일치 제외 {r.excluded.hard_mismatch}건 · 기준 이후/개찰일 미상 제외 {r.excluded.after_as_of_or_no_opening_date}건
            {r.analysis_run_id && <> · 저장됨 <a className="text-blue-700 underline" href={`/api/reports/runs/${r.analysis_run_id}.xlsx`}>XLSX</a></>}
          </p>
          <Warnings items={r.warnings} />
          {r.matches.length === 0 ? <Empty>유사 입찰이 없습니다.</Empty> : (
            <div className="space-y-2">
              {r.matches.map((m, i) => (
                <div key={m.notice_id} className="card text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Link className="font-medium text-blue-700 hover:underline" to={`/notice-analysis?notice=${m.notice_id}`}>{i + 1}. {m.title}</Link>
                    <Badge tone="blue">점수 {m.score}</Badge>
                  </div>
                  <div className="text-xs text-slate-600">{m.agency_name} · 개찰 {dt(m.opening_date)} · {won(m.base_amount)} · 참가 {m.bid_count ?? "-"}개사</div>
                  <div>사정률 {pct(m.sajeong_rate)} · 낙찰률 {pct(m.winning_rate)} {m.rate_basis && `(${label(m.rate_basis)} 대비)`}</div>
                  <div className="mt-1 text-xs">선정 이유: {m.reasons.join(" · ")}</div>
                  <div className="text-xs text-slate-500">항목별 점수: {Object.entries(m.components).map(([k, v]) => `${WEIGHT_LABELS[k] ?? k} ${v}`).join(", ")}</div>
                </div>
              ))}
            </div>
          )}
          <Disclaimer>금액 점수: {r.criteria.amount_rule}. 시점 점수: {r.criteria.recency_rule}. 유사 입찰 결과는 참고용이며 이번 공고의 결과를 예측하지 않습니다.</Disclaimer>
        </>
      )}
    </div>
  );
}
