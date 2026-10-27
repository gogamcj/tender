import { useState } from "react";
import { Link } from "react-router-dom";
import { get, patch, post } from "../api/client";
import type { Notice } from "../api/types";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Empty, ErrorBox, Loading, Section } from "../components/ui";
import { useAuth } from "../lib/auth";
import { day, dt, label, pct, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useNoticeParam } from "../lib/useNoticeParam";

interface Detail extends Notice {
  vat_included: boolean | null;
  vat_amount: string | null;
  reserve_range_begin_rate: string | null;
  reserve_range_end_rate: string | null;
  collected_at: string | null;
  raw_record_count: number;
  revisions: { id: number; notice_revision: string; title: string; is_latest: boolean }[];
  results: {
    id: number; source_name: string; rebid_number: number; opening_status: string | null; lookup_status: string | null;
    bid_count: number | null; winning_vendor_name: string | null; winning_bid_amount: string | null; winning_rate: string | null;
    winning_rate_basis: string | null; actual_estimated_price: string | null; actual_base_price: string | null; actual_sajeong_rate: string | null;
    external_metrics: Record<string, string> | null; opening_datetime: string | null;
    candidates: { ranking: number | null; vendor_name: string | null; bid_amount: string | null; bid_rate: string | null; bid_rate_basis: string | null }[];
  }[];
  change_log: { id: number; field_name: string; old_value: string | null; new_value: string | null; change_source: string; applied: boolean; changed_at: string }[];
}

const STATUSES = ["collected", "verified", "partial", "duplicate_suspected", "source_mismatch", "revision_check_needed", "result_unconfirmed", "excluded"];

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2 border-b py-1 text-sm">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right">{v ?? "-"}</dd>
    </div>
  );
}

