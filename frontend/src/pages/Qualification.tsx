import { useEffect, useState } from "react";
import { get, put } from "../api/client";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Disclaimer, Empty, ErrorBox, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { label } from "../lib/format";
import { useNoticeParam } from "../lib/useNoticeParam";

interface Item { item_code: string; item_name: string; max_score: string | null; score: string | null; status: string; basis: string | null; source_reference: string | null }
interface Range { min: string; max: string | null; meaning: string; verdict: string | null }
interface Evaluation { confirmed_score: string; expected_score: string; total_max_score: string | null; unknown_items: { item_name: string }[]; range_with_expected: Range; range_confirmed_only: Range; warnings: string[]; note: string }

export default function Qualification() {
  const { canWrite } = useAuth();
  const [noticeId, setNoticeId] = useNoticeParam();
  const [items, setItems] = useState<Item[]>([]);
  const [threshold, setThreshold] = useState("");
  const [ev, setEv] = useState<Evaluation | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!noticeId) return;
    setLoading(true);
    setErr(null);
    get<{ items: Item[]; evaluation: Evaluation }>(`/api/notices/${noticeId}/qualification`)
      .then((r) => { setItems(r.items); setEv(r.evaluation); })
      .catch((e) => setErr(e))
      .finally(() => setLoading(false));
  }, [noticeId]);

  const loadTemplate = async () => {
    const t = await get<{ items: { item_code: string; item_name: string }[] }>("/api/qualification/templates");
    const have = new Set(items.map((i) => i.item_code));
    setItems([...items, ...t.items.filter((x) => !have.has(x.item_code)).map((x) => ({ ...x, max_score: null, score: null, status: "unknown", basis: null, source_reference: null }))]);
  };
  const upd = (i: number, k: keyof Item, v: string) => {
    setSaved(false);
    setItems(items.map((x, j) => (j === i ? { ...x, [k]: v === "" ? null : v, ...(k === "status" && v === "unknown" ? { score: null } : {}) } : x)));
  };
  const save = async () => {
    setErr(null);
    try {
      const r = await put<{ items: Item[]; evaluation: Evaluation }>(`/api/notices/${noticeId}/qualification`, { items, pass_threshold: threshold || null });
      setItems(r.items);
      setEv(r.evaluation);
      setSaved(true);
    } catch (e) {
      setErr(e as Error);
    }
  };
  const verdict = (v: string | null) => v && <Badge tone={v === "pass" ? "green" : v === "fail" ? "red" : "amber"}>{label(v)}</Badge>;

  return (
    <div>
      <h1 className="h1">적격심사·자격 체크</h1>
      <Section title="대상 공고"><NoticePicker value={noticeId} onChange={setNoticeId} /></Section>
      {!noticeId && <Empty>공고를 고르세요.</Empty>}
      {loading && <Loading />}
      <ErrorBox error={err} />
      {noticeId && !loading && (
        <Section title="점검 항목" actions={canWrite && <button className="btn-secondary" onClick={() => void loadTemplate()}>기본 항목 불러오기</button>}>
          <p className="mb-2 text-xs text-slate-600">배점은 공고의 심사기준에서 확인해 입력하세요. 확인하지 못한 항목은 '미확인'으로 두면 0점이나 만점으로 계산하지 않습니다.</p>
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>항목</th><th>배점</th><th>상태</th><th>점수</th><th>근거</th>{canWrite && <th></th>}</tr></thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={i}>
                    <td><input className="input w-44" aria-label="항목 이름" value={it.item_name} disabled={!canWrite} onChange={(e) => upd(i, "item_name", e.target.value)} /></td>
                    <td><input className="input w-20" aria-label={`${it.item_name} 배점`} value={it.max_score ?? ""} disabled={!canWrite} onChange={(e) => upd(i, "max_score", e.target.value)} /></td>
                    <td>
                      <select className="input w-24" aria-label={`${it.item_name} 상태`} value={it.status} disabled={!canWrite} onChange={(e) => upd(i, "status", e.target.value)}>
                        <option value="confirmed">확인</option><option value="expected">예상</option><option value="unknown">미확인</option>
                      </select>
                    </td>
                    <td><input className="input w-20" aria-label={`${it.item_name} 점수`} value={it.score ?? ""} disabled={!canWrite || it.status === "unknown"} placeholder={it.status === "unknown" ? "미확인" : ""} onChange={(e) => upd(i, "score", e.target.value)} /></td>
                    <td><input className="input w-56" value={it.basis ?? ""} disabled={!canWrite} onChange={(e) => upd(i, "basis", e.target.value)} placeholder="예: 공고문 5쪽" /></td>
                    {canWrite && <td><button className="btn-secondary text-xs" onClick={() => setItems(items.filter((_, j) => j !== i))}>삭제</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {canWrite && (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <button className="btn-secondary" onClick={() => setItems([...items, { item_code: `item_${Date.now()}`, item_name: "새 항목", max_score: null, score: null, status: "unknown", basis: null, source_reference: null }])}>+ 항목</button>
              <label><span className="label">통과 기준점</span><input className="input w-24" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="예: 95" /></label>
              <button className="btn-primary" onClick={() => void save()}>저장·평가</button>
              {saved && <span className="text-sm text-green-700">저장했습니다.</span>}
            </div>
          )}
        </Section>
      )}
      {ev && (
        <Section title="평가">
          <div className="grid gap-3 md:grid-cols-2">
            {([["확인+예상 점수 기준", ev.range_with_expected], ["확인 점수만 인정", ev.range_confirmed_only]] as const).map(([t, rg]) => (
              <div key={t} className="rounded border p-3">
                <div className="text-sm text-slate-600">{t}</div>
                <div className="text-xl font-bold">{rg.min} ~ {rg.max ?? "상한 미상"}점 {verdict(rg.verdict)}</div>
                <div className="text-xs text-slate-500">{rg.meaning}</div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-sm">확인 {ev.confirmed_score}점 · 예상 {ev.expected_score}점 · 총 배점 {ev.total_max_score ?? "미상"} · 미확인 {ev.unknown_items.length}개</p>
          <Warnings items={ev.warnings} />
          <Disclaimer>{ev.note} 이 결과는 공식 기관의 확정 판정이 아닙니다.</Disclaimer>
        </Section>
      )}
    </div>
  );
}
