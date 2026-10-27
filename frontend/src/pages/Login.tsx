import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { ErrorBox } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-3" aria-label="로그인">
        <h1 className="h1">공공입찰 분석 시스템</h1>
        <label className="block">
          <span className="label">사용자 이름</span>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label className="block">
          <span className="label">비밀번호</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <ErrorBox error={error} />
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "확인 중…" : "로그인"}
        </button>
        <p className="text-xs text-slate-500">첫 관리자 계정은 서버에서 `python -m app.cli create-user` 로 만듭니다.</p>
      </form>
    </div>
  );
}
