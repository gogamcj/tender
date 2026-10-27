// 실행 중인 백엔드(8000)와 vite preview(4173)에 붙어 화면을 점검한다. docs/frontend.md 참고.
// 필요: 관리자 admin, 조회 전용 viewer1 계정(같은 비밀번호 E2E_PASSWORD), 샘플 데이터(scripts/load_sample_data.py).
const { chromium } = require('playwright');
const D = process.env.E2E_OUT ?? "e2e-out";
const B = process.env.E2E_BASE ?? "http://localhost:4173";
const paths = ["/","/notices","/notice-analysis","/pdfs","/calculator","/reserve","/history","/similar","/scenarios","/qualification","/costs","/favorites","/collections","/imports","/rules","/reports","/settings"];
(async () => {
  require("fs").mkdirSync(`${D}/shots`, { recursive: true });
  const b = await chromium.launch();
  for (const [name, vp] of [["pc", {width: 1366, height: 900}], ["mobile", {width: 390, height: 844}]]) {
    const ctx = await b.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errs = [];
    page.on("console", m => { if (m.type() === "error") errs.push(`[console] ${page.url()} ${m.text()}`); });
    page.on("pageerror", e => errs.push(`[pageerror] ${page.url()} ${e.message}`));
    page.on("response", r => { if (r.status() >= 400 && r.url().includes("/api/")) errs.push(`[http ${r.status()}] ${r.url()}`); });
    await page.goto(B + "/");
    await page.getByLabel("사용자 이름").fill("admin");
    await page.getByLabel("비밀번호").fill(process.env.E2E_PASSWORD);
    await page.locator("form button").click();
    await page.waitForSelector("nav", { state: "attached" }); errs.length = 0;
    for (const p of paths) {
      await page.goto(B + p);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(300);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) errs.push(`[overflow ${overflow}px] ${p}`);
      await page.screenshot({ path: `${D}/shots/${name}${p.replace(/\//g, "_") || "_"}.png`, fullPage: false });
    }
    console.log(name, errs.length ? errs.join("\n") : "no errors");
    if (errs.length) process.exitCode = 1;
    await ctx.close();
  }
  await b.close();
})();
