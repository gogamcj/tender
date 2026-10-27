import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChartFrame } from "../components/charts";
import { ErrorBox } from "../components/ui";
import { ApiError } from "../api/client";
import { AppRoutes } from "../App";
import { AuthProvider } from "../lib/auth";

const meta = (n: number) => ({ period: "2023-10-27 ~ 2026-10-27", n, basis: "예정가격", sources: "등록된 과거 개찰 결과" });
const table = { columns: ["구간", "건수"], rows: [["0~1%", 3]] };

describe("ChartFrame", () => {
  it("분석 기간·표본 수·기준·출처를 표시하고 표로 볼 수 있다", () => {
    render(<ChartFrame title="사정률 분포" meta={meta(120)} table={table}><div>차트</div></ChartFrame>);
    const m = screen.getByTestId("chart-meta");
    expect(m).toHaveTextContent("2023-10-27 ~ 2026-10-27");
    expect(m).toHaveTextContent("120건");
    expect(m).toHaveTextContent("예정가격");
    expect(m).toHaveTextContent("등록된 과거 개찰 결과");
    expect(screen.queryByRole("note")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "표로 보기" }));
    expect(screen.getByRole("table")).toHaveTextContent("0~1%");
    expect(screen.queryByText("차트")).toBeNull();
  });
  it("표본이 적으면 경고한다", () => {
    render(<ChartFrame title="t" meta={meta(4)} table={table}><div /></ChartFrame>);
    expect(screen.getByRole("note")).toHaveTextContent("표본이 4건으로 매우 적습니다");
  });
  it("표본이 없으면 차트 대신 안내", () => {
    render(<ChartFrame title="t" meta={meta(0)} table={table}><div>차트</div></ChartFrame>);
    expect(screen.getByText("표시할 자료가 없습니다.")).toBeInTheDocument();
  });
});

describe("ErrorBox", () => {
  it("연결 실패 시 저장 자료가 바뀌지 않았다고 안내하고 다시 시도 버튼을 준다", () => {
    const retry = vi.fn();
    render(<ErrorBox error={new ApiError(0, "서버에 연결할 수 없습니다.")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("저장된 자료는 바뀌지 않았습니다");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(retry).toHaveBeenCalled();
  });
});

function mockFetch(handler: (url: string, init?: RequestInit) => [number, unknown]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const [status, body] = handler(url, init);
    return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }));
}

const app = (path = "/") => render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>);

describe("로그인과 화면 전환", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("로그인 실패 메시지를 보여 준다", async () => {
    mockFetch((url) => (url.endsWith("/api/auth/login") ? [401, { detail: "아이디 또는 비밀번호가 맞지 않습니다." }] : [401, { detail: "로그인이 필요합니다." }]));
    app();
    fireEvent.change(await screen.findByLabelText("사용자 이름"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("아이디 또는 비밀번호가 맞지 않습니다.");
  });

  it("조회 전용 계정은 원가 화면을 볼 수 없다", async () => {
    mockFetch((url) => (url.endsWith("/api/auth/me") ? [200, { id: 2, username: "v", role: "viewer", is_active: true }] : [200, []]));
    app("/costs");
    expect(await screen.findByText("조회 전용 계정은 원가 자료를 볼 수 없습니다.")).toBeInTheDocument();
  });

  it("계산기 입력 오류를 필드에 표시한다", async () => {
    mockFetch((url) => (url.endsWith("/api/auth/me") ? [200, { id: 1, username: "a", role: "admin", is_active: true }] : [200, []]));
    app("/calculator");
    const input = (await screen.findAllByRole("textbox"))[0];
    fireEvent.change(input, { target: { value: "12abc" } });
    await waitFor(() => expect(screen.getAllByText(/원 단위 숫자로 입력하세요|숫자로 입력하세요/).length).toBeGreaterThan(0));
  });

  it("API 서버 오류 시 안내한다", async () => {
    mockFetch((url) => (url.endsWith("/api/auth/me") ? [200, { id: 1, username: "a", role: "admin", is_active: true }] : [500, undefined]));
    app("/notices");
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("서버 오류가 발생했습니다(500)");
  });
});

describe("데이터 수집 관리", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("수집 결과 요약(객체)을 표시하고 화면이 깨지지 않는다", async () => {
    const job = {
      id: 1, source_name: "g2b_scsbid", operation: "getOpengResultListInfoServc", query_parameters: {}, status: "failed",
      started_at: "2026-10-27T00:00:00+00:00", finished_at: "2026-10-27T00:00:05+00:00", request_count: 1, inserted_count: 0, updated_count: 0, skipped_count: 0,
      error_summary: { returned_items: 0, warnings: [], request_errors: ["SERVICE_KEY_IS_NOT_REGISTERED_ERROR"], error: "인증키 오류", error_code: "30" },
    };
    mockFetch((url) => {
      if (url.endsWith("/api/auth/me")) return [200, { id: 1, username: "a", role: "admin", is_active: true }];
      if (url.endsWith("/api/collections/sources")) return [200, { service_key_configured: true, usage_today: [], operations: [] }];
      if (url.endsWith("/api/collections")) return [200, [job]];
      return [200, []];
    });
    app("/collections");
    expect(await screen.findByText("인증키 오류")).toBeInTheDocument();
    expect(screen.getByText("SERVICE_KEY_IS_NOT_REGISTERED_ERROR")).toBeInTheDocument();
    expect(screen.getByText("응답 0건")).toBeInTheDocument();
  });

  it("화면 오류가 나도 빈 화면 대신 안내한다", async () => {
    const { ErrorBoundary } = await import("../components/ErrorBoundary");
    const Boom = () => { throw new Error("boom"); };
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorBoundary><Boom /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toHaveTextContent("이 화면을 표시하는 중 오류가 났습니다");
  });
});
