// API 호출 공통 처리. 금액·비율은 서버가 문자열로 주므로 숫자로 바꾸지 않고 그대로 다룬다(부동소수점 오차 방지).

export class ApiError extends Error {
  status: number;
  field?: string;
  data?: unknown;
  constructor(status: number, message: string, field?: string, data?: unknown) {
    super(message);
    this.status = status;
    this.field = field;
    this.data = data;
  }
}

type Json = Record<string, unknown>;

export function errorMessage(status: number, body: unknown): { message: string; field?: string } {
  if (body && typeof body === "object") {
    const b = body as Json;
    if (typeof b.message === "string") return { message: b.message, field: typeof b.field === "string" ? b.field : undefined };
    const d = b.detail;
    if (typeof d === "string") return { message: d };
    if (d && typeof d === "object" && !Array.isArray(d) && typeof (d as Json).message === "string") return { message: (d as Json).message as string };
    if (Array.isArray(d) && d.length) {
      const first = d[0] as Json;
      const loc = Array.isArray(first.loc) ? (first.loc as unknown[]).filter((x) => x !== "body").join(".") : undefined;
      return { message: `입력 오류${loc ? ` (${loc})` : ""}: ${String(first.msg ?? "")}`, field: loc };
    }
  }
  if (status === 0) return { message: "서버에 연결할 수 없습니다. 서버가 켜져 있는지, 네트워크를 확인하세요." };
  if (status >= 500) return { message: `서버 오류가 발생했습니다(${status}). 잠시 후 다시 시도하거나 관리자에게 알리세요.` };
  return { message: `요청을 처리하지 못했습니다(${status}).` };
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "same-origin",
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(headers ?? {}) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    const m = errorMessage(0, null);
    throw new ApiError(0, m.message);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !path.startsWith("/api/auth/login")) onUnauthorized();
    const m = errorMessage(res.status, body);
    throw new ApiError(res.status, m.message, m.field, body);
  }
  return body as T;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const put = <T,>(path: string, json: unknown) => api<T>(path, { method: "PUT", json });
export const patch = <T,>(path: string, json: unknown) => api<T>(path, { method: "PATCH", json });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

export function upload<T>(path: string, file: File, fields: Record<string, string> = {}): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  return api<T>(path, { method: "POST", body: fd });
}

export function qs(params: Record<string, unknown>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)));
    else u.append(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}
