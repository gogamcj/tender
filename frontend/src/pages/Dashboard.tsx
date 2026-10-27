import { Link } from "react-router-dom";
import { get } from "../api/client";
import type { Notice } from "../api/types";
import { Badge, Empty, ErrorBox, Loading, Section, Stat } from "../components/ui";
import { dt, label, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface DashboardData {
  generated_at: string;
  notices: { total: number; pre_opening: number; needs_review: number; result_unconfirmed: number; pending_changes: number };
  upcoming_deadlines: Notice[];
  favorites: number;
  rules: { total: number; unverified: number };
  pdf_unreviewed: number;
  recent_collections: { id: number; source_name: string; operation: string; status: string; started_at: string; inserted: number; updated: number }[];
  recent_imports: { id: number; file_name: string; status: string; uploaded_at: string; rows: number; accepted: number }[];
  api_usage_today: { source_name: string; used: number; limit: number; protect_at: number }[];
  api_key_configured: boolean;
}

export default function Dashboard() {
  const { data, error, loading, reload } = useAsync(() => get<DashboardData>("/api/dashboard"), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} onRetry={reload} />;
  const n = data.notices;
  return (
    <div>
      <h1 className="h1">대시보드</h1>
      {/* 모바일에서 먼저 보이도록 숫자·경고를 맨 위에 둔다 */}
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="공고(최신 차수)" value={n.total.toLocaleString()} sub={`개찰 전 ${n.pre_opening.toLocaleString()}건`} />
        <Stat label="7일 내 마감" value={data.upcoming_deadlines.length} />
        <Stat label="검토 필요" value={n.needs_review + n.pending_changes} sub={`보류 변경 ${n.pending_changes}건`} tone={n.needs_review + n.pending_changes ? "warn" : undefined} />
        <Stat label="미검증 규칙" value={`${data.rules.unverified}/${data.rules.total}`} tone={data.rules.unverified ? "warn" : undefined} />
        <Stat label="PDF 미검토 항목" value={data.pdf_unreviewed} tone={data.pdf_unreviewed ? "warn" : undefined} />
      </div>
      {!data.api_key_configured && (
        <p className="mb-4 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          공공데이터포털 인증키가 설정되지 않아 자동 수집을 할 수 없습니다. 엑셀 업로드나 수동 입력은 쓸 수 있습니다.
        </p>
      )}
      <Section title="마감 임박 공고(7일 이내)">
        {data.upcoming_deadlines.length === 0 ? (
          <Empty>7일 안에 마감하는 공고가 없습니다.</Empty>
        ) : (
          <ul className="divide-y text-sm">
            {data.upcoming_deadlines.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center justify-between gap-1 py-1.5">
                <Link className="text-blue-700 hover:underline" to={`/notice-analysis?notice=${x.id}`}>
                  {x.favorite && <span aria-label="관심 공고">★ </span>}
                  {x.title}
                </Link>
                <span className="text-xs text-slate-600">
                  마감 {dt(x.bid_deadline)} · {x.agency_name ?? "-"} · {won(x.base_amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="오늘 API 사용량">
          <ul className="space-y-1 text-sm">
            {data.api_usage_today.map((u) => (
              <li key={u.source_name}>
                {u.source_name}: {u.used.toLocaleString()} / {u.limit.toLocaleString()}회
                {u.used >= u.protect_at && <Badge tone="amber">한도 보호</Badge>}
              </li>
            ))}
          </ul>
        </Section>
        <Section title="최근 수집">
          {data.recent_collections.length === 0 ? <Empty>수집 이력이 없습니다.</Empty> : (
            <ul className="space-y-1 text-sm">
              {data.recent_collections.map((j) => (
                <li key={j.id}>#{j.id} {j.operation} <Badge tone={j.status === "succeeded" ? "green" : j.status === "failed" ? "red" : "amber"}>{label(j.status)}</Badge> 추가 {j.inserted}·갱신 {j.updated}</li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="최근 업로드">
          {data.recent_imports.length === 0 ? <Empty>업로드 이력이 없습니다.</Empty> : (
            <ul className="space-y-1 text-sm">
              {data.recent_imports.map((j) => (
                <li key={j.id}>#{j.id} {j.file_name} <Badge>{j.status}</Badge> {j.accepted}/{j.rows}행</li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="바로 가기">
          <div className="flex flex-wrap gap-2 text-sm">
            <Link className="btn-secondary" to="/notices">공고 검색</Link>
            <Link className="btn-secondary" to="/favorites">관심 공고 {data.favorites}건</Link>
            <Link className="btn-secondary" to="/imports">엑셀 업로드</Link>
            <Link className="btn-secondary" to="/history">과거 결과 분석</Link>
          </div>
        </Section>
      </div>
      <p className="text-xs text-slate-500">기준 시각 {dt(data.generated_at)}</p>
    </div>
  );
}
