import { useState } from "react";
import { get, post } from "../api/client";
import { Badge, Empty, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt, EVIDENCE, ko, label, SOURCE_NAME } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Op { key: string; label: string; source_name: string; operation: string; procurement_type: string | null; evidence: string; date_types: string[]; by_notice_number: boolean; max_window_days: number; search_params: string[] }
interface Sources { service_key_configured: boolean; usage_today: { source_name: string; date: string; used: number; limit: number; protect_at: number }[]; operations: Op[] }
interface Job { id: number; source_name: string; operation: string; operation_label?: string; query_parameters: Record<string, unknown>; status: string; started_at: string; finished_at: string | null; request_count: number; inserted_count: number; updated_count: number; skipped_count: number; error_summary: JobSummary | null }
// 서버는 수집 결과 요약을 객체로 준다(성공해도 returned_items·warnings 가 있음).
export interface JobSummary { returned_items?: number; warnings?: string[]; request_errors?: string[]; error?: string; error_code?: string }

export function JobSummaryCell({ s }: { s: JobSummary | null }) {
  if (!s) return null;
  const warnings = s.warnings ?? [];
  return (
    <div className="space-y-0.5">
      {s.returned_items !== undefined && <div>응답 {s.returned_items}건</div>}
      {s.error && <div className="text-red-700" title={s.error_code}>{s.error}</div>}
      {(s.request_errors ?? []).slice(-3).map((e, i) => <div key={i} className="text-amber-700">{String(e)}</div>)}
      {warnings.slice(0, 3).map((w, i) => <div key={i} className="text-slate-600">{String(w)}</div>)}
      {warnings.length > 3 && <div className="text-slate-500">외 경고 {warnings.length - 3}건</div>}
    </div>
  );
}

const DATE_TYPE: Record<string, string> = { posted: "공고일", opened: "개찰일", registered: "등록일" };
// 입찰공고 검색 오퍼레이션의 추가 조건(공공데이터포털 요청 변수)
const SEARCH_LABEL: Record<string, string> = {
  bidNtceNm: "공고명(일부)", ntceInsttNm: "공고기관", dminsttNm: "수요기관", prtcptLmtRgnNm: "참가제한지역", indstrytyNm: "업종명",
  presmptPrceBgn: "추정가격 이상(원)", presmptPrceEnd: "추정가격 이하(원)",
};
const STATUS_TONE: Record<string, "green" | "amber" | "red" | "blue"> = { succeeded: "green", partial: "amber", failed: "red", quota_stopped: "amber", running: "blue" };

