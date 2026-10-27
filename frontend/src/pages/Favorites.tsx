import { useState } from "react";
import { Link } from "react-router-dom";
import { del, get, patch } from "../api/client";
import type { Notice } from "../api/types";
import { Badge, Empty, ErrorBox, Loading, Section } from "../components/ui";
import { useAuth } from "../lib/auth";
import { day, dt, label, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface Fav { id: number; memo: string | null; created_at: string; notice: Notice }
interface SavedFilter { id: number; name: string; filter_type: string; criteria: Record<string, unknown>; created_at: string }

const FILTER_TYPE: Record<string, string> = { search: "공고 검색", analysis: "분석 조건", interest: "관심 조건" };

export default function Favorites() {
  const { canWrite } = useAuth();
  const favs = useAsync(() => get<Fav[]>("/api/favorites"), []);
  const filters = useAsync(() => get<SavedFilter[]>("/api/saved-filters"), []);
  const [memo, setMemo] = useState<Record<number, string>>({});
  const [err, setErr] = useState<Error | null>(null);

  const run = async (fn: () => Promise<unknown>, reload: () => void) => {
    setErr(null);
    try { await fn(); reload(); } catch (e) { setErr(e as Error); }
  };
  const criteriaText = (c: Record<string, unknown>) =>
    Object.entries(c).filter(([, v]) => v !== "" && v !== null && v !== undefined).map(([k, v]) => `${k}=${String(v)}`).join(", ") || "(조건 없음)";

  return (
    <div>
      <h1 className="h1">관심 공고·즐겨찾기</h1>
      <ErrorBox error={err} />
      <Section title="관심 공고">
        <ErrorBox error={favs.error} onRetry={favs.reload} />
        {favs.loading ? <Loading /> : (favs.data ?? []).length === 0 ? <Empty>관심 공고가 없습니다. 공고 검색 화면의 ☆ 버튼으로 추가하세요.</Empty> : (
          <ul className="divide-y">
            {favs.data!.map((f) => {
              const n = f.notice;
              const soon = n.bid_deadline && new Date(n.bid_deadline).getTime() - Date.now() < 3 * 86400_000 && new Date(n.bid_deadline).getTime() > Date.now();
              return (
                <li key={f.id} className="py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link className="font-medium text-blue-700 underline" to={`/notice-analysis?notice=${n.id}`}>{n.title}</Link>
                    <Badge>{label(n.phase)}</Badge>
                    {soon && <Badge tone="red">마감 임박</Badge>}
                  </div>
                  <div className="text-xs text-slate-600">{n.notice_number}-{n.notice_revision} · {n.agency_name} · 기초 {won(n.base_amount)} · 공고 {day(n.announcement_date)} · 마감 {dt(n.bid_deadline)}</div>
                  {canWrite ? (
                    <div className="mt-1 flex flex-wrap gap-2">
                      <input className="input flex-1" aria-label="메모" placeholder="메모" value={memo[f.id] ?? f.memo ?? ""} onChange={(e) => setMemo({ ...memo, [f.id]: e.target.value })} />
                      <button className="btn-secondary" onClick={() => void run(() => patch(`/api/favorites/${f.id}`, { memo: memo[f.id] ?? f.memo ?? "" }), favs.reload)}>메모 저장</button>
                      <button className="btn-secondary" onClick={() => void run(() => del(`/api/favorites/${f.id}`), favs.reload)}>해제</button>
                    </div>
                  ) : f.memo && <p className="text-sm">{f.memo}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </Section>
      <Section title="저장한 조건">
        <ErrorBox error={filters.error} onRetry={filters.reload} />
        {filters.loading ? <Loading /> : (filters.data ?? []).length === 0 ? <Empty>저장한 조건이 없습니다. 공고 검색 화면에서 '조건 저장'을 누르세요.</Empty> : (
          <div className="table-wrap">
            <table className="tbl">
              <thead><tr><th>이름</th><th>종류</th><th>조건</th><th>저장일</th>{canWrite && <th></th>}</tr></thead>
              <tbody>
                {filters.data!.map((f) => (
                  <tr key={f.id}>
                    <td>{f.name}</td><td>{FILTER_TYPE[f.filter_type] ?? f.filter_type}</td>
                    <td className="max-w-md whitespace-normal text-xs">{criteriaText(f.criteria)}</td><td>{day(f.created_at)}</td>
                    {canWrite && <td><button className="btn-secondary text-xs" onClick={() => void run(() => del(`/api/saved-filters/${f.id}`), filters.reload)}>삭제</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
