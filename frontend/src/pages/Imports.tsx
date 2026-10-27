import { useState } from "react";
import { get, post, upload } from "../api/client";
import { Badge, Empty, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Sheet { name: string; columns: string[]; row_count: number; sample_rows: Record<string, string>[]; suggested_mapping: Record<string, string> }
interface Target { key: string; label: string; kind: string; required: boolean; group: string; enum_values: string[] | null }
interface Analysis { job_id: number; file_name: string; source_type: string; encoding: string | null; warnings: string[]; sheets: Sheet[]; target_fields: Target[] }
interface Row { row_number: number; status: string; existing_id: number | null; values: Record<string, string | null>; errors: string[]; warnings: string[]; diffs: { field: string; label: string; old: string | null; new: string | null }[] }
interface Preview { job_id: number; mapping_errors: string[]; counts: Record<string, number>; rows: Row[] }
interface Job { id: number; file_name: string; source_type: string; status: string; uploaded_at: string; committed_at: string | null; row_count: number | null; accepted_count: number | null; rejected_count: number | null; duplicate_count: number | null }

export const ROW_STATUS: Record<string, [string, "green" | "blue" | "slate" | "amber" | "red"]> = {
  new: ["새 공고", "green"], new_revision: ["새 차수", "blue"], unchanged: ["변경 없음", "slate"], changed: ["기존과 다름", "amber"],
  duplicate_in_file: ["파일 내 중복", "amber"], invalid: ["오류", "red"],
};
const JOB_STATUS: Record<string, string> = { analyzing: "분석 중", mapping: "열 연결 대기", preview: "미리보기", committed: "저장 완료", cancelled: "취소", rolled_back: "되돌림", failed: "실패" };

export default function Imports() {
  const { canWrite } = useAuth();
  const jobs = useAsync(() => get<Job[]>("/api/imports"), []);
  const [file, setFile] = useState<File | null>(null);
  const [headerRow, setHeaderRow] = useState("0");
  const [an, setAn] = useState<Analysis | null>(null);
  const [sheet, setSheet] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [opts, setOpts] = useState({ rate_unit: "percent", default_winning_rate_basis: "", procurement_type: "", issuing_authority_type: "" });
  const [pv, setPv] = useState<Preview | null>(null);
  const [accept, setAccept] = useState<Set<number>>(new Set());
  const [skip, setSkip] = useState<Set<number>>(new Set());
  const [done, setDone] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<Error | null>(null);

  const step = async (fn: () => Promise<void>) => {
    setErr(null);
    setBusy(true);
    try { await fn(); } catch (e) { setErr(e as Error); } finally { setBusy(false); }
  };
  const doUpload = () => step(async () => {
    if (!file) return;
    const a = await upload<Analysis>(`/api/imports?header_row=${Number(headerRow) || 0}`, file);
    setAn(a);
    setSheet(a.sheets[0]?.name ?? "");
    setMapping(a.sheets[0]?.suggested_mapping ?? {});
    setPv(null);
    setDone(null);
    jobs.reload();
  });
  const doPreview = () => step(async () => {
    const options = Object.fromEntries(Object.entries(opts).filter(([, v]) => v !== ""));
    const m = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
    const p = await post<Preview>(`/api/imports/${an!.job_id}/preview`, { sheet_name: sheet || null, mapping: m, options });
    setPv(p);
    setAccept(new Set());
    setSkip(new Set());
  });
  const doCommit = () => step(async () => {
    const r = await post<{ counts: Record<string, number> }>(`/api/imports/${an!.job_id}/commit`, { accept_changes: [...accept], skip_rows: [...skip] });
    setDone(r.counts);
    jobs.reload();
  });
  const rollback = (id: number) => step(async () => {
    if (!window.confirm(`업로드 작업 #${id} 으로 저장한 데이터를 되돌릴까요?`)) return;
    await post(`/api/imports/${id}/rollback`);
    jobs.reload();
  });
  const toggle = (set: Set<number>, upd: (s: Set<number>) => void, n: number) => {
    const s = new Set(set);
    if (s.has(n)) s.delete(n); else s.add(n);
    upd(s);
  };
  const cur = an?.sheets.find((s) => s.name === sheet);

  return (
    <div>
      <h1 className="h1">엑셀 업로드 관리</h1>
      {!canWrite ? <Empty>조회 전용 계정은 업로드할 수 없습니다.</Empty> : (
        <Section title="1. 파일 선택">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="파일(xlsx, xls, csv · 20MB 이하)"><input aria-label="업로드 파일" type="file" accept=".xlsx,.xls,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
            <Field label="헤더 행(0부터)"><input className="input w-20" type="number" min={0} max={50} value={headerRow} onChange={(e) => setHeaderRow(e.target.value)} /></Field>
            <button className="btn-primary" disabled={!file || busy} onClick={() => void doUpload()}>업로드·분석</button>
          </div>
        </Section>
      )}
      <ErrorBox error={err} />
      {busy && <Loading text="처리 중…" />}
      {an && (
        <Section title="2. 시트와 열 연결">
          <Warnings items={an.warnings} />
          <p className="text-xs text-slate-600">{an.file_name} · {an.source_type}{an.encoding ? ` · ${an.encoding}` : ""} · 이름이 정확히 같은 열만 자동 연결했습니다. 나머지는 직접 고르세요.</p>
          {an.sheets.length > 1 && (
            <Field label="시트">
              <select className="input w-48" value={sheet} onChange={(e) => { setSheet(e.target.value); setMapping(an.sheets.find((s) => s.name === e.target.value)?.suggested_mapping ?? {}); }}>
                {an.sheets.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.row_count}행)</option>)}
              </select>
            </Field>
          )}
          <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
            {an.target_fields.map((t) => (
              <label key={t.key} className="flex items-center gap-2 text-sm">
                <span className="w-32 shrink-0">{t.label}{t.required && <span className="text-red-600">*</span>}</span>
                <select className="input" aria-label={`${t.label} 열`} value={mapping[t.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [t.key]: e.target.value })}>
                  <option value="">(연결 안 함)</option>
                  {cur?.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            ))}
          </div>
          <h3 className="h2 mt-3">변환 옵션</h3>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Field label="비율 단위">
              <select className="input" value={opts.rate_unit} onChange={(e) => setOpts({ ...opts, rate_unit: e.target.value })}><option value="percent">% (87.745)</option><option value="ratio">비율 (0.87745)</option></select>
            </Field>
            <Field label="투찰률 기준(열이 없을 때)">
              <select className="input" value={opts.default_winning_rate_basis} onChange={(e) => setOpts({ ...opts, default_winning_rate_basis: e.target.value })}>
                <option value="">지정 안 함</option><option value="estimated_price">예정가격</option><option value="base_amount">기초금액</option><option value="presumed_price">추정가격</option>
              </select>
            </Field>
            <Field label="업무구분(열이 없을 때)">
              <select className="input" value={opts.procurement_type} onChange={(e) => setOpts({ ...opts, procurement_type: e.target.value })}>
                <option value="">지정 안 함</option><option value="construction">공사</option><option value="service">용역</option><option value="goods">물품</option><option value="foreign">외자</option>
              </select>
            </Field>
            <Field label="발주기관 구분(열이 없을 때)">
              <select className="input" value={opts.issuing_authority_type} onChange={(e) => setOpts({ ...opts, issuing_authority_type: e.target.value })}>
                <option value="">지정 안 함</option><option value="national">국가기관</option><option value="local">지방자치단체</option><option value="public_corp">공기업·준정부기관</option>
              </select>
            </Field>
          </div>
          {cur && cur.sample_rows.length > 0 && (
            <details className="mt-2"><summary className="cursor-pointer text-sm">원본 앞부분 보기</summary>
              <div className="table-wrap"><table className="tbl"><thead><tr>{cur.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{cur.sample_rows.map((r, i) => <tr key={i}>{cur.columns.map((c) => <td key={c}>{r[c]}</td>)}</tr>)}</tbody></table></div>
            </details>
          )}
          <button className="btn-primary mt-2" disabled={busy} onClick={() => void doPreview()}>3. 검사·미리보기</button>
        </Section>
      )}
      {pv && (
        <Section title="4. 미리보기 확인">
          <Warnings tone="amber" items={pv.mapping_errors} />
          <div className="mb-2 flex flex-wrap gap-2 text-sm">
            {Object.entries(ROW_STATUS).map(([k, [t, tone]]) => <Badge key={k} tone={tone}>{t} {pv.counts[k] ?? 0}</Badge>)}
            <Badge>경고 있음 {pv.counts.with_warnings ?? 0}</Badge><Badge>전체 {pv.counts.total ?? 0}</Badge>
          </div>
          <p className="mb-2 text-xs text-slate-600">'기존과 다름' 행은 체크해야만 기존 값을 바꿉니다. 체크하지 않으면 기존 데이터를 그대로 둡니다. 오류 행은 저장하지 않습니다.</p>
          <div className="table-wrap max-h-[28rem]">
            <table className="tbl">
              <thead><tr><th>행</th><th>상태</th><th>변경 반영</th><th>제외</th><th>공고번호</th><th>공고명</th><th>오류·경고·변경</th></tr></thead>
              <tbody>
                {pv.rows.map((r) => {
                  const [t, tone] = ROW_STATUS[r.status] ?? [r.status, "slate"];
                  return (
                    <tr key={r.row_number}>
                      <td>{r.row_number}</td><td><Badge tone={tone}>{t}</Badge></td>
                      <td>{r.status === "changed" && <input type="checkbox" aria-label={`${r.row_number}행 변경 반영`} checked={accept.has(r.row_number)} onChange={() => toggle(accept, setAccept, r.row_number)} />}</td>
                      <td>{r.status !== "invalid" && r.status !== "unchanged" && <input type="checkbox" aria-label={`${r.row_number}행 제외`} checked={skip.has(r.row_number)} onChange={() => toggle(skip, setSkip, r.row_number)} />}</td>
                      <td>{r.values.notice_number}</td><td className="max-w-xs truncate">{r.values.title}</td>
                      <td className="max-w-md whitespace-normal text-xs">
                        {r.errors.map((e) => <div key={e} className="text-red-700">{e}</div>)}
                        {r.warnings.map((e) => <div key={e} className="text-amber-700">{e}</div>)}
                        {r.diffs.map((d) => <div key={d.field}>{d.label}: {d.old ?? "(없음)"} → {d.new ?? "(없음)"}</div>)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <button className="btn-primary mt-2" disabled={busy || pv.mapping_errors.length > 0 || !!done} onClick={() => void doCommit()}>5. 저장</button>
          {done && (
            <div className="mt-2 rounded border border-green-300 bg-green-50 p-2 text-sm" role="status">
              저장했습니다: 추가 {done.inserted}, 갱신 {done.updated}, 변경 없음 {done.unchanged}, 파일 내 중복 {done.duplicate_in_file}, 오류 {done.rejected}, 제외 {done.skipped_by_user}, 변경 미반영 {done.changes_not_accepted}
              {" "}<a className="underline" href={`/api/imports/${an!.job_id}/report.csv`}>결과 보고서 CSV</a>
            </div>
          )}
        </Section>
      )}
      <Section title="업로드 이력">
        <ErrorBox error={jobs.error} onRetry={jobs.reload} />
        {jobs.loading ? <Loading /> : (jobs.data ?? []).length === 0 ? <Empty>업로드 이력이 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>파일</th><th>상태</th><th>업로드</th><th>행</th><th>저장</th><th>오류</th><th>중복</th><th></th></tr></thead>
              <tbody>
                {jobs.data!.map((j) => (
                  <tr key={j.id}>
                    <td>{j.id}</td><td>{j.file_name}</td><td>{JOB_STATUS[j.status] ?? j.status}</td><td>{dt(j.uploaded_at)}</td>
                    <td>{j.row_count ?? "-"}</td><td>{j.accepted_count ?? "-"}</td><td>{j.rejected_count ?? "-"}</td><td>{j.duplicate_count ?? "-"}</td>
                    <td className="space-x-1">
                      <a className="btn-secondary text-xs" href={`/api/imports/${j.id}/report.csv`}>보고서</a>
                      {canWrite && j.status === "committed" && <button className="btn-secondary text-xs" onClick={() => void rollback(j.id)}>되돌리기</button>}
                    </td>
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