export default function Collections() {
  const { isAdmin } = useAuth();
  const src = useAsync(() => get<Sources>("/api/collections/sources"), []);
  const jobs = useAsync(() => get<Job[]>("/api/collections"), []);
  const [f, setF] = useState({ operation_key: "", mode: "date_range", date_from: "", date_to: "", date_type: "posted", notice_number: "", max_pages: "50" });
  const [search, setSearch] = useState<Record<string, string>>({});
  const [err, setErr] = useState<Error | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const op = src.data?.operations.find((o) => o.key === f.operation_key);

  const start = async () => {
    setErr(null);
    setMsg(null);
    try {
      const body = f.mode === "date_range"
        ? { operation_key: f.operation_key, mode: f.mode, date_from: f.date_from, date_to: f.date_to, date_type: f.date_type, max_pages: Number(f.max_pages),
            search: Object.fromEntries(Object.entries(search).filter(([k, v]) => v.trim() && op?.search_params.includes(k)).map(([k, v]) => [k, v.trim()])) }
        : { operation_key: f.operation_key, mode: f.mode, notice_number: f.notice_number, max_pages: Number(f.max_pages) };
      const r = await post<{ job_id: number }>("/api/collections", body);
      setMsg(`수집 작업 #${r.job_id} 을 시작했습니다. 진행 상태는 아래 이력에서 '새로고침'으로 확인하세요.`);
      jobs.reload();
      src.reload();
    } catch (e) {
      setErr(e as Error);
    }
  };

  return (
    <div>
      <h1 className="h1">데이터 수집 관리</h1>
      <ErrorBox error={src.error} onRetry={src.reload} />
      {src.loading && <Loading />}
      {src.data && (
        <>
          <Section title="API 상태">
            <p className="text-sm">서비스 키: {src.data.service_key_configured ? <Badge tone="green">설정됨</Badge> : <Badge tone="red">미설정</Badge>} <span className="text-xs text-slate-500">(키는 서버 환경변수 BID_DATA_GO_KR_SERVICE_KEY 에만 저장합니다)</span></p>
            <div className="table-wrap mt-2">
              <table className="tbl"><thead><tr><th>출처</th><th>오늘 호출</th><th>보호 기준</th><th>일일 한도</th></tr></thead>
                <tbody>{src.data.usage_today.map((u) => <tr key={u.source_name}><td>{ko(SOURCE_NAME, u.source_name)}</td><td>{u.used}</td><td>{u.protect_at}</td><td>{u.limit}</td></tr>)}</tbody>
              </table>
            </div>
            <Warnings tone="blue" items={["응답 필드명은 공식 문서 기준이며 실제 API 응답으로는 검증하지 않았습니다. 첫 수집 뒤 결과를 확인하세요.", "보호 기준(한도의 90%)에 이르면 수집을 멈춥니다."]} />
          </Section>
          {isAdmin ? (
            <Section title="새 수집 작업">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                <Field label="오퍼레이션">
                  <select className="input" value={f.operation_key} onChange={(e) => {
                    // 오퍼레이션마다 쓸 수 있는 기준일·조회 방식이 다르므로 맞지 않으면 첫 값으로 바꾼다
                    const next = src.data!.operations.find((o) => o.key === e.target.value);
                    const dateTypes = next?.date_types ?? [];
                    setF({ ...f, operation_key: e.target.value,
                      date_type: dateTypes.includes(f.date_type) ? f.date_type : dateTypes[0] ?? "posted",
                      mode: next && dateTypes.length === 0 ? "notice_number" : next && !next.by_notice_number ? "date_range" : f.mode });
                  }}>
                    <option value="">선택</option>
                    {src.data.operations.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>
                </Field>
                <Field label="조회 방식">
                  <select className="input" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>
                    <option value="date_range" disabled={op ? op.date_types.length === 0 : false}>기간</option>
                    <option value="notice_number" disabled={op ? !op.by_notice_number : false}>공고번호</option>
                  </select>
                </Field>
                {f.mode === "date_range" ? (
                  <>
                    <Field label="기준일">
                      <select className="input" value={f.date_type} onChange={(e) => setF({ ...f, date_type: e.target.value })}>
                        {(op?.date_types ?? ["posted"]).map((d) => <option key={d} value={d}>{DATE_TYPE[d] ?? d}</option>)}
                      </select>
                    </Field>
                    <Field label="최대 페이지"><input className="input" type="number" min={1} max={500} value={f.max_pages} onChange={(e) => setF({ ...f, max_pages: e.target.value })} /></Field>
                    <Field label="시작일"><input className="input" type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></Field>
                    <Field label="종료일" hint={op ? `한 번에 최대 ${op.max_window_days}일` : undefined}><input className="input" type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></Field>
                  </>
                ) : (
                  <Field label="공고번호"><input className="input" value={f.notice_number} onChange={(e) => setF({ ...f, notice_number: e.target.value })} /></Field>
                )}
              </div>
              {op && f.mode === "date_range" && op.search_params.length > 0 && (
                <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
                  {op.search_params.map((k) => (
                    <Field key={k} label={SEARCH_LABEL[k] ?? k}>
                      <input className="input" value={search[k] ?? ""} onChange={(e) => setSearch({ ...search, [k]: e.target.value })} />
                    </Field>
                  ))}
                </div>
              )}
              {op && <p className="mt-1 text-xs text-slate-500">{ko(SOURCE_NAME, op.source_name)} · 응답 형식 근거: {ko(EVIDENCE, op.evidence)} <span className="text-slate-400">({op.operation})</span></p>}
              <button className="btn-primary mt-2" disabled={!f.operation_key} onClick={() => void start()}>수집 시작</button>
              {msg && <p className="mt-2 text-sm text-green-700">{msg}</p>}
              <ErrorBox error={err} />
            </Section>
          ) : <p className="mb-3 text-sm text-slate-600">수집 작업은 관리자만 시작할 수 있습니다.</p>}
        </>
      )}
      <Section title="수집 이력" actions={<button className="btn-secondary" onClick={jobs.reload}>새로고침</button>}>
        <ErrorBox error={jobs.error} onRetry={jobs.reload} />
        {jobs.loading ? <Loading /> : (jobs.data ?? []).length === 0 ? <Empty>수집 이력이 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>오퍼레이션</th><th>상태</th><th>시작</th><th>종료</th><th>호출</th><th>추가</th><th>갱신</th><th>건너뜀</th><th>결과·오류</th></tr></thead>
              <tbody>
                {jobs.data!.map((j) => (
                  <tr key={j.id}>
                    <td>{j.id}</td><td>{j.operation_label ?? j.operation}</td><td><Badge tone={STATUS_TONE[j.status]}>{label(j.status)}</Badge></td>
                    <td>{dt(j.started_at)}</td><td>{dt(j.finished_at)}</td><td>{j.request_count}</td><td>{j.inserted_count}</td><td>{j.updated_count}</td><td>{j.skipped_count}</td>
                    <td className="max-w-md whitespace-normal text-xs"><JobSummaryCell s={j.error_summary} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
