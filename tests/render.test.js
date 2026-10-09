import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { renderReport, renderInline } from "../web/js/render.js";
import { normalizeContent, buildAnchors } from "../web/js/anchors.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const loadSample = () => JSON.parse(readFileSync(join(here, "fixtures/sample.json"), "utf8"));
const GRID_COLS = { topic: 3, role: 3, day: 3, decision: 3, agenda: 2, seq: 4 };

// 攔 console.error / warn，回傳 [結果, errs, warns]
function capture(fn) {
  const errs = [], warns = [];
  const oe = console.error, ow = console.warn;
  console.error = (...a) => errs.push(a.join(" "));
  console.warn = (...a) => warns.push(a.join(" "));
  try { return [fn(), errs, warns]; } finally { console.error = oe; console.warn = ow; }
}
const count = (html, re) => (html.match(re) || []).length;
const base = (blocks, extra = {}) => ({ title: "T", period: "P", to: "甲", from: "乙", blocks, ...extra });

test("renderInline：先 escape 再套標記", () => {
  assert.equal(renderInline("a **b** !!c!!\nd"), 'a <b class="mk-navy">b</b> <b class="mk-red">c</b><br>d');
  assert.equal(renderInline(`<script>"x"&'y'</script>`), "&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;&lt;/script&gt;");
  assert.equal(renderInline("**<i>**"), '<b class="mk-navy">&lt;i&gt;</b>');
});

