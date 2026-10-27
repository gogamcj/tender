// 차트 공통 틀: 모든 차트에 분석 기간·표본 수·기준 금액·출처를 표시하고, 표본이 적으면 경고한다.
// 색은 검증된 범주 팔레트의 앞 3개만 쓴다(그 이상은 표로 본다). 차트마다 '표로 보기'를 제공한다.
import { useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a"];
const GRID = "#e5e7eb";
const AXIS = { fontSize: 11, fill: "#52514e" };
export const SMALL_SAMPLE = 30;
export const TINY_SAMPLE = 10;

export interface ChartMeta {
  period?: string;
  n: number;
  basis?: string;
  sources?: Record<string, number> | string;
  warnings?: string[];
}

function sourcesText(s: ChartMeta["sources"]): string {
  if (!s) return "-";
  if (typeof s === "string") return s;
  const e = Object.entries(s);
  return e.length ? e.map(([k, v]) => `${k} ${v}건`).join(", ") : "-";
}

export function ChartFrame({
  title,
  meta,
  table,
  children,
}: {
  title: string;
  meta: ChartMeta;
  table: { columns: string[]; rows: (string | number | null)[][] };
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const small = meta.n < SMALL_SAMPLE;
  return (
    <figure className="card mb-4" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <figcaption className="h2 mb-0">{title}</figcaption>
        <button className="btn-secondary text-xs" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? "차트로 보기" : "표로 보기"}
        </button>
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-slate-600 sm:grid-cols-4" data-testid="chart-meta">
        <div><dt className="inline">분석 기간: </dt><dd className="inline">{meta.period || "전체"}</dd></div>
        <div><dt className="inline">표본 수: </dt><dd className="inline">{meta.n.toLocaleString()}건</dd></div>
        <div><dt className="inline">기준: </dt><dd className="inline">{meta.basis || "-"}</dd></div>
        <div><dt className="inline">출처: </dt><dd className="inline">{sourcesText(meta.sources)}</dd></div>
      </dl>
      {small && (
        <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900" role="note">
          ⚠ 표본이 {meta.n}건으로 {meta.n < TINY_SAMPLE ? "매우 " : ""}적습니다. 일반화하지 말고 참고용으로만 보세요.
        </p>
      )}
      {meta.warnings?.map((w) => (
        <p key={w} className="mt-1 text-xs text-amber-800">⚠ {w}</p>
      ))}
      <div className="mt-3">
        {asTable || meta.n === 0 ? (
          meta.n === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">표시할 자료가 없습니다.</p>
          ) : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                </thead>
                <tbody>
                  {table.rows.map((r, i) => (
                    <tr key={i}>{r.map((c, j) => <td key={j}>{c ?? "-"}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="h-64 w-full">{children}</div>
        )}
      </div>
    </figure>
  );
}

export interface BarDatum {
  name: string;
  value: number;
  extra?: string;
}

export function SimpleBar({ data, unit, color = SERIES[0], valueLabel }: { data: BarDatum[]; unit?: string; color?: string; valueLabel: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="name" tick={AXIS} interval="preserveStartEnd" tickLine={false} />
        <YAxis tick={AXIS} width={56} tickLine={false} axisLine={false} unit={unit} />
        <Tooltip formatter={(v: number) => [`${v.toLocaleString()}${unit ?? ""}`, valueLabel]} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
        <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TrendLine({ data, unit, valueLabel }: { data: { name: string; value: number; n?: number }[]; unit?: string; valueLabel: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="name" tick={AXIS} tickLine={false} />
        <YAxis tick={AXIS} width={56} tickLine={false} axisLine={false} unit={unit} domain={["auto", "auto"]} />
        <Tooltip
          formatter={(v: number, _k, item) => [`${v}${unit ?? ""} (n=${(item.payload as { n?: number }).n ?? "-"})`, valueLabel]}
        />
        <Line type="monotone" dataKey="value" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 5 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** 막대 여러 계열(최대 3개). 계열 이름은 범례로 표시한다. */
/** 축 눈금용 짧은 금액 표기(억·만). 정확한 값은 툴팁과 표에서 본다. */
export function compactNumber(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e8) return `${+(v / 1e8).toFixed(a >= 1e9 ? 0 : 1)}억`;
  if (a >= 1e4) return `${+(v / 1e4).toFixed(0)}만`;
  return v.toLocaleString();
}

export function GroupedBar({ data, keys, unit }: { data: Record<string, string | number>[]; keys: { key: string; label: string }[]; unit?: string }) {
  const shown = keys.slice(0, 3);
  return (
    <div className="flex h-full flex-col">
      <ul className="mb-1 flex flex-wrap gap-3 text-xs text-slate-700" aria-label="범례">
        {shown.map((k, i) => (
          <li key={k.key} className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[i] }} />
            {k.label}
          </li>
        ))}
      </ul>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }} barGap={2}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="name" tick={AXIS} tickLine={false} />
            <YAxis tick={AXIS} width={56} tickLine={false} axisLine={false} unit={unit} tickFormatter={compactNumber} allowDecimals={false} />
            <Tooltip formatter={(v: number, name) => [`${Number(v).toLocaleString()}${unit ?? ""}`, name]} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
            {shown.map((k, i) => (
              <Bar key={k.key} dataKey={k.key} name={k.label} fill={SERIES[i]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
