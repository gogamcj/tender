import { useState } from "react";
import { ApiError, get, patch, post, upload } from "../api/client";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Empty, ErrorBox, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { APPLY_STATUS, dt, FIELD_LABEL, ko, label, yesNo } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useNoticeParam } from "../lib/useNoticeParam";

interface Cand {
  id: number; field_name: string; raw_text: string | null; value: string | null; page_number: number | null; bbox: number[] | null;
  table_ref: string | null; confidence: number | null; method: string; review_status: string; reviewed_value: string | null; final_value: string | null;
}
interface FieldInfo { label: string; kind: string; target: string | null; candidates: Cand[]; distinct_values: string[]; conflict: boolean; found: boolean; notice_value?: Record<string, string | null> | null }
interface Doc { id: number; file_name: string; page_count: number; text_layer: string; notice_id: number | null; uploaded_at: string; extraction_count: number; unreviewed_count: number; fields: Record<string, FieldInfo>; note: string; warnings?: string[] }

function conf(c: number | null) {
  if (c === null) return <Badge>직접 입력</Badge>;
  return <Badge tone={c >= 0.85 ? "green" : c >= 0.6 ? "amber" : "red"}>신뢰도 {c.toFixed(2)}</Badge>;
}

export default function PdfAnalysis() {
  const { canWrite } = useAuth();
  const [noticeId, setNoticeId] = useNoticeParam();
  const [docId, setDocId] = useState<number | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [pageText, setPageText] = useState<{ page: number; text: string } | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [applyFields, setApplyFields] = useState<Record<string, boolean>>({});
  const [overwrite, setOverwrite] = useState<Record<string, boolean>>({});
  const [applyReport, setApplyReport] = useState<Record<string, { status: string; old?: string; new?: string; reason?: string }> | null>(null);
  const docs = useAsync(() => get<{ id: number; file_name: string; page_count: number; text_layer: string; notice_id: number | null; uploaded_at: string }[]>("/api/pdfs"), []);
  const doc = useAsync(() => get<Doc>(`/api/pdfs/${docId}`), [docId], !!docId);

  const [info, setInfo] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    setInfo(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  };
  const onFile = (f: File | undefined) =>
    f && act(async () => {
      try {
        const d = await upload<Doc>("/api/pdfs", f, noticeId ? { notice_id: String(noticeId) } : {});
        setDocId(d.id);
      } catch (e) {
        // 같은 파일을 다시 올리면 새로 만들지 않고 기존 분석 결과를 연다.
        const existing = e instanceof ApiError && e.status === 409 ? (e.data as { detail?: { document_id?: number } })?.detail?.document_id : undefined;
        if (!existing) throw e;
        setDocId(existing);
        setInfo(`이미 올린 파일이라 기존 분석 결과(#${existing})를 열었습니다.`);
      }
      docs.reload();
    });
  const review = (c: Cand, status: string, value?: string) =>
    act(async () => {
      await patch(`/api/pdfs/${docId}/extractions/${c.id}`, { review_status: status, value });
      doc.reload();
    });
  const showPage = (p: number) => act(async () => setPageText({ page: p, text: (await get<{ text: string }>(`/api/pdfs/${docId}/pages/${p}`)).text }));
  const link = () => act(async () => {
    await patch(`/api/pdfs/${docId}`, { notice_id: noticeId });
    doc.reload();
  });
  const apply = () => act(async () => {
    const fields = Object.keys(applyFields).filter((k) => applyFields[k]);
    const r = await post<{ report: typeof applyReport }>(`/api/pdfs/${docId}/apply`, { fields, overwrite: Object.keys(overwrite).filter((k) => overwrite[k]) });
    setApplyReport(r.report);
    doc.reload();
  });

  return (
    <div>
      <h1 className="h1">공고문 파일 분석</h1>
      <Section title="PDF 올리기">
        <p className="mb-2 text-sm text-slate-600">텍스트가 있는 PDF 만 분석합니다(스캔 이미지는 지원하지 않음). 추출 값은 검토한 뒤에만 공고에 반영됩니다.</p>
        <div className="mb-2"><NoticePicker value={noticeId} onChange={setNoticeId} /></div>
        {canWrite && <input type="file" accept="application/pdf,.pdf" aria-label="PDF 파일" disabled={busy} onChange={(e) => void onFile(e.target.files?.[0])} />}
      </Section>
      <ErrorBox error={err} />
      {info && <p className="mb-2 text-sm text-blue-800" role="status">{info}</p>}
      <Section title="올린 파일">
        {docs.loading ? <Loading /> : (docs.data?.length ?? 0) === 0 ? <Empty>올린 PDF 가 없습니다.</Empty> : (
          <ul className="text-sm">
            {docs.data!.map((d) => (
              <li key={d.id}>
                <button className={`underline ${d.id === docId ? "font-bold" : "text-blue-700"}`} onClick={() => { setDocId(d.id); setApplyReport(null); setPageText(null); }}>
                  #{d.id} {d.file_name}
                </button>{" "}
                <span className="text-xs text-slate-500">{d.page_count}쪽 · {d.text_layer === "none" ? "텍스트 없음" : "텍스트 있음"} · 공고 {d.notice_id ?? "미연결"} · {dt(d.uploaded_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      {doc.loading && <Loading />}
      <ErrorBox error={doc.error} />
      {doc.data && (
        <>
          <Warnings items={[doc.data.note, ...(doc.data.warnings ?? [])]} tone="blue" />
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <span>연결된 공고: {doc.data.notice_id ?? "없음"}</span>
            {canWrite && noticeId && noticeId !== doc.data.notice_id && <button className="btn-secondary" onClick={() => void link()}>공고 #{noticeId} 에 연결</button>}
            <span>미검토 {doc.data.unreviewed_count}/{doc.data.extraction_count}</span>
          </div>
          <div className="space-y-3">
            {Object.entries(doc.data.fields).map(([name, f]) => (
              <div key={name} className={`card ${f.conflict ? "border-red-300" : ""}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">{f.label} {f.conflict && <Badge tone="red">값 불일치</Badge>} {!f.found && <Badge>못 찾음</Badge>}</h3>
                  {f.notice_value && <span className="text-xs text-slate-600">공고 현재 값: {Object.entries(f.notice_value).map(([k, v]) => `${FIELD_LABEL[k] ?? k} ${yesNo(v) ?? "비어 있음"}`).join(", ")}</span>}
                </div>
                {f.candidates.map((c) => (
                  <div key={c.id} className="mt-2 rounded border p-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>{yesNo(c.value) ?? "(해석 불가)"}</strong>
                      {conf(c.confidence)}
                      <Badge tone={c.review_status === "confirmed" || c.review_status === "corrected" ? "green" : c.review_status === "rejected" ? "red" : "slate"}>{label(c.review_status)}</Badge>
                      {c.final_value && c.review_status === "corrected" && <span>→ 수정 값: <strong>{yesNo(c.final_value)}</strong></span>}
                      {c.page_number && <button className="text-xs text-blue-700 underline" onClick={() => void showPage(c.page_number!)}>{c.page_number}쪽 원문{c.table_ref ? ` (표 ${c.table_ref})` : ""}</button>}
                    </div>
                    {c.raw_text && <div className="mt-1 break-all text-xs text-slate-600">원문: “{c.raw_text}”</div>}
                    {canWrite && (
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <button className="btn-secondary text-xs" disabled={busy || c.value === null} onClick={() => void review(c, "confirmed")}>확인</button>
                        <input className="input w-48 text-xs" placeholder="고친 값" aria-label={`${f.label} 수정 값`} value={edits[c.id] ?? ""} onChange={(e) => setEdits({ ...edits, [c.id]: e.target.value })} />
                        <button className="btn-secondary text-xs" disabled={busy || !edits[c.id]} onClick={() => void review(c, "corrected", edits[c.id])}>수정</button>
                        <button className="btn-secondary text-xs" disabled={busy} onClick={() => void review(c, "rejected")}>기각</button>
                      </div>
                    )}
                  </div>
                ))}
                {canWrite && (f.target || name === "reserve_range") && (
                  <div className="mt-2 flex flex-wrap gap-3 text-xs">
                    <label><input type="checkbox" checked={!!applyFields[name]} onChange={(e) => setApplyFields({ ...applyFields, [name]: e.target.checked })} /> 공고에 반영</label>
                    <label><input type="checkbox" checked={!!overwrite[name]} onChange={(e) => setOverwrite({ ...overwrite, [name]: e.target.checked })} /> 기존 값이 달라도 덮어쓰기</label>
                  </div>
                )}
              </div>
            ))}
          </div>
          {canWrite && (
            <div className="mt-3">
              <button className="btn-primary" disabled={busy || !doc.data.notice_id || !Object.values(applyFields).some(Boolean)} onClick={() => void apply()}>
                검토한 값 공고에 반영
              </button>
              {!doc.data.notice_id && <span className="ml-2 text-sm text-slate-600">먼저 공고를 연결하세요.</span>}
            </div>
          )}
          {applyReport && (
            <Section title="반영 결과">
              <ul className="text-sm">
                {Object.entries(applyReport).map(([k, r]) => (
                  <li key={k}>{doc.data?.fields[k]?.label ?? FIELD_LABEL[k] ?? k}: <Badge tone={r.status === "applied" ? "green" : r.status === "pending" ? "amber" : "slate"}>{ko(APPLY_STATUS, r.status)}</Badge> {r.old !== undefined && `${yesNo(r.old) ?? "없음"} → ${yesNo(r.new)}`} {r.reason}</li>
                ))}
              </ul>
            </Section>
          )}
          {pageText && (
            <Section title={`${pageText.page}쪽 원문`} actions={<button className="btn-secondary text-xs" onClick={() => setPageText(null)}>닫기</button>}>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{pageText.text}</pre>
            </Section>
          )}
        </>
      )}
    </div>
  );
}
