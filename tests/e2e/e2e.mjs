// E2E（mock 模式）：node tests/e2e/e2e.mjs
// 自行起 python3 http.server（根＝web/），跑完一定關掉；截圖存 private/shots/。
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import puppeteer from "puppeteer";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = Number(process.env.E2E_PORT || 8787);
const BASE = `http://127.0.0.1:${PORT}/index.html`;
const SHOTS = join(root, "private", "shots");
mkdirSync(SHOTS, { recursive: true });

const sleep = (t) => new Promise((r) => setTimeout(r, t));
const step = (s) => console.log("•", s);

async function waitServer() {
  for (let i = 0; i < 50; i++) {
    try {
      const r = await fetch(BASE, { signal: AbortSignal.timeout(1000) });
      if (r.ok) return;
    } catch (e) { /* 尚未就緒 */ }
    await sleep(100);
  }
  throw new Error("http.server 未在 5 秒內就緒");
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1", "--directory", join(root, "web")], { stdio: "ignore" });
let browser;
const problems = [];

try {
  await waitServer();
  step(`伺服器 pid=${server.pid} 已就緒：${BASE}`);
  browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") problems.push("console.error: " + m.text()); });
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  page.on("dialog", async (d) => {
    if (d.type() === "confirm") return d.accept();
    problems.push("非預期 dialog（可能 XSS）：" + d.message());
    return d.dismiss();
  });
  await page.setViewport({ width: 1280, height: 900 });

  const go = async (hash) => {
    await page.goto(`${BASE}${hash}`, { waitUntil: "networkidle0" });
  };
  const whoIs = (text) => page.waitForFunction((t) => document.getElementById("who").textContent === t, { timeout: 5000 }, text);
  const reportReady = () => page.waitForSelector("#report:not([hidden]) article.report .cmt-btn", { timeout: 5000 });
  const countOf = (anchor) => page.$eval(`.cmt-btn[data-for="${anchor}"] .cmt-n`, (n) => n.textContent);

  // 乾淨起點
  await go("#");
  await page.evaluate(() => localStorage.clear());

  // 1. 讀者開報告頁、對表格列留言
  await go("#k=demo-reader-1&r=sample");
  await whoIs("張院長（讀者）");
  await reportReady();
  const hash = await page.evaluate(() => location.hash);
  assert.equal(hash, "#r=sample", "token 應已從網址列移除");
  assert.equal(await page.evaluate(() => localStorage.getItem("lwr.token")), "demo-reader-1");
  const rowAnchor = await page.$eval('#report tr[data-kind="row"]', (tr) => tr.dataset.anchor);
  step(`讀者對表格列 ${rowAnchor} 留言`);
  await page.click(`.cmt-btn[data-for="${rowAnchor}"]`);
  await page.waitForSelector(".drawer:not([hidden])");
  const body1 = "請補充進度 <b>粗體</b><img src=x onerror=alert(1)>";
  await page.type(".composer .composer-input", body1);
  await page.click(".composer .btn-primary");
  await page.waitForSelector(".drawer-list .cmt");
  const shown = await page.$eval(".drawer-list .cmt .cmt-body", (n) => ({ text: n.textContent, elems: n.children.length }));
  assert.equal(shown.text, body1, "留言內容應原樣以文字顯示");
  assert.equal(shown.elems, 0, "留言內容不得被解析成 HTML");
  assert.equal(await countOf(rowAnchor), "1");
  await page.keyboard.press("Escape");

  // 2. 作者回覆
  step("切換為作者並回覆");
  await go("#k=demo-author&r=sample");
  await whoIs("林踐宇（作者）");
  await reportReady();
  await page.waitForFunction((a) => document.querySelector(`.cmt-btn[data-for="${a}"] .cmt-n`).textContent === "1", { timeout: 5000 }, rowAnchor);
  await page.click(`.cmt-btn[data-for="${rowAnchor}"]`);
  await page.waitForSelector(".drawer-list .thread");
  const [replyBtn] = await page.$$("xpath/.//div[contains(@class,'drawer-list')]//button[normalize-space()='回覆']");
  assert.ok(replyBtn, "作者應看到回覆鈕");
  await replyBtn.click();
  await page.waitForSelector(".inline-form .composer-input");
  await page.type(".inline-form .composer-input", "已於 10/8 補件，請參閱附件。");
  await page.click(".inline-form .btn-primary");
  await page.waitForSelector(".drawer-list .cmt.is-reply");
  assert.equal(await countOf(rowAnchor), "2");
  assert.equal(await page.$$eval(".status-btn", (b) => b.length), 0, "作者不應有狀態鈕");
  await page.keyboard.press("Escape");

  step("作者首頁看到讀者已閱時間");
  await go("#");
  await page.waitForSelector("#home:not([hidden]) .rep-readers");
  const readersText = await page.$eval(".rep-readers", (n) => n.textContent);
  assert.match(readersText, /張院長已閱 \d\d\/\d\d/);
  assert.match(readersText, /讀者乙未閱/);

  // 3. 讀者首頁出現「新回覆」徽章
  step("讀者首頁應有新回覆徽章");
  await go("#k=demo-reader-1");
  await whoIs("張院長（讀者）");
  const badge = await page.waitForSelector('#home:not([hidden]) [data-badge="reply"]', { timeout: 5000 });
  assert.equal(await badge.evaluate((n) => n.textContent), "新回覆 1");
  assert.ok(await page.$('[data-badge="read"]'), "讀者已開過報告，應顯示已閱");

  // 4. 進報告頁設狀態
  step("讀者設狀態「同意」");
  await page.click(".rep-link");
  await reportReady();
  const stAnchor = await page.$eval('#report tr[data-statusable="true"]', (tr) => tr.dataset.anchor);
  await page.click(`.status-bar[data-for="${stAnchor}"] .status-btn[data-status="同意"]`);
  await page.waitForSelector(`.status-bar[data-for="${stAnchor}"] .status-btn.is-on[data-status="同意"]`);
  const liAnchor = await page.$eval('#report li[data-statusable="true"]', (li) => li.dataset.anchor);
  await page.click(`.status-bar[data-for="${liAnchor}"] .status-btn[data-status="請補資料"]`);
  await page.waitForSelector(`.status-bar[data-for="${liAnchor}"] .status-chip`);

  // 5. 重整後仍在
  step("重整後留言、回覆、狀態仍在");
  await page.reload({ waitUntil: "networkidle0" });
  await whoIs("張院長（讀者）");
  await reportReady();
  await page.waitForSelector(`.status-bar[data-for="${stAnchor}"] .status-btn.is-on[data-status="同意"]`, { timeout: 5000 });
  assert.equal(await page.$eval(`.status-bar[data-for="${stAnchor}"] .status-chip`, (n) => n.textContent), "張院長：同意");
  assert.equal(await page.$eval(`.status-bar[data-for="${liAnchor}"] .status-chip`, (n) => n.textContent), "張院長：請補資料");
  assert.equal(await countOf(rowAnchor), "2");
  step("點章節目錄只捲動、不離開報告頁");
  await page.click('a[href="#sec-2"]');
  await new Promise((r) => setTimeout(r, 400));
  assert.match(await page.evaluate(() => location.hash), /r=sample/, "點目錄後 hash 仍應指向報告");
  assert.ok(await page.$("#sec-2"), "點目錄後仍應在報告頁");
  await go("#");
  await page.waitForSelector("#home:not([hidden]) .rep-item");
  assert.equal(await page.$('[data-badge="reply"]'), null, "看過報告後新回覆徽章應消失");

  // 6. 截圖與 RWD
  await go("#r=sample");
  await page.reload({ waitUntil: "networkidle0" });
  await reportReady();
  const h1280 = await page.evaluate(() => document.documentElement.scrollHeight);
  step(`1280 寬頁高 ${h1280}px`);
  await page.screenshot({ path: join(SHOTS, "report-1280.png"), fullPage: true });
  await page.click(`.cmt-btn[data-for="${rowAnchor}"]`);
  await page.waitForSelector(".drawer:not([hidden])");
  await page.screenshot({ path: join(SHOTS, "drawer-1280.png") });
  await page.keyboard.press("Escape");

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
  await page.reload({ waitUntil: "networkidle0" });
  await reportReady();
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  step(`390 寬 scrollWidth=${sw}`);
  assert.ok(sw <= 390, `390 寬時不得整頁橫捲（scrollWidth=${sw}）`);
  await page.screenshot({ path: join(SHOTS, "report-390.png"), fullPage: true });
  await page.click(`.cmt-btn[data-for="${rowAnchor}"]`);
  await page.waitForSelector(".drawer:not([hidden])");
  const sw2 = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(sw2 <= 390, `抽屜開啟時不得整頁橫捲（scrollWidth=${sw2}）`);
  await page.screenshot({ path: join(SHOTS, "drawer-390.png") });
  await page.keyboard.press("Escape");
  await go("#");
  await page.waitForSelector("#home:not([hidden]) .rep-item");
  const sw3 = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(sw3 <= 390, `首頁 390 寬不得整頁橫捲（scrollWidth=${sw3}）`);
  await page.screenshot({ path: join(SHOTS, "home-390.png"), fullPage: true });

  // 7. 無 token、無效 token
  await page.evaluate(() => localStorage.removeItem("lwr.token"));
  await page.reload({ waitUntil: "networkidle0" });
  assert.match(await page.$eval("#notice", (n) => n.textContent), /請使用專屬連結/);
  await go("#k=not-a-real-token");
  await page.waitForFunction(() => /連結無效/.test(document.getElementById("notice").textContent), { timeout: 5000 });

  assert.deepEqual(problems, [], "頁面不應有 JS 錯誤或非預期 dialog");
  console.log(`E2E PASS（截圖：${SHOTS}）`);
} catch (e) {
  console.error("E2E FAIL:", e && e.stack ? e.stack : e);
  if (problems.length) console.error("頁面錯誤：\n" + problems.join("\n"));
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
