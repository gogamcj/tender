import { useState } from "react";
import { get, post, put } from "../api/client";
import { ChartFrame, GroupedBar } from "../components/charts";
import { NoticePicker } from "../components/NoticePicker";
import { Badge, Empty, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { parseRateInput, parseWonInput, pct, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useNoticeParam } from "../lib/useNoticeParam";

const ITEMS: [string, string][] = [
  ["material_cost", "재료비"], ["labor_cost", "노무비"], ["equipment_cost", "장비비"], ["subcontract_cost", "외주비"], ["transport_cost", "운송비"],
  ["site_overhead", "현장 관리비"], ["general_overhead", "일반관리비"], ["statutory_costs", "법정 경비(보험료 등)"], ["other_costs", "기타 비용"],
];
interface CostRow { id: number; notice_id: number | null; notes: string | null; target_profit: string | null; target_profit_rate: string | null; summary: { items: Record<string, { label: string; value: string | null }>; known_total: string; missing_items: string[]; complete: boolean; vat_treatment: string | null; supply_total: string | null; warnings: string[] } }
interface Profit { status: string; profit: string | null; margin_pct: string | null; bid_supply_amount?: string; flags: string[]; warnings: string[] }

export default function Costs() {
  const { canWrite } = useAuth();
  const [noticeId, setNoticeId] = useNoticeParam();
  const list = useAsync(() => get<CostRow[]>("/api/costs"), [], canWrite);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<Record<string, string>>({ vat_treatment: "excluded" });
  const [formErr, setFormErr] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [bids, setBids] = useState("");
  const [vat, setVat] = useState("true");
  const [evalOut, setEvalOut] = useState<{ be: Record<string, string | string[]>; rows: { bid: string; p: Profit }[] } | null>(null);

  if (!canWrite) return <div><h1 className="h1">원가·수익성 분석</h1><Empty>조회 전용 계정은 원가 자료를 볼 수 없습니다.</Empty></div>;

  const load = (c: CostRow) => {
    setEditId(c.id);
    const f: Record<string, string> = { vat_treatment: c.summary.vat_treatment ?? "", target_profit: c.target_profit ?? "", target_profit_rate: c.target_profit_rate ?? "", notes: c.notes ?? "" };
    for (const [k] of ITEMS) f[k] = c.summary.items[k]?.value ?? "";
    setForm(f);
    if (c.notice_id) setNoticeId(c.notice_id);
    setEvalOut(null);
  };
  const body = () => {
    const b: Record<string, unknown> = { notice_id: noticeId, vat_treatment: form.vat_treatment || null, notes: form.notes || null };
    for (const [k, t] of [...ITEMS, ["target_profit", "목표 이익"]]) {
      const v = form[k] ?? "";
      if (v === "") { b[k] = null; continue; }
      const p = parseWonInput(v);
      if (p === null) throw new Error(`${t}: 원 단위 숫자로 입력하세요.`);
      b[k] = p;
    }
    if (form.target_profit_rate) {
      const r = parseRateInput(form.target_profit_rate);
      if (r === null) throw new Error("목표 이익률은 숫자로 입력하세요.");
      b.target_profit_rate = r;
    }
    return b;
  };
  const save = async () => {
    setFormErr(null);
    setErr(null);
    let b;
    try { b = body(); } catch (e) { setFormErr((e as Error).message); return; }
    try {
      const r = editId ? await put<CostRow>(`/api/costs/${editId}`, b) : await post<CostRow>("/api/costs", b);
      setEditId(r.id);
      list.reload();
    } catch (e) { setErr(e as Error); }
  };
  const evaluate = async () => {
    if (!editId) return;
    setErr(null);
    try {
      const amounts = bids.split(/[\s,\n]+/).map((x) => parseWonInput(x)).filter((x): x is string => !!x).slice(0, 10);
      const vatIncluded = vat === "" ? null : vat === "true";
      const be = await post<{ break_even: Record<string, string | string[]> }>("/api/costs/evaluate", { cost_id: editId, bid_vat_included: vatIncluded });
      const rows = await Promise.all(amounts.map(async (a) => ({ bid: a, p: (await post<{ profit: Profit }>("/api/costs/evaluate", { cost_id: editId, bid_amount: a, bid_vat_included: vatIncluded })).profit })));
      setEvalOut({ be: be.break_even, rows });
    } catch (e) { setErr(e as Error); }
  };
  const current = list.data?.find((c) => c.id === editId);
  const reportQs = evalOut ? `?${[...evalOut.rows.map((r) => `bid_amounts=${r.bid}`), vat ? `bid_vat_included=${vat}` : ""].filter(Boolean).join("&")}` : "";

  return (
    <div>
      <h1 className="h1">원가·수익성 분석</h1>
      <p className="mb-2 text-sm text-slate-600">원가 자료는 작성자와 관리자만 볼 수 있습니다. 해당 없는 항목은 0 을 입력하세요(빈칸은 '미입력'으로 보고 이익을 계산하지 않습니다). 업체 내부 예상 비용이며 법정 원가계산이 아닙니다.</p>
      <Section title="내 원가 자료">
        {list.loading ? <Loading /> : (list.data ?? []).length === 0 ? <Empty>등록한 원가 자료가 없습니다.</Empty> : (
          <ul className="text-sm">
            {list.data!.map((c) => (
              <li key={c.id}><button className={`underline ${c.id === editId ? "font-bold" : "text-blue-700"}`} onClick={() => load(c)}>#{c.id}</button> 공고 {c.notice_id ?? "-"} · 총원가 {won(c.summary.supply_total ?? c.summary.known_total)} {!c.summary.complete && <Badge tone="amber">미입력 {c.summary.missing_items.length}</Badge>}</li>
            ))}
          </ul>
        )}
        <button className="btn-secondary mt-2" onClick={() => { setEditId(null); setForm({ vat_treatment: "excluded" }); setEvalOut(null); }}>새 원가 자료</button>
      </Section>
      <Section title={editId ? `원가 #${editId} 수정` : "새 원가 자료"}>
        <div className="mb-2"><NoticePicker value={noticeId} onChange={setNoticeId} /></div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          {ITEMS.map(([k, t]) => (
            <Field key={k} label={`${t}(원)`}><input className="input" inputMode="numeric" aria-label={t} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></Field>
          ))}
          <Field label="원가의 부가세 처리">
            <select className="input" value={form.vat_treatment ?? ""} onChange={(e) => setForm({ ...form, vat_treatment: e.target.value })}>
              <option value="excluded">부가세 별도</option><option value="included">부가세 포함</option><option value="">미지정</option>
            </select>
          </Field>
          <Field label="목표 이익(원)"><input className="input" value={form.target_profit ?? ""} onChange={(e) => setForm({ ...form, target_profit: e.target.value })} /></Field>
          <Field label="목표 이익률(%)"><input className="input" value={form.target_profit_rate ?? ""} onChange={(e) => setForm({ ...form, target_profit_rate: e.target.value })} /></Field>
        </div>
        {formErr && <p className="mt-2 text-sm text-red-700" role="alert">{formErr}</p>}
        <button className="btn-primary mt-2" onClick={() => void save()}>저장</button>
        {current && <Warnings items={current.summary.warnings} />}
      </Section>
      <ErrorBox error={err} />
      {editId && (
        <Section title="투찰금액별 손익">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <Field label="비교할 투찰금액(쉼표·줄바꿈, 최대 10개)"><textarea className="input h-20" value={bids} onChange={(e) => setBids(e.target.value)} /></Field>
            <Field label="투찰금액 부가세">
              <select className="input" value={vat} onChange={(e) => setVat(e.target.value)}><option value="true">포함</option><option value="false">별도</option><option value="">모름</option></select>
            </Field>
            <div className="flex items-end gap-2">
              <button className="btn-primary" onClick={() => void evaluate()}>계산</button>
              {evalOut && <a className="btn-secondary" href={`/api/reports/costs/${editId}.xlsx${reportQs}`}>보고서 XLSX</a>}
            </div>
          </div>
          {evalOut && (
            <>
              <dl className="mt-3 grid grid-cols-1 gap-2 text-sm md:grid-cols-3">
                <div className="rounded bg-slate-50 p-2"><dt className="text-xs text-slate-500">손익분기 투찰금액</dt><dd className="font-bold">{won(evalOut.be.break_even_bid as string)}</dd></div>
                <div className="rounded bg-slate-50 p-2"><dt className="text-xs text-slate-500">목표 이익 최소 금액</dt><dd className="font-bold">{won(evalOut.be.min_bid_for_target_profit as string)}</dd></div>
                <div className="rounded bg-slate-50 p-2"><dt className="text-xs text-slate-500">목표 이익률 최소 금액</dt><dd className="font-bold">{won(evalOut.be.min_bid_for_target_margin as string)}</dd></div>
              </dl>
              <Warnings items={evalOut.be.warnings as string[] | undefined} />
              {evalOut.rows.length > 0 && (
                <>
                  <div className="table-wrap mt-2">
                    <table className="tbl"><thead><tr><th>투찰금액</th><th>공급가액</th><th>이익</th><th>이익률</th><th>표시</th></tr></thead>
                      <tbody>{evalOut.rows.map((r) => <tr key={r.bid}><td>{won(r.bid)}</td><td>{won(r.p.bid_supply_amount)}</td><td>{r.p.profit ? won(r.p.profit) : r.p.status}</td><td>{pct(r.p.margin_pct, 2)}</td><td className="whitespace-normal text-xs">{[...r.p.flags, ...r.p.warnings].join(" / ")}</td></tr>)}</tbody>
                    </table>
                  </div>
                  <ChartFrame title="원가와 예상 이익 비교" meta={{ n: evalOut.rows.length, basis: `총원가(공급가액) ${won(current?.summary.supply_total)}`, sources: "사용자 입력 원가" }}
                    table={{ columns: ["투찰금액", "이익"], rows: evalOut.rows.map((r) => [won(r.bid), r.p.profit ? won(r.p.profit) : "-"]) }}>
                    <GroupedBar data={evalOut.rows.map((r) => ({ name: won(r.bid, ""), 원가: Number(current?.summary.supply_total ?? 0), 이익: Number(r.p.profit ?? 0) }))} keys={[{ key: "원가", label: "총원가(공급가액)" }, { key: "이익", label: "예상 이익" }]} />
                  </ChartFrame>
                </>
              )}
            </>
          )}
        </Section>
      )}
    </div>
  );
}
