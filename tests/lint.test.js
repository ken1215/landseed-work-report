// CONTRACTS §8.2 lint ＋整合層靜態檢查
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, extname } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const rel = (p) => relative(root, p).split("\\").join("/");

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const n of readdirSync(dir)) {
    if (n === "node_modules" || n === "__pycache__" || n === ".DS_Store") continue;
    const p = join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}

const TEXT_EXT = new Set([".html", ".css", ".js", ".mjs", ".json", ".md", ".py", ".sh", ".sql", ".svg", ".txt"]);
const webFiles = walk(join(root, "web"));
const webCode = webFiles.filter((p) => [".html", ".css", ".js"].includes(extname(p)));
const read = (p) => readFileSync(p, "utf8");

const HEX_RE = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])/g;
const FN_RE = /\b(rgba?|hsla?)\(/g;

test("lint：hex／rgb()／hsl() 只出現在 tokens.css", () => {
  assert.ok(webCode.length >= 8, "web/ 程式檔數量異常：" + webCode.length);
  const bad = [];
  for (const p of webCode) {
    if (rel(p) === "web/css/tokens.css") continue;
    const s = read(p);
    for (const m of s.matchAll(HEX_RE)) bad.push(`${rel(p)}: ${m[0]}`);
    for (const m of s.matchAll(FN_RE)) bad.push(`${rel(p)}: ${m[0]}`);
  }
  assert.deepEqual(bad, []);
});

test("lint 陽性對照：hex 正則抓得到色值、不誤抓 class 名", () => {
  assert.deepEqual("color:#0054A7;x:#fff;y:#12345678".match(HEX_RE), ["#0054A7", "#fff", "#12345678"]);
  assert.equal("a#sec-1 #report-head".match(HEX_RE), null);
  assert.ok(read(join(root, "web/css/tokens.css")).match(HEX_RE).length >= 10, "tokens.css 應持有色值");
});

test("lint：web/ 不得出現 service_role、sb_secret", () => {
  const bad = webFiles.filter((p) => TEXT_EXT.has(extname(p)) && /service_role|sb_secret/.test(read(p))).map(rel);
  assert.deepEqual(bad, []);
});

test("lint：第三方 CDN 只允許 supabase-js 釘版那一條", () => {
  const allowed = new Set(["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm"]);
  const urls = [];
  for (const p of webCode) {
    for (const m of read(p).matchAll(/https?:\/\/[^\s"'`)<>]+/g)) {
      // config.js 的專案網址（anon 角色另由 api-mock 測試把關）
      if (rel(p) === "web/js/config.js" && /^https:\/\/[a-z0-9]{20}\.supabase\.co$/.test(m[0])) continue;
      if (!allowed.has(m[0])) urls.push(`${rel(p)}: ${m[0]}`);
    }
  }
  assert.deepEqual(urls, []);
});

test("lint：ui.js 只有一處 innerHTML（render.js 已 escape 的輸出），無 insertAdjacentHTML／outerHTML／document.write", () => {
  const s = read(join(root, "web/js/ui.js"));
  const uses = s.split("\n").filter((l) => /innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(l) && !/^\s*\/\//.test(l));
  assert.equal(uses.length, 1, uses.join("\n"));
  assert.match(uses[0], /view\.innerHTML = html;/);
});

test("web/js 的相對 import 都指向存在的檔", () => {
  const missing = [];
  for (const p of webFiles.filter((f) => extname(f) === ".js")) {
    for (const m of read(p).matchAll(/from\s+"(\.{1,2}\/[^"]+)"/g)) {
      if (!existsSync(join(dirname(p), m[1]))) missing.push(`${rel(p)} → ${m[1]}`);
    }
  }
  assert.deepEqual(missing, []);
  const html = read(join(root, "web/index.html"));
  for (const m of html.matchAll(/(?:href|src)="((?:css|js|img)\/[^"]+)"/g)) {
    assert.ok(existsSync(join(root, "web", m[1])), "index.html 引用不存在：" + m[1]);
  }
});

test("web/demo/sample.json 與 tests/fixtures/sample.json 逐位元相同", () => {
  assert.equal(read(join(root, "web/demo/sample.json")), read(join(root, "tests/fixtures/sample.json")));
});

const PROBES = join(root, "private", "leak_probes.txt");
test("探針字串不在 web/ tests/ docs/ tools/ supabase/ README", { skip: existsSync(PROBES) ? false : "private/leak_probes.txt 不存在" }, () => {
  const probes = read(PROBES).split(/\r?\n/).map((s) => s.trim()).filter((s) => s && !s.startsWith("#"));
  assert.ok(probes.length > 0, "探針檔沒有有效探針");
  const files = ["web", "tests", "docs", "tools", "supabase"].flatMap((d) => walk(join(root, d)))
    .filter((p) => TEXT_EXT.has(extname(p))).concat([join(root, "README.md")]);
  const hits = [];
  probes.forEach((pr, i) => {
    for (const p of files) if (read(p).includes(pr)) hits.push(`探針第 ${i + 1} 個 → ${rel(p)}`);
  });
  assert.deepEqual(hits, []);
  // 陽性對照：探針必須在私密 fixture 找得到，否則探針本身失效
  const fx = walk(join(root, "private", "fixtures")).map(read).join("\n");
  probes.forEach((pr, i) => assert.ok(fx.includes(pr), `探針第 ${i + 1} 個在 private/fixtures 找不到（探針失效）`));
});
