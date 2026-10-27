import { useState } from "react";
import { get, post } from "../api/client";
import type { RecommendResult } from "../api/types";
import { GroupedBar, ChartFrame } from "../components/charts";
import { NoticePicker } from "../components/NoticePicker";
import { AssumptionBadge, Badge, Disclaimer, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { label, parseRateInput, parseWonInput, pct, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useNoticeParam } from "../lib/useNoticeParam";

interface CustomRow { kind: "sajeong" | "percentile" | "amount"; value: string; name: string }

export default function Scenarios() {
  const { canWrite } = useAuth();
  const [noticeId, setNoticeId] = useNoticeParam();
  const [period, setPeriod] = useState("3y");
  const [llr, setLlr] = useState("");
  const [aValue, setAValue] = useState("");
  const [baseAmount, setBaseAmount] = useState("");
  const [presets, setPresets] = useState({ conservative: "80", moderate: "50", aggressive: "20" });
  const [customs, setCustoms] = useState<CustomRow[]>([]);
  const [costId, setCostId] = useState("");
  const [vat, setVat] = useState("");
  const [r, setR] = useState<RecommendResult | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [inputErr, setInputErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const costs = useAsync(() => get<{ id: number; notice_id: number | null; summary: { complete: boolean; supply_total: string | null } }[]>("/api/costs"), [], canWrite);

  const run = async (save = false) => {
    setErr(null);
    setInputErr(null);
    if (llr && parseRateInput(llr) === null) return setInputErr("낙찰하한율은 숫자로 입력하세요.");
    if (aValue && parseWonInput(aValue) === null) return setInputErr("A값은 원 단위 숫자로 입력하세요.");
    if (baseAmount && !parseWonInput(baseAmount)) return setInputErr("기초금액은 원 단위 정수로 입력하세요.");
    const custom = [];
    for (const c of customs) {
      if (c.kind === "amount") {
        const v = parseWonInput(c.value);
        if (!v) return setInputErr("사용자 정의 금액은 원 단위 정수여야 합니다.");
        custom.push({ name: c.name || "직접 입력", bid_amount: v });
      } else {
        const v = parseRateInput(c.value);
        if (v === null) return setInputErr("사용자 정의 값은 숫자로 입력하세요.");
        custom.push(c.kind === "sajeong" ? { name: c.name || "가정 사정률", sajeong_rate_pct: v } : { name: c.name || "백분위", percentile: v });
      }
    }
    setLoading(true);
    try {
      setR(await post<RecommendResult>("/api/recommend", {
        notice_id: noticeId, period: period || null, lower_limit_rate_pct: parseRateInput(llr) ?? undefined, a_value: parseWonInput(aValue) ?? undefined,
        base_amount: parseWonInput(baseAmount) ?? undefined,
        presets, custom, cost_id: costId ? Number(costId) : undefined, bid_vat_included: vat === "" ? undefined : vat === "true", save,
      }));
    } catch (e) {
      setErr(e as Error);
    } finally {
      setLoading(false);
    }
  };

  // 금액끼리는 차이가 작아 막대로는 구분되지 않는다. 과거 사정률을 그대로 적용했을 때의 결과 건수를 비교한다.
  const chartRows = r ? r.scenarios.map((s) => ({ name: s.label === "사용자 정의" ? s.name : s.label, 하한미달: s.historical_check.below_lower_limit, 예정초과: s.historical_check.above_estimated_price })) : [];
  const profitRows = r ? r.scenarios.filter((s) => s.profit?.profit).map((s) => ({ name: s.label === "사용자 정의" ? s.name : s.label, 이익: Number(s.profit!.profit) })) : [];

  return (
    <div>
      <h1 className="h1">투찰 시나리오 비교</h1>
      <Section title="대상 공고와 가정">
        <NoticePicker value={noticeId} onChange={setNoticeId} />
        <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
          <Field label="과거 자료 기간">
            <select className="input" value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="1y">최근 1년</option><option value="3y">최근 3년</option><option value="">전체</option>
            </select>
          </Field>
          <Field label="낙찰하한율(%) 직접 입력" hint="비우면 등록 규칙 → 공고 기재값 순으로 찾습니다.">
            <input className="input" value={llr} onChange={(e) => setLlr(e.target.value)} />
          </Field>
          <Field label="A값(원, 공고 명시값)"><input className="input" value={aValue} onChange={(e) => setAValue(e.target.value)} /></Field>
          <Field label="기초금액(원, 공고문 확인값)" hint="비우면 수집된 기초금액을 씁니다. 공고 데이터는 바뀌지 않습니다.">
            <input className="input" value={baseAmount} onChange={(e) => setBaseAmount(e.target.value)} />
          </Field>
          <Field label="투찰금액 부가세">
            <select className="input" value={vat} onChange={(e) => setVat(e.target.value)}>
              <option value="">공고 값 따름</option><option value="true">포함</option><option value="false">별도</option>
            </select>
          </Field>
          {(["conservative", "moderate", "aggressive"] as const).map((k) => (
            <Field key={k} label={`${label(k === "conservative" ? "보수" : k === "moderate" ? "중립" : "공격")} 백분위`}>
              <input className="input" value={presets[k]} onChange={(e) => setPresets({ ...presets, [k]: e.target.value })} />
            </Field>
          ))}
          {canWrite && (
            <Field label="원가 자료(이익 계산)">
              <select className="input" value={costId} onChange={(e) => setCostId(e.target.value)}>
                <option value="">사용 안 함</option>
                {(costs.data ?? []).map((c) => <option key={c.id} value={c.id}>#{c.id} {c.notice_id ? `공고 ${c.notice_id}` : ""} {c.summary.complete ? "" : "(미완성)"}</option>)}
              </select>
            </Field>
          )}
        </div>
        <div className="mt-2">
          <div className="text-sm font-medium">사용자 정의 시나리오</div>
          {customs.map((c, i) => (
            <div key={i} className="mt-1 flex flex-wrap gap-1">
              <select className="input w-36" value={c.kind} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, kind: e.target.value as CustomRow["kind"] } : x)))}>
                <option value="sajeong">가정 사정률(%)</option><option value="percentile">과거 백분위</option><option value="amount">투찰금액(원)</option>
              </select>
              <input className="input w-40" placeholder="값" aria-label="사용자 정의 값" value={c.value} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
              <input className="input w-32" placeholder="이름" value={c.name} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <button className="btn-secondary" onClick={() => setCustoms(customs.filter((_, j) => j !== i))}>삭제</button>
            </div>
          ))}
          <button className="btn-secondary mt-1" onClick={() => setCustoms([...customs, { kind: "sajeong", value: "", name: "" }])}>+ 추가</button>
        </div>
        {inputErr && <p className="mt-2 text-sm text-red-700" role="alert">{inputErr}</p>}
        <div className="mt-3 flex gap-2">
          <button className="btn-primary" disabled={!noticeId || loading} onClick={() => void run()}>시나리오 계산</button>
          {canWrite && <button className="btn-secondary" disabled={!noticeId || loading} onClick={() => void run(true)}>계산 후 저장</button>}
        </div>
      </Section>
      {loading && <Loading />}
      <ErrorBox error={err} />
      {r && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <AssumptionBadge />
            {r.status === "insufficient_data" && <Badge tone="red">자료 부족: 보수·중립·공격 시나리오 없음</Badge>}
            <span>{r.notice.title} · 기초금액 {won(r.base_amount)}{r.base_amount_source === "user_input" ? " (직접 입력)" : ""}</span>
            <span>하한: {r.lower_limit.formula}, {pct(r.lower_limit.rate_pct)} ({r.lower_limit.source === "rule" ? `규칙 ${r.lower_limit.rule_code}${r.lower_limit.verified ? "" : " 미검증"}` : r.lower_limit.source === "notice" ? "공고 기재" : "사용자 입력"})</span>
            {r.analysis_run_id && <a className="text-blue-700 underline" href={`/api/reports/runs/${r.analysis_run_id}.xlsx`}>보고서 XLSX</a>}
          </div>
          <Warnings items={[...r.warnings, ...r.rule_selection.rule_selection_warnings]} />
          <p className="mb-2 text-sm text-slate-700">과거 표본: 같은 조건 {r.sample.n}건 (입찰마감 이전 개찰분만, 중앙값 사정률 {r.sample.sajeong_summary.median ?? "-"}%)</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {r.scenarios.map((s) => (
              <div key={s.name} className="card" data-testid="scenario-card">
                <div className="flex items-center justify-between"><h3 className="font-semibold">{s.label === "사용자 정의" ? s.name : s.label}</h3><AssumptionBadge /></div>
                <div className="mt-1 text-2xl font-bold">{won(s.candidate_amount)}</div>
                <dl className="mt-1 space-y-0.5 text-xs">
                  <div>방법: {s.method}</div>
                  <div>기초금액 대비 {pct(s.bid_rate_vs_base_amount, 4)}</div>
                  {s.assumed_estimated_price && <div>가정 예정가격 {won(Number(s.assumed_estimated_price).toFixed(0))} · 가정 하한 {won(Number(s.assumed_lower_limit).toFixed(0))}</div>}
                  <div>과거 사정률 {s.historical_check.n}건 적용 시: 하한 미달 {s.historical_check.below_lower_limit}건, 예정가격 초과 {s.historical_check.above_estimated_price}건</div>
                  {s.profit && <div>이익: {s.profit.profit ? `${won(s.profit.profit)} (${pct(s.profit.margin_pct, 2)})` : s.profit.status === "cost_incomplete" ? "원가 미완성" : "부가세 미확인"}</div>}
                </dl>
                {s.risk_flags.length > 0 && <Warnings items={s.risk_flags} />}
                <details className="mt-1 text-xs text-slate-600"><summary>계산 과정</summary><ol className="list-decimal pl-4">{s.explanation.steps.map((x) => <li key={x}>{x}</li>)}</ol></details>
              </div>
            ))}
          </div>
          {r.scenarios.length > 0 && (
            <ChartFrame title="후보 투찰금액별 결과 비교" meta={{ period: `${r.sample.period.from?.slice(0, 10) ?? "처음"} ~ ${r.sample.period.to.slice(0, 10)}`, n: r.sample.n, basis: `기초금액 ${won(r.base_amount)}`, sources: "등록된 과거 개찰 결과" }}
              table={{ columns: ["시나리오", "후보금액", "가정 하한", "하한 미달(과거)"], rows: r.scenarios.map((s) => [s.label === "사용자 정의" ? s.name : s.label, won(s.candidate_amount), won(s.assumed_lower_limit ? Number(s.assumed_lower_limit).toFixed(0) : null), `${s.historical_check.below_lower_limit}/${s.historical_check.n}`]) }}>
              <GroupedBar data={chartRows} keys={[{ key: "하한미달", label: "과거 사정률 적용 시 하한 미달(건)" }, { key: "예정초과", label: "예정가격 초과(건)" }]} unit="건" />
            </ChartFrame>
          )}
          {profitRows.length > 0 && r.cost && (
            <ChartFrame title="원가와 예상 이익 비교" meta={{ n: r.sample.n, basis: `총원가(공급가액) ${won(r.cost.supply_total)}`, sources: "사용자 입력 원가" }}
              table={{ columns: ["시나리오", "예상 이익"], rows: profitRows.map((p) => [p.name, won(String(p.이익))]) }}>
              <GroupedBar data={profitRows} keys={[{ key: "이익", label: "예상 이익(원)" }]} />
            </ChartFrame>
          )}
          <Disclaimer>{r.disclaimer}</Disclaimer>
        </>
      )}
    </div>
  );
}
