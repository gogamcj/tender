import { useState } from "react";
import { get, patch, post } from "../api/client";
import type { CalcResult } from "../api/types";
import { CalcResultView } from "../components/CalcResultView";
import { Badge, Empty, ErrorBox, Field, Loading, Section, Warnings } from "../components/ui";
import { useAuth } from "../lib/auth";
import { ko, label, parseWonInput, RULE_MODULE } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Rule {
  id: number; rule_code: string; rule_name: string; procurement_type: string; issuing_authority_type: string; contract_method: string; award_method: string;
  effective_from: string; effective_until: string | null; source_document: string | null; source_url: string | null; source_version: string;
  formula_definition: { module: string; params: Record<string, unknown> }; applicability: Record<string, unknown>; verification_status: string; notes: string | null;
}
interface SelectOut { selected_rule_code: string | null; matches: { rule_code: string; reasons: string[] }[]; undetermined: { rule_code: string; reasons: string[] }[]; warnings: string[]; evaluation: { rule_code: string; verification_status: string; definitive: boolean; flags: string[]; result: CalcResult } | null }

const TEMPLATE = JSON.stringify({
  rule_code: "EXAMPLE_RULE",
  rule_name: "예시: 적격심사 낙찰하한율(원문 확인 후 수정)",
  procurement_type: "construction",
  issuing_authority_type: "national",
  contract_method: "*",
  award_method: "적격심사",
  effective_from: "2026-01-01",
  effective_until: null,
  source_document: "규정 이름과 조항",
  source_url: null,
  formula_definition: { module: "simple_lower_limit", params: { lower_limit_rate_pct: "87.745", reference: "estimated_price" } },
  rounding_rule: { mode: "ceil", unit: 1 },
  applicability: { amount_basis: "presumed_price", amount_min: null, amount_max_exclusive: null },
  notes: null,
}, null, 2);

// 규칙 계산 값 표시(하한율·기준가격 등)
const PARAM_LABEL: Record<string, string> = { lower_limit_rate_pct: "하한율(%)", reference: "기준" };
const ruleParams = (p: Record<string, unknown>) =>
  Object.entries(p).map(([k, v]) => `${PARAM_LABEL[k] ?? k} ${label(String(v))}`).join(", ");

const tone = (s: string) => (s === "verified" ? "green" : s === "retired" ? "slate" : "amber");

