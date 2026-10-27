import { useState } from "react";
import { get, post } from "../api/client";
import type { StatsResult, Summary } from "../api/types";
import { AnalysisFilters, EMPTY_AF, periodText, toFilters, type AF } from "../components/AnalysisFilters";
import { ChartFrame, SimpleBar } from "../components/charts";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Disclaimer, Empty, ErrorBox, Loading, Section, Warnings } from "../components/ui";
import { useAsync } from "../lib/useAsync";
import { useNoticeParam } from "../lib/useNoticeParam";
import { won } from "../lib/format";
import { SummaryTable } from "./HistoryAnalysis";

type Bin = { from: number; to: number; count: number };
interface ReserveStats {
  period: { from: string | null; to: string };
  strata: { label: string; notice_count: number; all_prices: Summary; drawn_prices: Summary; histogram_all: Bin[]; histogram_drawn: Bin[]; draws_by_seq: { seq: number; count: number }[] }[];
  warnings: string[];
  definition: string;
  disclaimer: string;
}
interface NoticeReserve {
  reserve_range: { begin_rate: string | null; end_rate: string | null };
  available: boolean;
  note: string | null;
  results: { result_id: number; source_name: string; base_amount: string | null; drawn_count: number; prices: { seq: number; amount: string; rate_vs_base: string | null; drawn: boolean | null }[]; estimated_check: { drawn_mean: string; actual_estimated_price: string; difference: string; consistent: boolean; meaning: string } | null }[];
}

const binsToBars = (bins: Bin[]) => bins.map((b) => ({ name: `${b.from}`, value: b.count, extra: `${b.from}~${b.to}%` }));

export default function ReserveAnalysis() {
  const [f, setF] = useState<AF>({ ...EMPTY_AF, period: "3y" });
  const [width, setWidth] = useState("0.5");
  const [dist, setDist] = useState<StatsResult | null>(null);
  const [rs, setRs] = useState<ReserveStats | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [noticeId, setNoticeId] = useNoticeParam();
  const nr = useAsync(() => get<NoticeReserve>(`/api/notices/${noticeId}/reserve-prices`), [noticeId], !!noticeId);

  const run = async () => {
    setErr(null);
    setLoading(true);
    try {
      const filters = toFilters(f);
      const [d, r] = await Promise.all([
        post<StatsResult>("/api/analysis/sajeong-distribution", { filters, bin_width: Number(width) }),
        post<ReserveStats>("/api/analysis/reserve-prices", { filters, bin_width: Number(width) }),
      ]);
      setDist(d);
      setRs(r);
    } catch (e) {
      setErr(e as Error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="h1">복수예비가격·사정률 분석</h1>
      <Section title="조건">
        <AnalysisFilters value={f} onChange={setF} />
        <div className="mt-2 flex items-end gap-2">
          <label><span className="label">구간 폭(%p)</span>
            <select className="input" value={width} onChange={(e) => setWidth(e.target.value)}>
              <option value="0.1">0.1</option><option value="0.25">0.25</option><option value="0.5">0.5</option><option value="1">1</option>
            </select>
          </label>
          <button className="btn-primary" onClick={() => void run()} disabled={loading}>분석</button>
        </div>
      </Section>
      {loading && <Loading />}
      <ErrorBox error={err} />
      {dist && (
        <>
          <Warnings items={dist.warnings} />
          {dist.strata.length === 0 && <Empty>조건에 맞는 사정률 자료가 없습니다.</Empty>}
          {dist.strata.map((s) => (
            <div key={s.label}>
              <ChartFrame title={`사정률 분포 — ${s.label}`} meta={{ period: periodText(dist.period), n: s.summary.n, basis: "(예정가격 − 기초금액) ÷ 기초금액", sources: dist.sources, warnings: s.summary.warnings }}
                table={{ columns: ["구간(%)", "건수"], rows: (dist.histograms?.[s.label] ?? []).map((b) => [`${b.from} ~ ${b.to}`, b.count]) }}>
                <SimpleBar data={binsToBars(dist.histograms?.[s.label] ?? [])} valueLabel="건수" />
              </ChartFrame>
              <div className="card mb-4"><SummaryTable s={s.summary} /></div>
            </div>
          ))}
          <Disclaimer>{dist.disclaimer}</Disclaimer>
        </>
      )}
      {rs && (
        <Section title="복수예비가격 분포(공식 수집 자료)">
          <Warnings items={rs.warnings} />
          {rs.strata.map((s) => (
            <div key={s.label} className="mb-4">
              <ChartFrame title={`추첨된 예비가격 비율 — ${s.label}`} meta={{ period: periodText(rs.period), n: s.drawn_prices.n, basis: rs.definition, sources: `공고 ${s.notice_count}건` }}
                table={{ columns: ["구간(%)", "추첨 건수"], rows: s.histogram_drawn.map((b) => [`${b.from} ~ ${b.to}`, b.count]) }}>
                <SimpleBar data={binsToBars(s.histogram_drawn)} valueLabel="추첨 건수" />
              </ChartFrame>
              <ChartFrame title="번호별 추첨 횟수" meta={{ period: periodText(rs.period), n: s.notice_count, basis: "예비가격 번호(1~15)", sources: `공고 ${s.notice_count}건` }}
                table={{ columns: ["번호", "추첨 횟수"], rows: s.draws_by_seq.map((x) => [x.seq, x.count]) }}>
                <SimpleBar data={s.draws_by_seq.map((x) => ({ name: String(x.seq), value: x.count }))} valueLabel="추첨 횟수" />
              </ChartFrame>
            </div>
          ))}
          <Disclaimer>{rs.disclaimer}</Disclaimer>
        </Section>
      )}
      <Section title="공고별 복수예비가격">
        <NoticePicker value={noticeId} onChange={setNoticeId} />
        {nr.loading && <Loading />}
        <ErrorBox error={nr.error} />
        {nr.data && !nr.data.available && <Empty>{nr.data.note}</Empty>}
        {nr.data?.results.filter((r) => r.prices.length).map((r) => (
          <div key={r.result_id} className="mt-3">
            <div className="text-sm">기초금액 {won(r.base_amount)} · 추첨 {r.drawn_count}개 · 예비가격 범위 {nr.data!.reserve_range.begin_rate ?? "?"}% ~ {nr.data!.reserve_range.end_rate ?? "?"}%</div>
            {r.estimated_check && (
              <p className="text-sm">추첨값 평균 {won(r.estimated_check.drawn_mean)} / 공개 예정가격 {won(r.estimated_check.actual_estimated_price)} {r.estimated_check.consistent ? <Badge tone="green">일치</Badge> : <Badge tone="red">차이 {r.estimated_check.difference}원</Badge>}</p>
            )}
            <div className="table-wrap"><table className="tbl"><thead><tr><th>번호</th><th>금액</th><th>기초금액 대비</th><th>추첨</th></tr></thead>
              <tbody>{r.prices.map((p) => <tr key={p.seq} className={p.drawn ? "bg-blue-50" : ""}><td>{p.seq}</td><td>{won(p.amount)}</td><td>{p.rate_vs_base ?? "-"}%</td><td>{p.drawn ? "추첨" : ""}</td></tr>)}</tbody>
            </table></div>
          </div>
        ))}
      </Section>
    </div>
  );
}
