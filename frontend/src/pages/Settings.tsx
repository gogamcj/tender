import { useState } from "react";
import { get, patch, post } from "../api/client";
import { Badge, ErrorBox, Field, Loading, Section } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dt, label } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface U { id: number; username: string; role: string; is_active: boolean; created_at: string }

function PasswordForm() {
  const { logout } = useAuth();
  const [f, setF] = useState({ current: "", next: "", again: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const submit = async () => {
    setErr(null);
    setMsg(null);
    if (f.next !== f.again) { setMsg("새 비밀번호가 서로 다릅니다."); return; }
    try {
      await post("/api/auth/password", { current_password: f.current, new_password: f.next });
      setF({ current: "", next: "", again: "" });
      window.alert("비밀번호를 바꿨습니다. 모든 세션이 종료되어 다시 로그인해야 합니다.");
      void logout();
    } catch (e) { setErr(e as Error); }
  };
  return (
    <div className="grid max-w-md gap-2">
      <Field label="현재 비밀번호"><input className="input" type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
      <Field label="새 비밀번호" hint="10자 이상"><input className="input" type="password" autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} /></Field>
      <Field label="새 비밀번호 확인"><input className="input" type="password" autoComplete="new-password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} /></Field>
      {msg && <p className="text-sm text-red-700" role="alert">{msg}</p>}
      <ErrorBox error={err} />
      <button className="btn-primary w-fit" onClick={() => void submit()}>변경</button>
    </div>
  );
}

function Users() {
  const users = useAsync(() => get<U[]>("/api/users"), []);
  const [nf, setNf] = useState({ username: "", password: "", role: "user" });
  const [err, setErr] = useState<Error | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); users.reload(); } catch (e) { setErr(e as Error); }
  };
  return (
    <>
      <ErrorBox error={err ?? users.error} />
      {users.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="tbl">
            <thead><tr><th>아이디</th><th>권한</th><th>상태</th><th>생성</th><th></th></tr></thead>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.username}</td>
                  <td>
                    <select className="input w-28" aria-label={`${u.username} 권한`} value={u.role} onChange={(e) => void act(() => patch(`/api/users/${u.id}`, { role: e.target.value }))}>
                      <option value="admin">관리자</option><option value="user">일반</option><option value="viewer">조회 전용</option>
                    </select>
                  </td>
                  <td>{u.is_active ? <Badge tone="green">사용</Badge> : <Badge>중지</Badge>}</td>
                  <td>{dt(u.created_at)}</td>
                  <td className="space-x-1">
                    <button className="btn-secondary text-xs" onClick={() => void act(() => patch(`/api/users/${u.id}`, { is_active: !u.is_active }))}>{u.is_active ? "사용 중지" : "다시 사용"}</button>
                    <button className="btn-secondary text-xs" onClick={() => { const p = window.prompt(`${u.username} 의 새 비밀번호(10자 이상)`); if (p) void act(() => patch(`/api/users/${u.id}`, { password: p })); }}>비밀번호 재설정</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label="새 아이디"><input className="input" value={nf.username} onChange={(e) => setNf({ ...nf, username: e.target.value })} /></Field>
        <Field label="초기 비밀번호"><input className="input" type="password" autoComplete="new-password" value={nf.password} onChange={(e) => setNf({ ...nf, password: e.target.value })} /></Field>
        <Field label="권한">
          <select className="input" value={nf.role} onChange={(e) => setNf({ ...nf, role: e.target.value })}><option value="user">일반</option><option value="viewer">조회 전용</option><option value="admin">관리자</option></select>
        </Field>
        <button className="btn-primary" onClick={() => void act(async () => { await post("/api/users", nf); setNf({ username: "", password: "", role: "user" }); })}>사용자 추가</button>
      </div>
    </>
  );
}

export default function Settings() {
  const { user, isAdmin } = useAuth();
  const health = useAsync(() => get<{ status: string }>("/api/health"), []);
  return (
    <div>
      <h1 className="h1">시스템 설정</h1>
      <Section title="내 계정">
        <p className="mb-2 text-sm">{user?.username} · {label(user?.role)}</p>
        <PasswordForm />
      </Section>
      {isAdmin && <Section title="사용자 관리"><Users /></Section>}
      <Section title="시스템 상태">
        <p className="text-sm">서버: {health.loading ? "확인 중" : health.data?.status === "ok" ? <Badge tone="green">정상</Badge> : <Badge tone="red">응답 없음</Badge>}</p>
        <p className="mt-1 text-xs text-slate-600">공공데이터 API 키, DB 주소, 세션 시간, 일일 호출 한도 같은 설정은 보안을 위해 화면에서 바꾸지 않고 서버의 환경변수(.env)로만 관리합니다. API 키 설정 여부와 오늘 사용량은 데이터 수집 관리 화면에서 볼 수 있습니다.</p>
      </Section>
    </div>
  );
}
