import { useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../api/client";
import { Badge, Empty, ErrorBox, Loading, Section } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt, label } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Run { id: number; analysis_type: string; notice_id: number | null; confidence_status: string | null; dataset_version: string | null; created_at: string }
interface Repro { run_id: number; data_changed: boolean; result_identical: boolean; note: string | null }

const TYPE: Record<string, string> = { recommend: "투찰 시나리오", statistics: "과거 결과 분석", reserve: "복수예비가격 분석" };

function Links({ base }: { base: string }) {
  return (
    <span className="space-x-1 whitespace-nowrap">
      <a className="btn-secondary text-xs" href={`${base}.xlsx`}>XLSX</a>
      <a className="btn-secondary text-xs" href={`${base}.csv`}>CSV</a>
    </span>
  );
}

export default function Reports() {
  const { canWrite } = useAuth();
  const runs = useAsync(() => get<Run[]>("/api/analysis/runs?limit=100"), []);
  const costs = useAsync(() => get<{ id: number; notice_id: number | null }[]>("/api/costs"), [], canWrite);
  const [repro, setRepro] = useState<Record<number, Repro | Error>>({});

  const reproduce = async (id: number) => {
    try { setRepro({ ...repro, [id]: await post<Repro>(`/api/analysis/runs/${id}/reproduce`) }); } catch (e) { setRepro({ ...repro, [id]: e as Error }); }
  };

  return (
    <div>
      <h1 className="h1">보고서 출력</h1>
      <p className="mb-3 text-sm text-slate-600">모든 보고서 첫 시트(CSV 는 머리말)에 작성 시각, 데이터 출처, 분석 조건, 주의 문구가 들어갑니다. 엑셀에서 수식으로 실행되지 않도록 '=' 등으로 시작하는 값은 글자로 저장합니다.</p>
      <Section title="공고 목록">
        <p className="text-sm">공고 검색 화면에서 조건을 정한 뒤 XLSX·CSV 버튼을 누르면 그 조건 그대로 내려받습니다. <Link className="text-blue-700 underline" to="/notices">공고 검색으로 이동</Link></p>
        <div className="mt-2">전체 최근 공고: <Links base="/api/reports/notices" /></div>
      </Section>
      <Section title="저장한 분석 결과">
        <ErrorBox error={runs.error} onRetry={runs.reload} />
        {runs.loading ? <Loading /> : (runs.data ?? []).length === 0 ? <Empty>저장한 분석이 없습니다. 투찰 시나리오 비교 등에서 '저장'을 선택해 실행하세요.</Empty> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>#</th><th>종류</th><th>공고</th><th>신뢰 수준</th><th>데이터 버전</th><th>저장 시각</th><th>내려받기</th><th>재현</th></tr></thead>
              <tbody>
                {runs.data!.map((r) => {
                  const rp = repro[r.id];
                  return (
                    <tr key={r.id}>
                      <td>{r.id}</td><td>{TYPE[r.analysis_type] ?? r.analysis_type}</td>
                      <td>{r.notice_id ? <Link className="text-blue-700 underline" to={`/notice-analysis?notice=${r.notice_id}`}>{r.notice_id}</Link> : "-"}</td>
                      <td>{label(r.confidence_status)}</td><td className="font-mono text-xs">{r.dataset_version?.slice(0, 12) ?? "-"}</td><td>{dt(r.created_at)}</td>
                      <td><Links base={`/api/reports/runs/${r.id}`} /></td>
                      <td className="whitespace-normal text-xs">
                        {!rp ? <button className="btn-secondary text-xs" onClick={() => void reproduce(r.id)}>다시 계산</button>
                          : rp instanceof Error ? <span className="text-red-700">{rp.message}</span>
                          : <>{rp.result_identical ? <Badge tone="green">결과 동일</Badge> : <Badge tone="amber">결과 다름</Badge>} {rp.data_changed && <Badge tone="blue">데이터 변경됨</Badge>} {rp.note}</>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {canWrite && (
        <Section title="원가·손익">
          {costs.loading ? <Loading /> : (costs.data ?? []).length === 0 ? <Empty>원가 자료가 없습니다.</Empty> : (
            <ul className="space-y-1 text-sm">
              {costs.data!.map((c) => <li key={c.id}>원가 #{c.id} (공고 {c.notice_id ?? "-"}) <Links base={`/api/reports/costs/${c.id}`} /></li>)}
            </ul>
          )}
          <p className="mt-1 text-xs text-slate-500">투찰금액별 손익을 함께 넣으려면 원가·수익성 분석 화면에서 계산 후 내려받으세요.</p>
        </Section>
      )}
      <Section title="규칙 목록"><Links base="/api/reports/rules" /></Section>
    </div>
  );
}