export default function NoticeAnalysis() {
  const [id, setId] = useNoticeParam();
  const { canWrite } = useAuth();
  const d = useAsync(() => get<Detail>(`/api/notices/${id}`), [id], !!id);
  const [actionError, setActionError] = useState<Error | null>(null);

  const changeStatus = async (s: string) => {
    setActionError(null);
    try {
      await patch(`/api/notices/${id}/status`, { data_status: s });
      d.reload();
    } catch (e) {
      setActionError(e as Error);
    }
  };
  const applyChange = async (logId: number) => {
    setActionError(null);
    try {
      await post(`/api/notices/${id}/changes/${logId}/apply`);
      d.reload();
    } catch (e) {
      setActionError(e as Error);
    }
  };

  return (
    <div>
      <h1 className="h1">공고 상세 분석</h1>
      <div className="card mb-3"><NoticePicker value={id} onChange={setId} /></div>
      {!id && <Empty>분석할 공고를 고르세요.</Empty>}
      {d.loading && <Loading />}
      <ErrorBox error={d.error ?? actionError} onRetry={d.reload} />
      {d.data && (() => {
        const n = d.data;
        const pending = n.change_log.filter((c) => !c.applied);
        const q = `?notice=${n.id}`;
        return (
          <>
            <div className="card mb-3">
              <div className="text-xs text-slate-500">{n.notice_number}-{n.notice_revision} · {n.source_name}</div>
              <h2 className="text-lg font-bold">{n.title}</h2>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge tone={n.data_status === "collected" || n.data_status === "verified" ? "green" : "amber"}>{n.data_status_label || n.data_status}</Badge>
                <Badge>{label(n.phase)}</Badge>
                {!n.is_latest_revision && <Badge tone="red">최신 차수 아님</Badge>}
                {pending.length > 0 && <Badge tone="amber">보류 변경 {pending.length}건</Badge>}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                <div><div className="text-xs text-slate-500">기초금액</div><div className="font-bold">{won(n.base_amount)}</div></div>
                <div><div className="text-xs text-slate-500">입찰마감</div><div className="font-bold">{dt(n.bid_deadline)}</div></div>
                <div><div className="text-xs text-slate-500">낙찰하한율</div><div className="font-bold">{pct(n.lower_limit_rate)}</div></div>
                <div><div className="text-xs text-slate-500">예정가격</div><div className="font-bold">{won(n.estimated_price)} <span className="text-xs font-normal">({label(n.estimated_price_status)})</span></div></div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-sm">
                <Link className="btn-primary" to={`/scenarios${q}`}>투찰 시나리오</Link>
                <Link className="btn-secondary" to={`/similar${q}`}>유사 입찰</Link>
                <Link className="btn-secondary" to={`/qualification${q}`}>적격심사</Link>
                <Link className="btn-secondary" to={`/costs${q}`}>원가</Link>
                <Link className="btn-secondary" to={`/pdfs${q}`}>공고문 PDF</Link>
                <Link className="btn-secondary" to={`/reserve${q}`}>복수예비가격</Link>
                {n.notice_url && <a className="btn-secondary" href={n.notice_url} target="_blank" rel="noreferrer noopener">원문 공고</a>}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Section title="공고 정보">
                <dl>
                  <Row k="공고기관" v={n.agency_name} /><Row k="수요기관" v={n.demand_agency_name} />
                  <Row k="업무구분" v={label(n.procurement_type)} /><Row k="기관유형" v={label(n.issuing_authority_type)} />
                  <Row k="계약방법" v={n.contract_method} /><Row k="낙찰자 결정방법" v={n.award_method} />
                  <Row k="지역" v={n.region_name} /><Row k="업종" v={n.industry_name} />
                  <Row k="공고일" v={day(n.announcement_date)} /><Row k="개찰일시" v={dt(n.opening_date)} />
                  <Row k="추정가격" v={won(n.presumed_price)} />
                  <Row k="부가세 포함" v={n.vat_included === null ? "미확인" : n.vat_included ? "포함" : "별도"} />
                  <Row k="예비가격 범위" v={n.reserve_range_begin_rate ? `${n.reserve_range_begin_rate}% ~ ${n.reserve_range_end_rate}%` : "-"} />
                  <Row k="원본 기록" v={`${n.raw_record_count}건`} />
                </dl>
                {canWrite && (
                  <label className="mt-2 block">
                    <span className="label">데이터 상태 바꾸기(이력이 남습니다)</span>
                    <select className="input" value={n.data_status} onChange={(e) => void changeStatus(e.target.value)}>
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </label>
                )}
              </Section>
              <Section title="개찰 결과">
                {n.results.length === 0 ? (
                  <Empty>개찰 결과가 없습니다. 결과가 없다는 것은 유찰을 뜻하지 않습니다.</Empty>
                ) : n.results.map((r) => (
                  <div key={r.id} className="mb-3">
                    <div className="text-xs text-slate-500">출처 {r.source_name} · 재입찰 {r.rebid_number} · 조회 상태 {r.lookup_status}</div>
                    <dl>
                      <Row k="개찰 상태" v={r.opening_status} /><Row k="참가업체수" v={r.bid_count} />
                      <Row k="낙찰업체" v={r.winning_vendor_name} /><Row k="낙찰금액" v={won(r.winning_bid_amount)} />
                      <Row k="낙찰률" v={r.winning_rate ? `${pct(r.winning_rate)} (${label(r.winning_rate_basis) || "기준 미상"} 대비)` : "-"} />
                      <Row k="확정 예정가격" v={won(r.actual_estimated_price)} /><Row k="사정률" v={pct(r.actual_sajeong_rate)} />
                    </dl>
                    {r.external_metrics && Object.keys(r.external_metrics).length > 0 && (
                      <p className="mt-1 text-xs text-slate-500">원본 제공 값(기준 미확인): {Object.entries(r.external_metrics).map(([k, v]) => `${k}=${v}`).join(", ")}</p>
                    )}
                    {r.candidates.length > 0 && (
                      <div className="table-wrap mt-2">
                        <table className="tbl"><thead><tr><th>순위</th><th>업체</th><th>투찰금액</th><th>투찰률</th></tr></thead>
                          <tbody>{r.candidates.slice(0, 20).map((c, i) => <tr key={i}><td>{c.ranking ?? "-"}</td><td>{c.vendor_name}</td><td>{won(c.bid_amount)}</td><td>{pct(c.bid_rate)}</td></tr>)}</tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </Section>
            </div>
            <Section title="정정 차수">
              <ul className="text-sm">
                {n.revisions.map((r) => (
                  <li key={r.id}><button className="text-blue-700 underline" onClick={() => setId(r.id)}>{r.notice_revision}차</button> {r.title} {r.is_latest && <Badge tone="green">최신</Badge>}</li>
                ))}
              </ul>
            </Section>
            <Section title="변경 이력">
              {n.change_log.length === 0 ? <Empty>변경 이력이 없습니다.</Empty> : (
                <div className="table-wrap">
                  <table className="tbl">
                    <thead><tr><th>항목</th><th>이전 값</th><th>새 값</th><th>출처</th><th>시각</th><th>반영</th></tr></thead>
                    <tbody>
                      {n.change_log.map((c) => (
                        <tr key={c.id} className={c.applied ? "" : "bg-amber-50"}>
                          <td>{c.field_name}</td><td>{c.old_value ?? "-"}</td><td>{c.new_value ?? "-"}</td><td>{c.change_source}</td><td>{dt(c.changed_at)}</td>
                          <td>{c.applied ? "반영됨" : canWrite ? <button className="btn-secondary text-xs" onClick={() => void applyChange(c.id)}>확인 후 반영</button> : "보류"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          </>
        );
      })()}
    </div>
  );
}