export default function Rules() {
  const { isAdmin } = useAuth();
  const rules = useAsync(() => get<Rule[]>("/api/rules"), []);
  const [json, setJson] = useState(TEMPLATE);
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [ctx, setCtx] = useState({ announcement_date: "", procurement_type: "construction", issuing_authority_type: "national", contract_method: "", award_method: "", presumed_price: "", base_amount: "", estimated_price: "" });
  const [calc, setCalc] = useState({ reference_price: "", price_status: "user_assumed", a_value: "" });
  const [sel, setSel] = useState<SelectOut | null>(null);

  const create = async () => {
    setJsonErr(null);
    setErr(null);
    let body;
    try { body = JSON.parse(json); } catch { setJsonErr("JSON 형식이 올바르지 않습니다."); return; }
    try { await post("/api/rules", body); rules.reload(); } catch (e) { setErr(e as Error); }
  };
  const setStatus = async (id: number, s: string) => {
    setErr(null);
    try { await patch(`/api/rules/${id}/verification`, { verification_status: s }); rules.reload(); } catch (e) { setErr(e as Error); }
  };
  const select = async () => {
    setErr(null);
    const notice: Record<string, unknown> = { announcement_date: ctx.announcement_date || null };
    for (const [k, v] of Object.entries(ctx)) if (k !== "announcement_date" && v) notice[k] = k.endsWith("price") || k === "base_amount" ? parseWonInput(v) : v;
    const inputs = calc.reference_price ? { reference_price: parseWonInput(calc.reference_price), price_status: calc.price_status, ...(calc.a_value ? { a_value: parseWonInput(calc.a_value) } : {}) } : null;
    try { setSel(await post<SelectOut>("/api/rules/select", { notice, inputs })); } catch (e) { setErr(e as Error); }
  };

  return (
    <div>
      <h1 className="h1">규칙 관리</h1>
      <p className="mb-2 text-sm text-slate-600">낙찰하한율 등 계산 규칙은 원문 규정과 대조한 뒤 '검증됨'으로 바꾸세요. 미검증 규칙의 계산 결과는 확정값으로 표시하지 않습니다. 유효기간 밖의 공고에는 적용하지 않습니다(소급 적용 없음).</p>
      <ErrorBox error={err} />
      <Section title="등록된 규칙" actions={<a className="btn-secondary" href="/api/reports/rules.xlsx">XLSX</a>}>
        <ErrorBox error={rules.error} onRetry={rules.reload} />
        {rules.loading ? <Loading /> : (rules.data ?? []).length === 0 ? <Empty>등록된 규칙이 없습니다.</Empty> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>코드</th><th>이름</th><th>업무·기관</th><th>계약·낙찰방법</th><th>유효기간</th><th>계산</th><th>근거</th><th>검증</th></tr></thead>
              <tbody>
                {rules.data!.map((r) => (
                  <tr key={r.id}>
                    <td>{r.rule_code}</td><td className="whitespace-normal">{r.rule_name}</td>
                    <td>{label(r.procurement_type)} · {label(r.issuing_authority_type)}</td><td>{label(r.contract_method)} · {label(r.award_method)}</td>
                    <td>{r.effective_from} ~ {r.effective_until ?? "현재"}</td>
                    <td className="text-xs">{ko(RULE_MODULE, r.formula_definition.module)}<br />{ruleParams(r.formula_definition.params)}</td>
                    <td className="max-w-xs whitespace-normal text-xs">{r.source_document}{r.source_url && <> · <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">원문</a></>}</td>
                    <td>
                      {isAdmin ? (
                        <select className="input w-28" aria-label={`${r.rule_code} 검증 상태`} value={r.verification_status} onChange={(e) => void setStatus(r.id, e.target.value)}>
                          <option value="unverified">미검증</option><option value="verified">검증됨</option><option value="retired">사용 중지</option>
                        </select>
                      ) : <Badge tone={tone(r.verification_status)}>{label(r.verification_status)}</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {isAdmin && (
        <Section title="새 규칙 등록(JSON)">
          <p className="mb-1 text-xs text-slate-600">계산 방식(JSON 의 module 값): "simple_lower_limit" = 기준가격 × 하한율, "a_value_lower_limit" = A값 + (예정가격 − A값) × 하한율. 예시 값은 실제 규정이 아니므로 반드시 원문을 확인해 고치세요. 새 규칙은 '미검증'으로 등록됩니다.</p>
          <textarea className="input h-72 font-mono text-xs" aria-label="규칙 JSON" value={json} onChange={(e) => setJson(e.target.value)} />
          {jsonErr && <p className="text-sm text-red-700" role="alert">{jsonErr}</p>}
          <button className="btn-primary mt-2" onClick={() => void create()}>등록</button>
        </Section>
      )}
      <Section title="공고 조건으로 규칙 선택해 보기">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Field label="공고일"><input className="input" type="date" value={ctx.announcement_date} onChange={(e) => setCtx({ ...ctx, announcement_date: e.target.value })} /></Field>
          <Field label="업무구분">
            <select className="input" value={ctx.procurement_type} onChange={(e) => setCtx({ ...ctx, procurement_type: e.target.value })}>
              <option value="construction">공사</option><option value="service">용역</option><option value="goods">물품</option><option value="foreign">외자</option>
            </select>
          </Field>
          <Field label="발주기관 구분">
            <select className="input" value={ctx.issuing_authority_type} onChange={(e) => setCtx({ ...ctx, issuing_authority_type: e.target.value })}>
              <option value="national">국가기관</option><option value="local">지방자치단체</option><option value="public_corp">공기업·준정부기관</option>
            </select>
          </Field>
          <Field label="계약방법"><input className="input" value={ctx.contract_method} onChange={(e) => setCtx({ ...ctx, contract_method: e.target.value })} /></Field>
          <Field label="낙찰자 결정방법"><input className="input" value={ctx.award_method} onChange={(e) => setCtx({ ...ctx, award_method: e.target.value })} /></Field>
          <Field label="추정가격(원)"><input className="input" value={ctx.presumed_price} onChange={(e) => setCtx({ ...ctx, presumed_price: e.target.value })} /></Field>
          <Field label="기초금액(원)"><input className="input" value={ctx.base_amount} onChange={(e) => setCtx({ ...ctx, base_amount: e.target.value })} /></Field>
          <Field label="예정가격(원)"><input className="input" value={ctx.estimated_price} onChange={(e) => setCtx({ ...ctx, estimated_price: e.target.value })} /></Field>
        </div>
        <h3 className="h2 mt-2">선택된 규칙으로 계산(선택)</h3>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Field label="기준가격(원)"><input className="input" value={calc.reference_price} onChange={(e) => setCalc({ ...calc, reference_price: e.target.value })} /></Field>
          <Field label="기준가격 성격">
            <select className="input" value={calc.price_status} onChange={(e) => setCalc({ ...calc, price_status: e.target.value })}>
              <option value="user_assumed">사용자 가정</option><option value="actual">확정</option><option value="historical_estimate">과거 기반 예상</option><option value="scenario">시나리오</option>
            </select>
          </Field>
          <Field label="A값(원, 해당 시)"><input className="input" value={calc.a_value} onChange={(e) => setCalc({ ...calc, a_value: e.target.value })} /></Field>
        </div>
        <button className="btn-primary mt-2" onClick={() => void select()}>선택해 보기</button>
        {sel && (
          <div className="mt-3 text-sm">
            <p>선택된 규칙: {sel.selected_rule_code ? <b>{sel.selected_rule_code}</b> : <Badge tone="amber">없음</Badge>}</p>
            {sel.matches.length > 0 && <p className="text-xs">조건 일치: {sel.matches.map((m) => m.rule_code).join(", ")}</p>}
            {sel.undetermined.map((u) => <p key={u.rule_code} className="text-xs text-amber-700">판단 불가 {u.rule_code}: {u.reasons.join(", ")}</p>)}
            <Warnings items={sel.warnings} />
            {sel.evaluation && (
              <>
                {!sel.evaluation.definitive && <Warnings items={[`규칙 ${sel.evaluation.rule_code} 은(는) ${label(sel.evaluation.verification_status)} 상태라 계산 결과를 확정값으로 볼 수 없습니다.`]} />}
                <CalcResultView r={sel.evaluation.result} title="규칙 계산 결과" />
              </>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}
