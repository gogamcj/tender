import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Loading({ text = "불러오는 중…" }: { text?: string }) {
  return <p className="py-4 text-sm text-slate-500" role="status">{text}</p>;
}

export function ErrorBox({ error, onRetry }: { error: Error | null; onRetry?: () => void }) {
  if (!error) return null;
  const status = error instanceof ApiError ? error.status : undefined;
  return (
    <div role="alert" className="my-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      <p className="font-medium">{error.message}</p>
      {status === 0 && <p className="mt-1">API 서버에 연결하지 못했습니다. 저장된 자료는 바뀌지 않았습니다.</p>}
      {onRetry && (
        <button className="btn-secondary mt-2" onClick={onRetry}>
          다시 시도
        </button>
      )}
    </div>
  );
}

/** 경고 목록. "CODE: 설명" 형식이면 설명만 크게 보이고 코드는 작게. */
export function Warnings({ items, tone = "amber" }: { items?: (string | null | undefined)[]; tone?: "amber" | "blue" }) {
  const list = (items ?? []).filter(Boolean) as string[];
  if (!list.length) return null;
  const cls = tone === "amber" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-900";
  return (
    <ul className={`my-2 space-y-1 rounded-md border p-3 text-sm ${cls}`} aria-label="경고">
      {list.map((w, i) => {
        const m = /^([A-Z_]+):\s*(.*)$/.exec(w);
        return (
          <li key={i}>
            {m ? (
              <>
                {m[2]} <span className="text-xs opacity-60">({m[1]})</span>
              </>
            ) : (
              w
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "blue" }) {
  const cls = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-green-100 text-green-800",
    amber: "bg-amber-100 text-amber-900",
    red: "bg-red-100 text-red-800",
    blue: "bg-blue-100 text-blue-800",
  }[tone];
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

export function AssumptionBadge() {
  return <Badge tone="amber">가정 기반 분석</Badge>;
}

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: string; error?: string | null }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && !error && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
      {error && <span className="mt-0.5 block text-xs text-red-700" role="alert">{error}</span>}
    </label>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "warn" }) {
  return (
    <div className={`card ${tone === "warn" ? "border-amber-300" : ""}`}>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-bold text-slate-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const last = Math.max(1, Math.ceil(total / size));
  return (
    <div className="mt-2 flex items-center justify-between text-sm">
      <span className="text-slate-600">
        전체 {total.toLocaleString()}건 · {page}/{last}쪽
      </span>
      <div className="space-x-1">
        <button className="btn-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          이전
        </button>
        <button className="btn-secondary" disabled={page >= last} onClick={() => onPage(page + 1)}>
          다음
        </button>
      </div>
    </div>
  );
}

export function Disclaimer({ children }: { children: ReactNode }) {
  return <p className="mt-3 rounded bg-slate-100 p-2 text-xs text-slate-600">{children}</p>;
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card mb-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="h2 mb-0">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}
