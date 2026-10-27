import { useState } from "react";
import { post } from "../api/client";
import type { StatsResult, Stratum, Summary } from "../api/types";
import { AnalysisFilters, EMPTY_AF, periodText, toFilters, type AF } from "../components/AnalysisFilters";
import { ChartFrame, SimpleBar, TrendLine } from "../components/charts";
import { Disclaimer, ErrorBox, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { num } from "../lib/format";

const DIMENSIONS: [string, string][] = [
  ["", "묶지 않음"], ["agency_name", "발주기관별"], ["industry_name", "업종(공종)별"], ["amount_band", "금액 구간별"],
  ["bid_count_band", "참가업체 수 구간별"], ["region_name", "지역별"], ["contract_method", "계약방법별"],
];

export function SummaryTable({ s }: { s: Summary }) {
  const cells: [string, string][] = [
    ["건수", String(s.n)], ["평균", num(s.mean)], ["중앙값", num(s.median)], ["1사분위", num(s.q1)], ["3사분위", num(s.q3)],
    ["표준편차", num(s.std)], ["최소", num(s.min)], ["최대", num(s.max)], ["이상치", `${s.outliers}건${s.outliers_excluded ? "(제외함)" : "(포함)"}`],
  ];
  return (
    <dl className="grid grid-cols-3 gap-2 text-sm md:grid-cols-9">
      {cells.map(([k, v]) => (
        <div key={k} className="rounded bg-slate-50 p-1.5"><dt className="text-xs text-slate-500">{k}</dt><dd className="font-semibold">{v}</dd></div>
      ))}
    </dl>
  );
}

function basisOf(r: StatsResult, s: Stratum) {
  if (r.metric === "winning_rate") return `${s.conditions.rate_basis === "estimated_price" ? "예정가격" : s.conditions.rate_basis === "base_amount" ? "기초금액" : s.conditions.rate_basis ?? "미상"} 대비`;
  if (r.metric === "sajeong_rate") return "기초금액 대비 예정가격";
  return "참가업체 수";
}

export default function HistoryAnalysis() {
  const { canWrite } = useAuth();
  const [f, setF] = useState<AF>(EMPTY_AF);
  const [metric, setMetric] = useState("winning_rate");
  const [groupBy, setGroupBy] = useState("agency_name");
  const [excludeOutliers, setExcludeOutliers] = useState(false);
  const [r, setR] = useState<StatsResult | null>(null);
  const [counts, setCounts] = useState<StatsResult | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async (save = false) => {
    setErr(null);
    setLoading(true);
    try {
      const body = { filters: toFilters(f), metric, group_by: groupBy ? [groupBy] : [], exclude_outliers: excludeOutliers, trend: "month", save };
      const [main, bc] = await Promise.all([
        post<StatsResult>("/api/analysis/stats", body),
        post<StatsResult>("/api/analysis/stats", { ...body, metric: "bid_count", group_by: ["bid_count_band"], save: false }),
      ]);
      setR(main);
      setCounts(bc);
    } catch (e) {
      setErr(e as Error);
    } finally {
      setLoading(false);
    }
  };

  const unit = metric === "bid_count" ? "개사" : "%";
  return (
    <div>
      <h1 className="h1">과거 개찰 결과 분석</h1>
      <Section title="조건">
        <AnalysisFilters value={f} onChange={setF} />
        <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
          <label><span className="label">지표</span>
            <select className="input" value={metric} onChange={(e) => setMetric(e.target.value)}>
              <option value="winning_rate">낙찰률</option><option value="sajeong_rate">사정률</option><option value="bid_count">참가업체 수</option>
            </select>
          </label>
          <label><span className="label">비교 기준</span>
            <select className="input" value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
              {DIMENSIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </label>
          <label className="flex items-end gap-1 text-sm"><input type="checkbox" checked={excludeOutliers} onChange={(e) => setExcludeOutliers(e.target.checked)} /> 이상치 제외(IQR 1.5배)</label>
          <div className="flex items-end gap-2">
            <button className="btn-primary" onClick={() => void run()} disabled={loading}>분석</button>
            {canWrite && <button className="btn-secondary" onClick={() => void run(true)} disabled={loading}>분석 후 저장</button>}
          </div>
        </div>
      </Section>
      {loading && <Loading />}
      <ErrorBox error={err} />
      {r && (
        <>
          <div className="mb-2 text-sm text-slate-700">
            대상 {r.n_records}건 · 누락 {r.missing_count}건(누락률 {r.missing_rate === null ? "-" : `${(r.missing_rate * 100).toFixed(1)}%`}) · 기간 {periodText(r.period)}
            {r.analysis_run_id && <> · 저장됨(분석 #{r.analysis_run_id}) <a className="text-blue-700 underline" href={`/api/reports/runs/${r.analysis_run_id}.xlsx`}>XLSX</a></>}
          </div>
          <Warnings items={r.warnings} />
          {r.strata.length > 1 && <p className="mb-2 text-sm text-amber-900">조건(계약방법·결정방식·기준 등)이 다른 자료는 섞지 않고 아래처럼 따로 보여 줍니다.</p>}
          {r.strata.map((s) => {
            const meta = { period: periodText(r.period), n: s.summary.n, basis: basisOf(r, s), sources: r.sources, warnings: s.summary.warnings };
            const trend = s.trend.filter((t) => t.median !== null).map((t) => ({ name: t.period, value: t.median as number, n: t.n }));
            const groups = s.groups.map((g) => ({ name: Object.values(g.key).join(" ") || "미상", value: g.summary.median ?? 0, n: g.summary.n }));
            return (
              <div key={s.label} className="mb-6">
                <h2 className="h2">{s.label}</h2>
                <div className="card mb-3"><SummaryTable s={s.summary} /></div>
                <ChartFrame title={`기간별 ${r.metric_label} (월별 중앙값)`} meta={meta}
                  table={{ columns: ["월", "건수", "중앙값"], rows: s.trend.map((t) => [t.period, t.n, num(t.median)]) }}>
                  <TrendLine data={trend} unit={unit} valueLabel={`${r.metric_label} 중앙값`} />
                </ChartFrame>
                {groups.length > 0 && (
                  <ChartFrame title={`${DIMENSIONS.find(([k]) => k === groupBy)?.[1] ?? ""} ${r.metric_label} 비교(중앙값)`} meta={meta}
                    table={{ columns: ["묶음", "건수", "중앙값", "평균", "최소", "최대"], rows: s.groups.map((g) => [Object.values(g.key).join(" ") || "미상", g.summary.n, num(g.summary.median), num(g.summary.mean), num(g.summary.min), num(g.summary.max)]) }}>
                    <SimpleBar data={groups.slice(0, 15)} unit={unit} valueLabel="중앙값" />
                  </ChartFrame>
                )}
              </div>
            );
          })}
          {counts && counts.strata.map((s) => (
            <ChartFrame key={`bc-${s.label}`} title={`입찰 참여 업체 수 분포 — ${s.label}`}
              meta={{ period: periodText(counts.period), n: s.summary.n, basis: "개찰 결과 참가업체 수", sources: counts.sources }}
              table={{ columns: ["구간", "건수"], rows: s.groups.map((g) => [String(g.key.bid_count_band ?? "미상"), g.summary.n]) }}>
              <SimpleBar data={s.groups.map((g) => ({ name: String(g.key.bid_count_band ?? "미상"), value: g.summary.n }))} unit="건" valueLabel="공고 수" />
            </ChartFrame>
          ))}
          <Disclaimer>{r.disclaimer} 평균 하나로 투찰금액을 정하지 마세요. 정의: {r.metric_definition}</Disclaimer>
        </>
      )}
    </div>
  );
}