test("sample：每種 block 產出對應元素與 class", () => {
  const [r, errs] = capture(() => renderReport(loadSample()));
  const h = r.html;
  assert.deepEqual(r.errors, []);
  assert.deepEqual(errs, []);
  assert.match(h, /^<article class="report" data-period="2026年10月5日（一）～2026年10月7日（三）">/);
  assert.match(h, /<h1 class="report-title">林踐宇個人工作報告<\/h1>/);
  assert.match(h, /<span class="meta-k">提報對象：<\/span>張院長<span class="meta-sep">｜<\/span><span class="meta-k">報告人：<\/span>林踐宇/);
  assert.equal(count(h, /<p class="kicker" data-btype="kicker"/g), 5);
  assert.equal(count(h, /<h2 class="h1 tight" data-btype="h1"/g), 5);
  assert.match(h, /<span class="h1-text">一、本期重點事項<\/span><span class="h1-note">截至 10 月 7 日<\/span>/);
  assert.equal(count(h, /<p class="cap" data-btype="cap"/g), 1);
  assert.equal(count(h, /<div class="stats n-4" data-btype="stats"/g), 1);
  assert.equal(count(h, /<div class="stats n-2" data-btype="stats"/g), 1);
  assert.match(h, /<div class="stat accent-navy"><div class="stat-v">12<span class="stat-u">項<\/span><\/div><div class="stat-label">本期事項<\/div><div class="stat-note">較上期 \+2<\/div><\/div>/);
  assert.match(h, /<div class="stat accent-green">/);
  assert.match(h, /<div class="stat accent-red"><div class="stat-v">3<\/div>/);
  assert.match(h, /<div class="stat accent-blue">/);
  assert.equal(count(h, /<div class="bars" data-btype="bars"/g), 1);
  assert.equal(count(h, /<div class="bar-row">/g), 5);
  for (const c of ["navy", "green", "blue", "grey"]) assert.match(h, new RegExp(`bar-fill c-${c}"`));
  assert.match(h, /<span class="bar-fill c-blue" style="width:4.2%"><\/span>/);
  assert.match(h, /<span class="bar-fill c-blue" style="width:100%"><\/span><\/span><span class="bar-val">已結案/);
  assert.match(h, /<span class="bar-fill c-grey" style="width:0%"><\/span>/);
  assert.equal(count(h, /<div class="callout" data-btype="callout"/g), 1);
  assert.match(h, /本期 <b class="mk-navy">三項<\/b> 重點：甲案進度 <b class="mk-red">落後 2 天<\/b>，乙案完成驗收，丙案啟動。<br>次週重點/);
  for (const g of ["seq", "role", "day", "decision", "agenda"]) assert.match(h, new RegExp(`<div class="tbl grid-${g} cols-${GRID_COLS[g]}" data-btype="table"`));
  assert.equal(count(h, /<h3 class="day" data-btype="day"/g), 2);
  assert.equal(count(h, /<ul class="bullets" data-btype="bullets"/g), 1);
  assert.equal(count(h, /<li data-kind="li" data-anchor="[^"]+" data-statusable="true">/g), 3);
  assert.match(h, /<figure class="photos cols-3" data-btype="photos"/);
  assert.match(h, /<figure class="photos cols-2" data-btype="photos"/);
  assert.match(h, /<img src="photos\/p2.jpg" loading="lazy" alt="B1／機房：水泵 更換 中"><figcaption>B1／機房：水泵 <b class="mk-navy">更換<\/b> 中<\/figcaption>/);
  assert.equal(count(h, /<p class="footnote" data-btype="footnote"/g), 1);
  assert.equal(count(h, /blk-error/g), 0);
  assert.doesNotMatch(h, /ignored/);
});

test("data-anchor 與 buildAnchors 一致、文件順序相同", () => {
  const raw = loadSample();
  const r = renderReport(raw);
  const expected = buildAnchors(normalizeContent(raw)).anchors.map((a) => a.anchor);
  assert.deepEqual(r.anchors.map((a) => a.anchor), expected);
  const inHtml = [...r.html.matchAll(/data-anchor="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(inHtml, expected);
  // 每個 data-anchor 元素都有 data-kind
  assert.equal(count(r.html, /data-anchor="/g), count(r.html, /data-kind="/g));
});

test("section 與 toc", () => {
  const h = renderReport(loadSample()).html;
  assert.doesNotMatch(h, /id="sec-0"/);
  for (let i = 1; i <= 5; i++) assert.match(h, new RegExp(`<section class="sec" id="sec-${i}">`));
  assert.match(h, /<nav class="toc" aria-label="章節目錄"><a href="#sec-1">一、本期重點事項<\/a><a href="#sec-2">二、專案角色與權責<\/a>/);
  // kicker 位於其 section 內
  assert.match(h, /<section class="sec" id="sec-2"><p class="kicker"/);
  const h0 = renderReport(base([{ cap: "前言" }, { h1: "甲" }])).html;
  assert.match(h0, /<section class="sec" id="sec-0"><p class="cap"/);
});

test("data-statusable 只在 decision row 與 li", () => {
  const h = renderReport(loadSample()).html;
  const st = [...h.matchAll(/<(\w+)[^>]*data-statusable="true"[^>]*>/g)];
  assert.equal(st.length, 5);
  assert.equal(st.filter((m) => m[1] === "tr").length, 2);
  assert.equal(st.filter((m) => m[1] === "li").length, 3);
  assert.doesNotMatch(h, /data-statusable="false"/);
  const dec = h.slice(h.indexOf('grid-decision'), h.indexOf('</table>', h.indexOf('grid-decision')));
  assert.equal(count(dec, /<tr data-kind="row"[^>]*data-statusable="true"/g), 2);
});

test("table：表頭 th、資料列 td 數＝grid 欄數、\\n→<br>", () => {
  const h = renderReport(loadSample()).html;
  for (const m of h.matchAll(/<div class="tbl grid-(\w+) cols-(\d)"[\s\S]*?<\/table><\/div>/g)) {
    const n = GRID_COLS[m[1]];
    assert.equal(Number(m[2]), n);
    for (const tr of m[0].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)) {
      assert.equal(count(tr[1], /<t[hd][ >]/g), n);
    }
  }
  assert.match(h, /<td>進度管控<br>品質查驗<\/td>/);
  assert.match(h, /<thead><tr><th>序<\/th><th>所屬專案<\/th>/);
});

test("XSS：<script> 被 escape", () => {
  const h = renderReport(loadSample()).html;
  assert.doesNotMatch(h, /<script/i);
  assert.match(h, /規劃啟動會議 &lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  const h2 = renderReport(base([{ h1: '"><img onerror=x>' }], { title: "<b>x</b>", period: '"q"' })).html;
  assert.doesNotMatch(h2, /<img onerror/);
  assert.match(h2, /data-period="&quot;q&quot;"/);
  assert.match(h2, /&lt;b&gt;x&lt;\/b&gt;/);
});

test("未知 block → 錯誤區塊＋console.error，不中斷", () => {
  const [r, errs] = capture(() => renderReport(base([{ h1: "一" }, { weird: "x" }, { cap: "a", day: "b" }, { cap: "後" }])));
  assert.equal(count(r.html, /<div class="blk-error" data-btype="error">區塊格式錯誤（bi=1）<\/div>/g), 1);
  assert.equal(count(r.html, /區塊格式錯誤（bi=2）/g), 1);
  assert.match(r.html, /<p class="cap" data-btype="cap"[^>]*>後<\/p>/);
  assert.ok(errs.some((e) => e.includes("[render] 未知區塊 bi=1 keys=[weird]")));
  assert.ok(r.errors.some((e) => e.includes("[render] 未知區塊 bi=1 keys=[weird]")));
  assert.ok(r.errors.some((e) => e.includes("bi=2")));
  assert.doesNotMatch(r.html, /blk-error[^>]*data-anchor/);
  // 錨點：錯誤 block 不產但後面照常
  assert.deepEqual(r.anchors.map((a) => a.bi), [0, 3]);
});

test("table 欄數不符 → 錯誤區塊＋errors 訊息", () => {
  const [r, errs] = capture(() => renderReport(base([{ table: { grid: "seq", rows: [["a", "b", "c", "d"], ["1", "2", "3"]] } }])));
  assert.match(r.html, /<div class="blk-error" data-btype="error">區塊格式錯誤（bi=0）<\/div>/);
  assert.ok(r.errors.includes("[render] table bi=0 第 1 列 3 欄，grid seq 需要 4 欄"), r.errors.join("\n"));
  assert.ok(errs.includes("[render] table bi=0 第 1 列 3 欄，grid seq 需要 4 欄"));
  assert.doesNotMatch(r.html, /<table>/);
  const [r2] = capture(() => renderReport(base([{ table: { grid: "nope", rows: [["a"]] } }])));
  assert.match(r2.html, /blk-error/);
});

test("頂層 photos 找不到 day → 丟棄該鍵重試、文末錯誤區塊", () => {
  const raw = base([{ day: "D1" }, { table: { grid: "agenda", rows: [["a", "b"]] } }],
    { photos: { "不存在": [["x.jpg", "c"]], D1: [["y.jpg", "ok"]] } });
  const [r, errs] = capture(() => renderReport(raw));
  assert.ok(errs.some((e) => e.includes("photos day label not found: 不存在")));
  assert.ok(r.errors.some((e) => e.includes("photos day label not found: 不存在")));
  assert.match(r.html, /<img src="y.jpg"/);
  assert.match(r.html, /<div class="blk-error" data-btype="error">[^<]*<\/div><\/article>$/);
});

test("stats accent 對照：可含 #、大小寫、未知→navy＋warn", () => {
  const [r, , warns] = capture(() => renderReport(base([{ stats: [
    { v: "1", accent: "#c00000" }, { v: "2", accent: "6e6a67" }, { v: "3", accent: "123456" }, { v: "4" },
  ] }])));
  assert.match(r.html, /stat accent-red/);
  assert.match(r.html, /stat accent-grey/);
  assert.equal(count(r.html, /stat accent-navy/g), 2);
  assert.equal(warns.length, 1);
  assert.doesNotMatch(r.html, /style=/);
});

test("bars：pct 夾在 0～100、未知色 → blue", () => {
  const [r] = capture(() => renderReport(base([{ bars: [["a", "x", 150, "pink"], ["b", "y", -3]] }])));
  assert.match(r.html, /c-blue" style="width:100%"/);
  assert.match(r.html, /style="width:0%"/);
  assert.equal(count(r.html, /style="/g), 2);
});

test("photoBase 只前綴相對 url", () => {
  const raw = base([{ photos: [{ url: "a/b.jpg", cap: "1", path: "a/b.jpg" }, { url: "https://h/x.jpg", cap: "2", path: "p" }], cols: 2 }]);
  const h = renderReport(raw, { photoBase: "../private/" }).html;
  assert.match(h, /src="..\/private\/a\/b.jpg"/);
  assert.match(h, /src="https:\/\/h\/x.jpg"/);
});

test("純字串輸出：不碰 document", () => {
  assert.equal(typeof globalThis.document, "undefined");
  const r = renderReport(loadSample());
  assert.equal(typeof r.html, "string");
});

// web/ 色值與機密自檢（正式 lint 由 integrate 的 tests/lint.test.js 負責）
function walk(d, out = []) {
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    if (statSync(p).isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}
test("render 擁有的 web 檔：hex/rgb/hsl 只在 tokens.css、無 service_role", () => {
  const files = walk(join(root, "web")).filter((p) => /\.(html|css|js)$/.test(p));
  assert.ok(files.length >= 5);
  for (const p of files) {
    const s = readFileSync(p, "utf8");
    assert.doesNotMatch(s, /service_role/, p);
    if (p.endsWith("css/tokens.css")) continue;
    assert.doesNotMatch(s, /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])/, p);
    assert.doesNotMatch(s, /\b(rgba?|hsla?)\(/, p);
  }
});

test("app.css：斷點、tbl min-width、print、logo、body 背景", () => {
  const css = readFileSync(join(root, "web/css/app.css"), "utf8");
  assert.match(css, /@media \(max-width: ?600px\)/);
  assert.match(css, /@media \(min-width: ?601px\) and \(max-width: ?1023px\)/);
  assert.match(css, /@media \(min-width: ?1024px\)/);
  assert.match(css, /@media print/);
  assert.match(css, /\.tbl\s*\{[^}]*overflow-x:\s*auto/);
  assert.match(css, /\.tbl\.cols-3 table\s*\{[^}]*min-width:\s*560px/);
  assert.match(css, /\.tbl\.cols-4 table\s*\{[^}]*min-width:\s*640px/);
  assert.match(css, /body\s*\{[^}]*background:\s*var\(--bg\)/);
  assert.match(css, /height:\s*var\(--logo-h\)[^}]*width:\s*auto/);
  const tokens = readFileSync(join(root, "web/css/tokens.css"), "utf8");
  for (const t of ["--navy:#0054A7", "--thead-bg:#EAF2F9", "--ink:#3E3A39", "--logo-h:36px"]) assert.ok(tokens.replace(/\s/g, "").includes(t), t);
});

test("index.html：logo、ui.js 模組、品牌名", () => {
  const h = readFileSync(join(root, "web/index.html"), "utf8");
  assert.match(h, /<script type="module" src="js\/ui.js"><\/script>/);
  assert.match(h, /img\/logo-cis.png/);
  assert.match(h, /林踐宇個人工作報告/);
  assert.ok(existsSync(join(root, "web/img/logo-cis.png")));
});

const PRIVATE = ["260928-1002.json", "260921-27.json"].map((f) => join(root, "private", "fixtures", f));
for (const p of PRIVATE) {
  test(`私密 fixture 渲染：${p.split("/").pop()}`, (t) => {
    if (!existsSync(p)) { t.skip("私密 fixture 不存在"); return; }
    const raw = JSON.parse(readFileSync(p, "utf8"));
    const [r, errs] = capture(() => renderReport(raw));
    assert.deepEqual(r.errors, []);
    assert.deepEqual(errs, []);
    assert.equal(count(r.html, /blk-error/g), 0);
    const n = normalizeContent(raw).blocks.length;
    assert.equal(count(r.html, /data-btype="/g), n);
    for (const m of r.html.matchAll(/<div class="tbl grid-(\w+) cols-(\d)"[\s\S]*?<\/table><\/div>/g)) {
      const cols = GRID_COLS[m[1]];
      assert.equal(Number(m[2]), cols);
      for (const tr of m[0].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)) assert.equal(count(tr[1], /<t[hd][ >]/g), cols);
    }
    assert.doesNotMatch(r.html, /<script/i);
  });
}
