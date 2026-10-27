import { useState } from "react";
import { get, post } from "../api/client";
import { Badge, Empty, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt, label } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Op { key: string; label: string; source_name: string; operation: string; procurement_type: string | null; evidence: string; date_types: string[]; by_notice_number: boolean; max_window_days: number; search_params: string[] }
interface Sources { service_key_configured: boolean; usage_today: { source_name: string; date: string; used: number; limit: number; protect_at: number }[]; operations: Op[] }
interface Job { id: number; source_name: string; operation: string; query_parameters: Record<string, unknown>; status: string; started_at: string; finished_at: string | null; request_count: number; inserted_count: number; updated_count: number; skipped_count: number; error_summary: string | null }

const DATE_TYPE: Record<string, string> = { posted: "공고일", opening: "개찰일" };
const STATUS_TONE: Record<string, "green" | "amber" | "red" | "blue"> = { succeeded: "green", partial: "amber", failed: "red", quota_stopped: "amber", running: "blue" };

export default function Collections() {
  const { isAdmin } = useAuth();
  const src = useAsync(() => get<Sources>("/api/collections/sources"), []);
  const jobs = useAsync(() => get<Job[]>("/api/collections"), []);
  const [f, setF] = useState({ operation_key: "", mode: "date_range", date_from: "", date_to: "", date_type: "posted", notice_number: "", max_pages: "50" });
  const [err, setErr] = useState<Error | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const op = src.data?.operations.find((o) => o.key === f.operation_key);

  const start = async () => {
    setErr(null);
    setMsg(null);
    try {
      const body = f.mode === "date_range"
        ? { operation_key: f.operation_key, mode: f.mode, date_from: f.date_from, date_to: f.date_to, date_type: f.date_type, max_pages: Number(f.max_pages) }
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
                <tbody>{src.data.usage_today.map((u) => <tr key={u.source_name}><td>{u.source_name}</td><td>{u.used}</td><td>{u.protect_at}</td><td>{u.limit}</td></tr>)}</tbody>
              </table>
            </div>
            <Warnings tone="blue" items={["응답 필드명은 공식 문서 기준이며 실제 API 응답으로는 검증하지 않았습니다. 첫 수집 뒤 결과를 확인하세요.", "보호 기준(한도의 90%)에 이르면 수집을 멈춥니다."]} />
          </Section>
          {isAdmin ? (
            <Section title="새 수집 작업">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                <Field label="오퍼레이션">
                  <select className="input" value={f.operation_key} onChange={(e) => setF({ ...f, operation_key: e.target.value })}>
                    <option value="">선택</option>
                    {src.data.operations.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>
                </Field>
                <Field label="조회 방식">
                  <select className="input" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>
                    <option value="date_range">기간</option>
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
              {op && <p className="mt-1 text-xs text-slate-500">{op.source_name} / {op.operation} · 근거: {op.evidence}</p>}
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
              <thead><tr><th>#</th><th>오퍼레이션</th><th>상태</th><th>시작</th><th>종료</th><th>호출</th><th>추가</th><th>갱신</th><th>건너뜀</th><th>오류</th></tr></thead>
              <tbody>
                {jobs.data!.map((j) => (
                  <tr key={j.id}>
                    <td>{j.id}</td><td>{j.operation}</td><td><Badge tone={STATUS_TONE[j.status]}>{label(j.status)}</Badge></td>
                    <td>{dt(j.started_at)}</td><td>{dt(j.finished_at)}</td><td>{j.request_count}</td><td>{j.inserted_count}</td><td>{j.updated_count}</td><td>{j.skipped_count}</td>
                    <td className="max-w-xs whitespace-normal text-xs">{j.error_summary ?? ""}</td>
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
