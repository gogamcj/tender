import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { get, post, setUnauthorizedHandler } from "../api/client";

export interface Me {
  id: number;
  username: string;
  role: "admin" | "user" | "viewer";
  is_active: boolean;
}

interface AuthValue {
  user: Me | null;
  checking: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  canWrite: boolean;
  isAdmin: boolean;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    get<Me>("/api/auth/me")
      .then(setUser, () => setUser(null))
      .finally(() => setChecking(false));
    setUnauthorizedHandler(() => setUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await post<{ user: Me }>("/api/auth/login", { username, password });
    setUser(r.user);
  }, []);
  const logout = useCallback(async () => {
    try {
      await post("/api/auth/logout");
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <Ctx.Provider value={{ user, checking, login, logout, canWrite: !!user && user.role !== "viewer", isAdmin: user?.role === "admin" }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("AuthProvider 밖에서 useAuth 를 썼습니다.");
  return v;
}
