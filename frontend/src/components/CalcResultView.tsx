import type { CalcResult } from "../api/types";
import { won } from "../lib/format";
import { Badge, Warnings } from "./ui";

export function CalcResultView({ r, title }: { r: CalcResult; title?: string }) {
  const value = r.unit === "KRW" ? won(r.value) : `${r.value}%`;
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="calc-result">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">{title ?? r.name}</span>
        <Badge tone={r.assumption_based ? "amber" : "green"}>{r.status_label}</Badge>
      </div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
      <div className="mt-1 text-xs text-slate-600">산식: {r.formula}</div>
      {r.extra?.unrounded && r.extra.unrounded !== r.value && <div className="text-xs text-slate-600">처리 전 값: {r.extra.unrounded}</div>}
      <details className="mt-1 text-xs text-slate-600">
        <summary>입력값</summary>
        <pre className="whitespace-pre-wrap">{JSON.stringify(r.inputs, null, 2)}</pre>
      </details>
      <Warnings items={r.warnings} />
    </div>
  );
}
