// 실행 중인 백엔드(8000)와 vite preview(4173)에 붙어 화면을 점검한다. docs/frontend.md 참고.
// 필요: 관리자 admin, 조회 전용 viewer1 계정(같은 비밀번호 E2E_PASSWORD), 샘플 데이터(scripts/load_sample_data.py).
const { chromium } = require('playwright');
const D = process.env.E2E_OUT ?? "e2e-out", SEED = require("path").resolve(__dirname, "../../backend/seed");
const B = process.env.E2E_BASE ?? "http://localhost:4173";
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(`PASS ${name}`); } catch (e) { results.push(`FAIL ${name}: ${e.message.split("\n")[0]}`); }
}
async function login(page, u) {
  await page.goto(B + "/");
  await page.getByLabel("사용자 이름").fill(u);
  await page.getByLabel("비밀번호").fill(process.env.E2E_PASSWORD);
  await page.locator("form button").click();
  await page.waitForSelector("nav", { state: "attached" });
}
(async () => {
  require("fs").mkdirSync(`${D}/shots`, { recursive: true });
  const b = await chromium.launch();
  for (const [vpName, vp] of [["pc", { width: 1366, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    const ctx = await b.newContext({ viewport: vp, acceptDownloads: true });
    const page = await ctx.newPage();
    page.setDefaultTimeout(15000);
    await login(page, "admin");
    const T = (n) => `${vpName}: ${n}`;

    await check(T("로그인 실패 메시지"), async () => {
      const p2 = await ctx.browser().newPage();
      await p2.goto(B + "/"); await p2.getByLabel("사용자 이름").fill("admin"); await p2.getByLabel("비밀번호").fill("wrong-password!");
      await p2.locator("form button").click(); await p2.getByRole("alert").waitFor(); await p2.close();
    });
    await check(T("계산기 입력 오류 표시"), async () => {
      await page.goto(B + "/calculator");
      await page.locator("input[inputmode=numeric]").first().fill("12abc");
      await page.getByText("원 단위 숫자로 입력하세요.").first().waitFor();
    });
    await check(T("공고 검색 필터"), async () => {
      await page.goto(B + "/notices");
      await page.getByLabel("검색어(공고명·공고번호)").fill("0009");
      await page.getByRole("button", { name: "검색", exact: true }).click();
      await page.getByText("가상 공사 0009").locator("visible=true").first().waitFor();
      await page.waitForFunction(() => document.body.innerText.match(/가상 (공사|용역) \d{4}/g)?.length <= 2);
    });
    await check(T("과거 결과 분석 차트·표 보기"), async () => {
      await page.goto(B + "/history");
      await page.getByRole("button", { name: "분석", exact: true }).click();
      await page.getByText("표본 수:").first().waitFor();
      await page.getByRole("button", { name: "표로 보기" }).first().click();
      await page.getByRole("button", { name: "차트로 보기" }).first().waitFor();
      await page.screenshot({ path: `${D}/shots/flow_${vpName}_history.png`, fullPage: true });
    });
    await check(T("시나리오 계산·저장"), async () => {
      await page.goto(B + "/scenarios?notice=1");
      await page.getByRole("button", { name: "계산 후 저장" }).click();
      await page.getByText("후보 투찰금액별 결과 비교").first().waitFor();
      await page.screenshot({ path: `${D}/shots/flow_${vpName}_scenarios.png`, fullPage: true });
    });
    await check(T("보고서 다운로드"), async () => {
      await page.goto(B + "/reports");
      const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "XLSX" }).nth(1).click()]);
      const f = dl.suggestedFilename();
      if (!f.endsWith(".xlsx")) throw new Error(f);
    });
    await check(T("엑셀 업로드 미리보기"), async () => {
      await page.goto(B + "/imports");
      await page.getByLabel("업로드 파일").setInputFiles(`${SEED}/sample_results.csv`);
      await page.getByRole("button", { name: "업로드·분석" }).click();
      await page.getByRole("button", { name: "3. 검사·미리보기" }).click();
      await page.getByText(/^오류 \d+/).first().waitFor();
      await page.screenshot({ path: `${D}/shots/flow_${vpName}_imports.png`, fullPage: true });
    });
    await check(T("PDF 업로드 추출 결과"), async () => {
      await page.goto(B + "/pdfs");
      await page.getByLabel("PDF 파일").setInputFiles(`${SEED}/sample_notice.pdf`);
      await page.getByRole("button", { name: "확인" }).first().waitFor();
      if (vpName === "mobile") await page.getByText("이미 올린 파일이라").waitFor();
    });
    await check(T("API 장애 시 오류 안내"), async () => {
      await page.route("**/api/notices?**", (r) => r.abort("connectionrefused"));
      await page.goto(B + "/notices");
      await page.getByText("서버에 연결할 수 없습니다").first().waitFor();
      await page.unroute("**/api/notices?**");
      await page.route("**/api/notices?**", (r) => r.fulfill({ status: 500, body: "boom" }));
      await page.goto(B + "/notices");
      await page.getByText("서버 오류가 발생했습니다(500)").first().waitFor();
      await page.unroute("**/api/notices?**");
    });
    await ctx.close();
  }
  // 조회 전용 계정
  const ctx = await b.newContext();
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  await login(page, "viewer1");
  await check("viewer: 원가 화면 차단", async () => {
    await page.goto(B + "/costs");
    await page.getByText("조회 전용 계정은 원가 자료를 볼 수 없습니다.").waitFor();
  });
  await check("viewer: 규칙 상태 변경 불가", async () => {
    await page.goto(B + "/rules");
    await page.getByText("SAMPLE_LOWER_LIMIT").first().waitFor();
    if (await page.getByLabel("SAMPLE_LOWER_LIMIT 검증 상태").count()) throw new Error("select visible");
  });
  await b.close();
  console.log(results.join("\n"));
  process.exitCode = results.some((r) => r.startsWith("FAIL")) ? 1 : 0;
})();
