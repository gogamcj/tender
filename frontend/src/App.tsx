import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import Calculator from "./pages/Calculator";
import Collections from "./pages/Collections";
import Costs from "./pages/Costs";
import Dashboard from "./pages/Dashboard";
import Favorites from "./pages/Favorites";
import HistoryAnalysis from "./pages/HistoryAnalysis";
import Imports from "./pages/Imports";
import Login from "./pages/Login";
import NoticeAnalysis from "./pages/NoticeAnalysis";
import NoticeSearch from "./pages/NoticeSearch";
import PdfAnalysis from "./pages/PdfAnalysis";
import Qualification from "./pages/Qualification";
import Reports from "./pages/Reports";
import ReserveAnalysis from "./pages/ReserveAnalysis";
import Rules from "./pages/Rules";
import Scenarios from "./pages/Scenarios";
import Settings from "./pages/Settings";
import SimilarSearch from "./pages/SimilarSearch";

export function AppRoutes() {
  const { user, checking } = useAuth();
  if (checking) return <Loading text="로그인 상태 확인 중…" />;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="notices" element={<NoticeSearch />} />
        <Route path="notice-analysis" element={<NoticeAnalysis />} />
        <Route path="pdfs" element={<PdfAnalysis />} />
        <Route path="calculator" element={<Calculator />} />
        <Route path="reserve" element={<ReserveAnalysis />} />
        <Route path="history" element={<HistoryAnalysis />} />
        <Route path="similar" element={<SimilarSearch />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="qualification" element={<Qualification />} />
        <Route path="costs" element={<Costs />} />
        <Route path="favorites" element={<Favorites />} />
        <Route path="collections" element={<Collections />} />
        <Route path="imports" element={<Imports />} />
        <Route path="rules" element={<Rules />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<p className="p-4">없는 화면입니다.</p>} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
