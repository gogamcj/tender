import { useState } from "react";
import { get, qs } from "../api/client";
import type { Notice, Page } from "../api/types";
import { won } from "../lib/format";

/** 공고 선택: 공고 ID 직접 입력 또는 공고명·번호 검색. */
export function NoticePicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Notice[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const search = async () => {
    setErr(null);
    try {
      const r = await get<Page<Notice>>(`/api/notices${qs({ q, size: 10 })}`);
      setItems(r.items);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="w-28">
          <span className="label">공고 ID</span>
          <input
            className="input"
            inputMode="numeric"
            aria-label="공고 ID"
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value ? Number(e.target.value.replace(/\D/g, "")) || null : null)}
          />
        </label>
        <label className="min-w-0 flex-1">
          <span className="label">또는 공고명·공고번호로 찾기</span>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void search()} />
        </label>
        <button type="button" className="btn-secondary" onClick={() => void search()}>
          찾기
        </button>
      </div>
      {err && <p className="text-sm text-red-700">{err}</p>}
      {items && (
        <ul className="max-h-48 overflow-y-auto rounded border text-sm">
          {items.length === 0 && <li className="p-2 text-slate-500">검색 결과가 없습니다.</li>}
          {items.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className={`block w-full px-2 py-1 text-left hover:bg-blue-50 ${n.id === value ? "bg-blue-100" : ""}`}
                onClick={() => {
                  onChange(n.id);
                  setItems(null);
                }}
              >
                <span className="text-slate-500">#{n.id}</span> {n.title} <span className="text-xs text-slate-500">({n.notice_number}, {won(n.base_amount)})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
