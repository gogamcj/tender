import { useState, type FormEvent } from "react";
import { post } from "../api/client";
import type { CalcResult } from "../api/types";
import { CalcResultView } from "../components/CalcResultView";
import { ErrorBox, Field } from "../components/ui";
import { parseRateInput, parseWonInput } from "../lib/format";

type Tab = "lower" | "sajeong" | "assumed" | "rate" | "amount" | "vat" | "reserve";
const TABS: { key: Tab; title: string }[] = [
  { key: "lower", title: "낙찰하한금액" },
  { key: "assumed", title: "가정 예정가격" },
  { key: "sajeong", title: "사정률" },
  { key: "rate", title: "투찰률" },
  { key: "amount", title: "투찰금액" },
  { key: "vat", title: "부가가치세" },
  { key: "reserve", title: "예비가격 평균" },
];

const STATUS_OPTIONS = [
  ["actual", "확정(개찰 후 공개값)"],
  ["user_assumed", "사용자 가정"],
  ["scenario", "시나리오"],
] as const;

const ROUNDING = [
  ["", "규칙 모름(원 미만 그대로 표시)"],
  ["truncate", "절사"],
  ["floor", "내림"],
  ["ceil", "올림"],
  ["half_up", "반올림"],
] as const;

function MoneyInput({ label, value, onChange, name }: { label: string; value: string; onChange: (v: string) => void; name: string }) {
  const bad = value !== "" && parseWonInput(value) === null;
  return (
    <Field label={label} error={bad ? "원 단위 숫자로 입력하세요." : null}>
      <input className="input" inputMode="numeric" name={name} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

function RateInput({ label, value, onChange, name }: { label: string; value: string; onChange: (v: string) => void; name: string }) {
  const bad = value !== "" && parseRateInput(value) === null;
  return (
    <Field label={`${label}(%)`} error={bad ? "숫자로 입력하세요(예: 87.745)." : null}>
      <input className="input" inputMode="decimal" name={name} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export default function Calculator() {
  const [tab, setTab] = useState<Tab>("lower");
  const [v, setV] = useState<Record<string, string>>({ price_status: "user_assumed", basis: "estimated_price", rounding: "", unit: "1", vat_included: "true" });
  const [result, setResult] = useState<{ main: CalcResult; extra?: CalcResult } | null>(null);
  const [vatResult, setVatResult] = useState<Record<string, string | string[]> | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const s = (k: string) => (x: string) => setV({ ...v, [k]: x });
  const rounding = v.rounding ? { mode: v.rounding, unit: Number(v.unit || 1) } : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setVatResult(null);
    const m = (k: string) => parseWonInput(v[k] ?? "");
    const r = (k: string) => parseRateInput(v[k] ?? "");
    try {
      switch (tab) {
        case "lower":
          setResult({ main: await post<CalcResult>("/api/calc/lower-limit", { reference_price: m("ref"), lower_limit_rate: r("llr"), price_status: v.price_status, reference_basis: v.basis, rounding }) });
          break;
        case "assumed":
          setResult({ main: await post<CalcResult>("/api/calc/assumed-estimated-price", { base_amount: m("base"), sajeong_rate: r("sj"), rounding }) });
          break;
        case "sajeong":
          setResult({ main: await post<CalcResult>("/api/calc/sajeong-rate", { base_amount: m("base"), estimated_price: m("est"), price_status: v.price_status }) });
          break;
        case "rate":
          setResult({ main: await post<CalcResult>("/api/calc/bid-rate", { bid_amount: m("bid"), reference_amount: m("ref"), basis: v.basis, price_status: v.price_status }) });
          break;
        case "amount":
          setResult({ main: await post<CalcResult>("/api/calc/bid-amount", { reference_amount: m("ref"), rate: r("rate"), basis: v.basis, price_status: v.price_status, rounding }) });
          break;
        case "vat":
          setVatResult(await post("/api/calc/vat", { amount: m("amount"), vat_included: v.vat_included === "" ? null : v.vat_included === "true", stated_vat_amount: m("stated") ?? undefined, rounding }));
          break;
        case "reserve": {
          const prices = (v.prices ?? "").split(/[\s\n]+/).map((x) => parseWonInput(x)).filter((x): x is string => !!x);
          const out = await post<CalcResult & { sajeong?: CalcResult }>("/api/calc/reserve-average", { selected_prices: prices, base_amount: m("base") ?? undefined, price_status: v.price_status, rounding });
          setResult({ main: out, extra: out.sajeong });
          break;
        }
      }
    } catch (err) {
      setError(err as Error);
    }
  };

  const needsBasis = tab === "lower" || tab === "rate" || tab === "amount";
  const needsStatus = tab !== "assumed" && tab !== "vat";
  return (
    <div>
      <h1 className="h1">투찰금액 계산기</h1>
      <p className="mb-2 text-sm text-slate-600">
        모든 계산은 서버의 계산 엔진(정밀 소수)으로 합니다. 기준 가격이 확정값이 아니면 결과에 "가정 기반 분석"이 표시됩니다.
      </p>
      <div className="mb-3 flex flex-wrap gap-1" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "btn-primary" : "btn-secondary"} onClick={() => { setTab(t.key); setResult(null); setVatResult(null); setError(null); }}>
            {t.title}
          </button>
        ))}
      </div>
      <form className="card grid gap-3 md:grid-cols-3" onSubmit={submit}>
        {tab === "lower" && <><MoneyInput name="ref" label="기준가격(원)" value={v.ref ?? ""} onChange={s("ref")} /><RateInput name="llr" label="낙찰하한율" value={v.llr ?? ""} onChange={s("llr")} /></>}
        {tab === "assumed" && <><MoneyInput name="base" label="기초금액(원)" value={v.base ?? ""} onChange={s("base")} /><RateInput name="sj" label="가정 사정률" value={v.sj ?? ""} onChange={s("sj")} /></>}
        {tab === "sajeong" && <><MoneyInput name="base" label="기초금액(원)" value={v.base ?? ""} onChange={s("base")} /><MoneyInput name="est" label="예정가격(원)" value={v.est ?? ""} onChange={s("est")} /></>}
        {tab === "rate" && <><MoneyInput name="bid" label="투찰금액(원)" value={v.bid ?? ""} onChange={s("bid")} /><MoneyInput name="ref" label="기준금액(원)" value={v.ref ?? ""} onChange={s("ref")} /></>}
        {tab === "amount" && <><MoneyInput name="ref" label="기준금액(원)" value={v.ref ?? ""} onChange={s("ref")} /><RateInput name="rate" label="투찰률" value={v.rate ?? ""} onChange={s("rate")} /></>}
        {tab === "vat" && (
          <>
            <MoneyInput name="amount" label="금액(원)" value={v.amount ?? ""} onChange={s("amount")} />
            <Field label="부가세 포함 여부">
              <select className="input" value={v.vat_included} onChange={(e) => s("vat_included")(e.target.value)}>
                <option value="true">포함</option><option value="false">별도</option><option value="">모름(계산하지 않음)</option>
              </select>
            </Field>
            <MoneyInput name="stated" label="공고에 적힌 세액(있으면)" value={v.stated ?? ""} onChange={s("stated")} />
          </>
        )}
        {tab === "reserve" && (
          <>
            <Field label="추첨된 예비가격(줄마다 하나)">
              <textarea className="input h-28" aria-label="추첨된 예비가격" value={v.prices ?? ""} onChange={(e) => s("prices")(e.target.value)} />
            </Field>
            <MoneyInput name="base" label="기초금액(사정률 계산용, 선택)" value={v.base ?? ""} onChange={s("base")} />
          </>
        )}
        {needsBasis && (
          <Field label="기준금액 종류">
            <select className="input" value={v.basis} onChange={(e) => s("basis")(e.target.value)}>
              <option value="estimated_price">예정가격</option><option value="base_amount">기초금액</option><option value="presumed_price">추정가격</option>
            </select>
          </Field>
        )}
        {needsStatus && (
          <Field label="기준 가격 상태">
            <select className="input" value={v.price_status} onChange={(e) => s("price_status")(e.target.value)}>
              {STATUS_OPTIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </Field>
        )}
        {tab !== "sajeong" && tab !== "rate" && (
          <Field label="원 단위 처리" hint="공고·규정에서 확인한 처리 방식만 고르세요.">
            <div className="flex gap-1">
              <select className="input" value={v.rounding} onChange={(e) => s("rounding")(e.target.value)} aria-label="처리 방식">
                {ROUNDING.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
              {v.rounding && <input className="input w-24" aria-label="처리 단위" value={v.unit} onChange={(e) => s("unit")(e.target.value.replace(/\D/g, ""))} />}
            </div>
          </Field>
        )}
        <div className="flex items-end"><button className="btn-primary">계산</button></div>
      </form>
      <ErrorBox error={error} />
      {result && <CalcResultView r={result.main} />}
      {result?.extra && <CalcResultView r={result.extra} title="사정률" />}
      {vatResult && (
        <div className="mt-3 rounded-md border bg-slate-50 p-3 text-sm" data-testid="vat-result">
          <div>공급가액 <strong>{vatResult.supply_amount}</strong>원 · 세액 <strong>{vatResult.vat_amount}</strong>원 · 합계 <strong>{vatResult.total_amount}</strong>원</div>
          <div className="text-xs text-slate-600">세액 근거: {vatResult.source === "stated" ? "공고 명시값" : "계산값"}</div>
          {Array.isArray(vatResult.warnings) && vatResult.warnings.map((w) => <p key={w} className="text-xs text-amber-800">⚠ {w}</p>)}
        </div>
      )}
    </div>
  );
}
