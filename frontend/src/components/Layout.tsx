import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { label } from "../lib/format";

export const MENUS: { path: string; title: string }[] = [
  { path: "/", title: "대시보드" },
  { path: "/notices", title: "입찰공고 검색" },
  { path: "/notice-analysis", title: "공고 상세 분석" },
  { path: "/pdfs", title: "공고문 파일 분석" },
  { path: "/calculator", title: "투찰금액 계산기" },
  { path: "/reserve", title: "복수예비가격·사정률 분석" },
  { path: "/history", title: "과거 개찰 결과 분석" },
  { path: "/similar", title: "유사 입찰 검색" },
  { path: "/scenarios", title: "투찰 시나리오 비교" },
  { path: "/qualification", title: "적격심사·자격 체크" },
  { path: "/costs", title: "원가·수익성 분석" },
  { path: "/favorites", title: "관심 공고·즐겨찾기" },
  { path: "/collections", title: "데이터 수집 관리" },
  { path: "/imports", title: "엑셀 업로드 관리" },
  { path: "/rules", title: "규칙 관리" },
  { path: "/reports", title: "보고서 출력" },
  { path: "/settings", title: "시스템 설정" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen md:flex">
      <header className="flex items-center justify-between bg-slate-900 px-4 py-2 text-white md:hidden">
        <span className="font-bold">공공입찰 분석</span>
        <button className="rounded border border-slate-500 px-2 py-1 text-sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="side-menu">
          메뉴
        </button>
      </header>
      <nav
        id="side-menu"
        aria-label="주 메뉴"
        className={`${open ? "block" : "hidden"} w-full shrink-0 bg-slate-900 text-slate-100 md:block md:min-h-screen md:w-56`}
      >
        <div className="hidden px-4 py-4 text-lg font-bold md:block">공공입찰 분석</div>
        <ol className="pb-4">
          {MENUS.map((m, i) => (
            <li key={m.path}>
              <NavLink
                to={m.path}
                end={m.path === "/"}
                onClick={() => setOpen(false)}
                className={({ isActive }) => `block px-4 py-1.5 text-sm ${isActive ? "bg-blue-700 text-white" : "hover:bg-slate-800"}`}
              >
                <span className="mr-1 text-xs text-slate-400">{i + 1}.</span>
                {m.title}
              </NavLink>
            </li>
          ))}
        </ol>
        <div className="border-t border-slate-700 px-4 py-3 text-xs">
          <div>
            {user?.username} ({label(user?.role)})
          </div>
          <button className="mt-1 underline" onClick={() => void logout()}>
            로그아웃
          </button>
        </div>
      </nav>
      <main className="min-w-0 flex-1 p-3 md:p-6">
        <ErrorBoundary resetKey={pathname}>
          <Outlet />
        </ErrorBoundary>
        <footer className="mt-8 text-xs text-slate-500">
          이 시스템은 분석·의사결정 지원용입니다. 낙찰을 보장하지 않으며 투찰을 대신 제출하지 않습니다.
        </footer>
      </main>
    </div>
  );
}
