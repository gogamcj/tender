import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { del, get, post, qs } from "../api/client";
import type { Notice, Page } from "../api/types";
import { Badge, Empty, ErrorBox, Loading, Pager } from "../components/ui";
import { useAuth } from "../lib/auth";
import { DATA_STATUS, day, dt, ko, label, parseWonInput, pct, won } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export interface SearchForm {
  q: string;
  agency: string;
  industry: string;
  region: string;
  procurement_type: string;
  award_method: string;
  amount_min: string;
  amount_max: string;
  date_from: string;
  date_to: string;
  has_result: string;
  phase: string;
  sort: string;
}

export const EMPTY_SEARCH: SearchForm = {
  q: "", agency: "", industry: "", region: "", procurement_type: "", award_method: "", amount_min: "", amount_max: "",
  date_from: "", date_to: "", has_result: "", phase: "", sort: "-announcement_date",
};

export function searchQuery(f: SearchForm): Record<string, string | undefined> {
  return {
    ...f,
    amount_min: parseWonInput(f.amount_min) ?? undefined,
    amount_max: parseWonInput(f.amount_max) ?? undefined,
  };
}

export default function NoticeSearch() {
  const { canWrite } = useAuth();
  const [form, setForm] = useState<SearchForm>(EMPTY_SEARCH);
  const [applied, setApplied] = useState<SearchForm>(EMPTY_SEARCH);
  const [page, setPage] = useState(1);
  const [formError, setFormError] = useState<string | null>(null);
  const [favs, setFavs] = useState<Record<number, number>>({});
  const list = useAsync(() => get<Page<Notice>>(`/api/notices${qs({ ...searchQuery(applied), page, size: 20 })}`), [applied, page]);
  const favList = useAsync(() => get<{ id: number; notice: Notice }[]>("/api/favorites"), []);
  const saved = useAsync(() => get<{ id: number; name: string; criteria: Partial<SearchForm> }[]>("/api/saved-filters?filter_type=search"), []);
  const loadSaved = (id: string) => {
    const f = saved.data?.find((x) => String(x.id) === id);
    if (!f) return;
    const next = { ...EMPTY_SEARCH, ...f.criteria };
    setForm(next);
    setApplied(next);
    setPage(1);
  };
  const saveCurrent = async () => {
    const name = window.prompt("저장할 검색 조건 이름");
    if (!name) return;
    try {
      await post("/api/saved-filters", { name, filter_type: "search", criteria: form });
      saved.reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };
  const favMap: Record<number, number> = { ...Object.fromEntries((favList.data ?? []).map((f) => [f.notice.id, f.id])), ...favs };

  const set = (k: keyof SearchForm) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    for (const k of ["amount_min", "amount_max"] as const) {
      if (form[k] && parseWonInput(form[k]) === null) {
        setFormError("금액은 원 단위 숫자로 입력하세요(예: 100,000,000).");
        return;
      }
    }
    setFormError(null);
    setPage(1);
    setApplied(form);
  };
  const toggleFav = async (n: Notice) => {
    const fid = favMap[n.id];
    try {
      if (fid) {
        await del(`/api/favorites/${fid}`);
        setFavs({ ...favs, [n.id]: 0 });
      } else {
        const r = await post<{ id: number }>("/api/favorites", { notice_id: n.id });
        setFavs({ ...favs, [n.id]: r.id });
      }
    } catch (e) {
      alert((e as Error).message);
    }
  };
  const exportQs = qs(searchQuery(applied));

  return (
    <div>
      <h1 className="h1">입찰공고 검색</h1>
      <form onSubmit={submit} className="card mb-3 grid grid-cols-2 gap-2 md:grid-cols-4" aria-label="검색 조건">
        <label className="col-span-2"><span className="label">검색어(공고명·공고번호)</span><input className="input" value={form.q} onChange={set("q")} /></label>
        <label><span className="label">기관</span><input className="input" value={form.agency} onChange={set("agency")} /></label>
        <label><span className="label">업종(공종)</span><input className="input" value={form.industry} onChange={set("industry")} /></label>
        <label><span className="label">지역</span><input className="input" value={form.region} onChange={set("region")} /></label>
        <label><span className="label">업무구분</span>
          <select className="input" value={form.procurement_type} onChange={set("procurement_type")}>
            <option value="">전체</option><option value="construction">공사</option><option value="service">용역</option><option value="goods">물품</option><option value="foreign">외자</option>
          </select>
        </label>
        <label><span className="label">낙찰자 결정방법</span><input className="input" value={form.award_method} onChange={set("award_method")} placeholder="예: 적격심사" /></label>
        <label><span className="label">개찰 결과</span>
          <select className="input" value={form.has_result} onChange={set("has_result")}>
            <option value="">전체</option><option value="true">있음</option><option value="false">없음</option>
          </select>
        </label>
        <label><span className="label">금액 이상(원)</span><input className="input" inputMode="numeric" value={form.amount_min} onChange={set("amount_min")} /></label>
        <label><span className="label">금액 이하(원)</span><input className="input" inputMode="numeric" value={form.amount_max} onChange={set("amount_max")} /></label>
        <label><span className="label">공고일 시작</span><input className="input" type="date" value={form.date_from} onChange={set("date_from")} /></label>
        <label><span className="label">공고일 끝</span><input className="input" type="date" value={form.date_to} onChange={set("date_to")} /></label>
        <label><span className="label">정렬</span>
          <select className="input" value={form.sort} onChange={set("sort")}>
            <option value="-announcement_date">공고일 최신순</option><option value="-opening_date">개찰일 최신순</option>
            <option value="-base_amount">금액 큰 순</option><option value="base_amount">금액 작은 순</option>
          </select>
        </label>
        <div className="col-span-2 flex flex-wrap items-end gap-2 md:col-span-3">
          <button className="btn-primary">검색</button>
          <button type="button" className="btn-secondary" onClick={() => { setForm(EMPTY_SEARCH); setApplied(EMPTY_SEARCH); setPage(1); }}>초기화</button>
          {canWrite && <button type="button" className="btn-secondary" onClick={() => void saveCurrent()}>조건 저장</button>}
          {(saved.data ?? []).length > 0 && (
            <select className="input w-40" aria-label="저장한 검색 조건" value="" onChange={(e) => loadSaved(e.target.value)}>
              <option value="">저장한 조건…</option>
              {saved.data!.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          )}
          <a className="btn-secondary" href={`/api/reports/notices.xlsx${exportQs}`}>XLSX</a>
          <a className="btn-secondary" href={`/api/reports/notices.csv${exportQs}`}>CSV</a>
        </div>
        {formError && <p className="col-span-full text-sm text-red-700" role="alert">{formError}</p>}
      </form>
      <ErrorBox error={list.error} onRetry={list.reload} />
      {list.loading && <Loading />}
      {list.data && (list.data.items.length === 0 ? <Empty>조건에 맞는 공고가 없습니다.</Empty> : (
        <>
          {/* 모바일: 카드 목록 */}
          <ul className="space-y-2 md:hidden" aria-label="공고 목록(모바일)">
            {list.data.items.map((n) => (
              <li key={n.id} className="card">
                <Link to={`/notice-analysis?notice=${n.id}`} className="font-medium text-blue-700">{n.title}</Link>
                <div className="mt-1 text-sm font-bold">{won(n.base_amount)}</div>
                <div className="text-xs text-slate-600">{n.agency_name} · 마감 {dt(n.bid_deadline)} · {label(n.procurement_type)}</div>
                {n.result && <div className="text-xs">사정률 {pct(n.result.actual_sajeong_rate)} · 낙찰률 {pct(n.result.winning_rate)}</div>}
              </li>
            ))}
          </ul>
          {/* PC: 표 */}
          <div className="table-wrap card hidden p-0 md:block">
            <table className="tbl" aria-label="공고 목록">
              <thead>
                <tr><th>관심</th><th>공고번호</th><th>공고명</th><th>기관</th><th>구분</th><th>결정방법</th><th className="text-right">기초금액</th><th>공고일</th><th>마감</th><th>상태</th><th className="text-right">사정률</th><th className="text-right">낙찰률</th></tr>
              </thead>
              <tbody>
                {list.data.items.map((n) => (
                  <tr key={n.id}>
                    <td>
                      {canWrite && (
                        <button aria-label={favMap[n.id] ? "관심 해제" : "관심 추가"} onClick={() => void toggleFav(n)} className="text-amber-500">
                          {favMap[n.id] ? "★" : "☆"}
                        </button>
                      )}
                    </td>
                    <td>{n.notice_number}-{n.notice_revision}</td>
                    <td className="max-w-xs truncate"><Link to={`/notice-analysis?notice=${n.id}`} className="text-blue-700 hover:underline">{n.title}</Link></td>
                    <td>{n.agency_name ?? "-"}</td>
                    <td>{label(n.procurement_type)}</td>
                    <td>{n.award_method ?? "-"}</td>
                    <td className="text-right">{won(n.base_amount)}</td>
                    <td>{day(n.announcement_date)}</td>
                    <td>{dt(n.bid_deadline)}</td>
                    <td><Badge tone={n.data_status === "collected" || n.data_status === "verified" ? "green" : "amber"}>{n.data_status_label || ko(DATA_STATUS, n.data_status)}</Badge></td>
                    <td className="text-right">{pct(n.result?.actual_sajeong_rate)}</td>
                    <td className="text-right">{pct(n.result?.winning_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} size={20} total={list.data.total} onPage={setPage} />
        </>
      ))}
    </div>
  );
}
