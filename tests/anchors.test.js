import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  normalizeText, sha1hex, normalizeContent, buildAnchors,
} from "../web/js/anchors.js";

const here = dirname(fileURLToPath(import.meta.url));
const loadSample = () => JSON.parse(readFileSync(join(here, "fixtures/sample.json"), "utf8"));
const nodeSha1 = (s) => createHash("sha1").update(s, "utf8").digest("hex");

// CONTRACTS §3.7 逐列（anchor, kind, btype, bi, ri/li, statusable）
const EXPECTED_44 = `
s1/blk/f3bb269fce blk kicker 0
s1/blk/cfe6ac6f4d blk h1 0+1
s1/blk/b8da5c2822 blk callout 2
s1/blk/2ae3d27bf0 blk stats 3
s1/blk/884a3891d1 blk cap 4
s1/blk/50a5caa49b blk bars 5
s1/blk/993b636521 blk table 6
s1/row/22233ed062 row table 6 r1
s1/row/5045ff3771 row table 6 r2
s1/row/5c65f0409f row table 6 r3
s2/blk/d29ad4e6bf blk kicker 7
s2/blk/f47a10a6f5 blk h1 8
s2/blk/221b395626 blk table 9
s2/row/20ba44cd63 row table 9 r1
s2/row/da3d0c7364 row table 9 r2
s3/blk/4020e6f5e5 blk kicker 10
s3/blk/efb4e41335 blk h1 11
s3/blk/5e160e2629 blk day 12
s3/blk/402a8c4d38 blk table 13
s3/row/1806afac91 row table 13 r1
s3/row/2cb4a95d37 row table 13 r2
s3/blk/56c49e21dd blk photos 14
s3/blk/f31a726914 blk day 15
s3/blk/15f04f71a1 blk table 16
s3/row/47b7f70649 row table 16 r1
s3/row/47b7f70649-2 row table 16 r2
s3/row/8ad82fd7a7 row table 16 r3
s3/blk/063728c4b1 blk photos 17
s4/blk/b0a942ef66 blk kicker 18
s4/blk/a69bc56cda blk h1 19
s4/blk/07a07f3112 blk table 20
s4/row/42010f0754 row table 20 r1 S
s4/row/ce82e02d91 row table 20 r2 S
s4/blk/f0367e28fc blk bullets 21
s4/li/66accc3c3a li bullets 21 l0 S
s4/li/df3b87b7bd li bullets 21 l1 S
s4/li/66accc3c3a-2 li bullets 21 l2 S
s5/blk/5cd345aa56 blk kicker 22
s5/blk/7713a09072 blk h1 23
s5/blk/daf704c96e blk stats 24
s5/blk/eb0d05bfe0 blk table 25
s5/row/4746e777c1 row table 25 r1
s5/row/baa34e642e row table 25 r2
s5/blk/1fb6098dc5 blk footnote 26
`.trim().split("\n").map((line) => {
  const p = line.split(" ");
  const bi = Number(p[3].replace("0+", ""));
  const extra = p[4] || "";
  return {
    anchor: p[0], kind: p[1], btype: p[2], bi,
    ri: extra.startsWith("r") ? Number(extra.slice(1)) : null,
    li: extra.startsWith("l") ? Number(extra.slice(1)) : null,
    statusable: p.includes("S"),
  };
});

test("normalizeText：刪 ** !! 與八種空白，其他不動", () => {
  assert.equal(normalizeText("a **b** !!c!! d"), "abcd");
  assert.equal(normalizeText("x \u0009\u000A\u000D\u000C\u000B 　y"), "xy");
  assert.equal(normalizeText("**半**"), "半");
  assert.equal(normalizeText("*單!"), "*單!");
  assert.equal(normalizeText("ＡＢ ab Ab"), "ＡＢabAb");
  // \s 以外的字元（例如 U+2003、U+FEFF）必須保留
  assert.equal(normalizeText("a b﻿c"), "a b﻿c");
  assert.throws(() => normalizeText(12), TypeError);
  assert.throws(() => normalizeText(null), TypeError);
});

test("sha1hex 與 node:crypto 一致（短／長／CJK／多區塊填充邊界）", () => {
  const cases = ["", "abc", "a".repeat(55), "a".repeat(56), "a".repeat(64), "b".repeat(119),
    "中文字串含全形（）／、與 emoji 😀", "table|role|專案|參與角色|權責範圍／本期重點".repeat(7)];
  for (const s of cases) assert.equal(sha1hex(s), nodeSha1(s), JSON.stringify(s).slice(0, 40));
});

test("§3.6 手算範例（硬斷言）", () => {
  assert.equal(sha1hex("h1|一、本期重點事項"), "cfe6ac6f4d0eca44c553e4357df3b3c001d8cfa6");
  assert.equal(sha1hex("row|day|10月5日（一）|14:00|甲案進度會"), "2cb4a95d37271bebcb5049a0b67ddde4831a727a");
  assert.equal(sha1hex("li|追蹤：甲案補漆查驗10/8。"), "66accc3c3a25ec56b2c6da49dde2884ea3de71b7");
  assert.equal(sha1hex("row|day|10月6日（二）|09:00|工地巡檢"), "47b7f70649ba4b4e130a382fc97969b44b5d8f46");

  const { anchors, errors } = buildAnchors(normalizeContent(loadSample()));
  assert.deepEqual(errors, []);
  const by = (a) => anchors.find((e) => e.anchor === a);
  assert.equal(by("s1/blk/cfe6ac6f4d").bi, 1);
  assert.equal(by("s1/blk/cfe6ac6f4d").btype, "h1");
  assert.equal(by("s3/row/2cb4a95d37").bi, 13);
  assert.equal(by("s3/row/2cb4a95d37").ri, 2);
  assert.equal(by("s3/row/2cb4a95d37").text, "day|10月5日（一）|14:00|甲案進度會");
  assert.equal(by("s4/li/66accc3c3a").li, 0);
  assert.equal(by("s4/li/66accc3c3a-2").li, 2);
  assert.equal(by("s4/li/66accc3c3a-2").statusable, true);
  assert.equal(by("s3/row/47b7f70649-2").ri, 2);
  const ph = by("s3/blk/56c49e21dd");
  assert.equal(ph.bi, 14);
  assert.equal(ph.text, "3F／候診區：天花板補漆完成|B1／機房：水泵更換中|RF／水塔：漏水點已封");
});

test("§3.7 sample 全部 44 錨點逐列相符（硬斷言）", () => {
  const { anchors, errors } = buildAnchors(normalizeContent(loadSample()));
  assert.deepEqual(errors, []);
  assert.equal(anchors.length, 44);
  const got = anchors.map((a) => ({
    anchor: a.anchor, kind: a.kind, btype: a.btype, bi: a.bi, ri: a.ri, li: a.li, statusable: a.statusable,
  }));
  assert.deepEqual(got, EXPECTED_44);
  for (const a of anchors) {
    assert.equal(a.sec, a.anchor.split("/")[0]);
    assert.equal(typeof a.text, "string");
  }
  // 附帶 src 的列
  const src = (a) => (a.kind === "blk" ? a.btype : a.kind) + "|" + a.text;
  const find = (x) => anchors.find((e) => e.anchor === x);
  assert.equal(src(find("s1/blk/2ae3d27bf0")), "stats|12|項|本期事項|87|%|甲案進度|3||待決事項|1|件|新啟動專案");
  assert.equal(src(find("s1/blk/50a5caa49b")), "bars|甲案裝修|87/100曆日|乙案機電|60/60曆日|丙案規劃|5/120曆日|丁案保固|已結案|戊案評估|尚未開始");
  assert.equal(src(find("s1/row/22233ed062")), "row|seq|1|甲案");
  assert.equal(src(find("s2/blk/221b395626")), "table|role|專案|參與角色|權責範圍／本期重點|甲案|PCM|進度管控品質查驗|乙案|PCM|驗收與缺失追蹤");
});

test("status_anchors 只含 decision row 與 li", () => {
  const { anchors } = buildAnchors(normalizeContent(loadSample()));
  assert.deepEqual(anchors.filter((a) => a.statusable).map((a) => a.anchor),
    ["s4/row/42010f0754", "s4/row/ce82e02d91", "s4/li/66accc3c3a", "s4/li/df3b87b7bd", "s4/li/66accc3c3a-2"]);
});

test("normalizeContent：刪 outfile、插入 photos、冪等、不改原物件", () => {
  const raw = loadSample();
  const snapshot = JSON.stringify(raw);
  const c = normalizeContent(raw);
  assert.equal(JSON.stringify(raw), snapshot);
  assert.deepEqual(Object.keys(c).sort(), ["blocks", "from", "period", "title", "to"]);
  assert.equal(c.blocks.length, 27);
  assert.deepEqual(c.blocks[14], {
    photos: [
      { url: "photos/p1.jpg", cap: "3F／候診區：天花板補漆完成", path: "photos/p1.jpg" },
      { url: "photos/p2.jpg", cap: "B1／機房：水泵 **更換** 中", path: "photos/p2.jpg" },
      { url: "photos/p3.jpg", cap: "RF／水塔：!!漏水點!! 已封", path: "photos/p3.jpg" },
    ],
    cols: 3, day: "10月5日（一）",
  });
  assert.deepEqual(c.blocks[17].photos[0], { url: "photos/p4.jpg", cap: "B1／機房：新泵浦就位", path: "photos/p4.jpg" });
  assert.equal(c.blocks[17].cols, 2);
  assert.deepEqual(normalizeContent(c), c);
  assert.deepEqual(normalizeContent(JSON.parse(JSON.stringify(c))), c);
  // cap 缺省 → 空字串
  const r2 = normalizeContent({ title: "t", period: "p", to: "x", from: "y", blocks: [{ photos: [{ file: "a.jpg" }] }] });
  assert.deepEqual(r2.blocks[0].photos[0], { url: "a.jpg", cap: "", path: "a.jpg" });
});

test("normalizeContent：頂層 photos 找不到 day／其後無 table 時 throw", () => {
  const base = { title: "t", period: "p", to: "x", from: "y" };
  assert.throws(() => normalizeContent({ ...base, photos: { "不存在": [["a.jpg", "c"]] }, blocks: [{ day: "某日" }] }),
    { message: "photos day label not found: 不存在" });
  assert.throws(() => normalizeContent({ ...base, photos: { "某日": [["a.jpg", "c"]] }, blocks: [{ day: "某日" }, { cap: "x" }] }),
    { message: "no table after day: 某日" });
});

test("sec 規則：無 h1 前為 s0；kicker 後非 h1 不加；h1 前非 kicker 自行加", () => {
  const c = {
    title: "t", period: "p", to: "x", from: "y", blocks: [
      { cap: "前言" }, { kicker: "孤兒" }, { h1: "甲" }, { kicker: "K" }, { cap: "插" }, { h1: "乙" },
    ],
  };
  const { anchors } = buildAnchors(c);
  assert.deepEqual(anchors.map((a) => a.sec), ["s0", "s1", "s1", "s1", "s1", "s2"]);
});

test("去重只在同 sec 內、跨 block 累計", () => {
  const c = {
    title: "t", period: "p", to: "x", from: "y", blocks: [
      { h1: "一" }, { cap: "同" }, { cap: "同" }, { cap: "同" }, { h1: "二" }, { cap: "同" },
    ],
  };
  const a = buildAnchors(c).anchors.map((e) => e.anchor);
  const h = sha1hex("cap|同").slice(0, 10);
  assert.deepEqual(a.slice(1, 4), [`s1/blk/${h}`, `s1/blk/${h}-2`, `s1/blk/${h}-3`]);
  assert.equal(a[5], `s2/blk/${h}`);
});

test("row 的 day 標籤：無 day 前為空字串", () => {
  const c = { title: "t", period: "p", to: "x", from: "y", blocks: [{ table: { grid: "day", rows: [["a", "b", "c"], ["1", "2", "3"]] } }] };
  const row = buildAnchors(c).anchors.find((e) => e.kind === "row");
  assert.equal(row.anchor, "s0/row/" + sha1hex("row|day||1|2").slice(0, 10));
});

test("strict=true 遇錯丟出；strict=false 跳過該 block 但保留 bi 與 sec 計數", () => {
  const blocks = [
    { kicker: "K" }, { h1: "一" }, { mystery: 1 }, { table: { grid: "role", rows: [["a", "b"], ["1", "2"]] } },
    { cap: "c", h1: "兩型別" }, { stats: [{ v: 3 }, { v: "4" }] }, { h1: "二" }, { cap: "尾" },
  ];
  const c = { title: "t", period: "p", to: "x", from: "y", blocks };
  assert.throws(() => buildAnchors(c));
  assert.throws(() => buildAnchors(c, { strict: true }));
  const { anchors, errors } = buildAnchors(c, { strict: false });
  assert.equal(errors.length, 4);
  assert.deepEqual(anchors.map((a) => [a.sec, a.bi, a.btype]),
    [["s1", 0, "kicker"], ["s1", 1, "h1"], ["s2", 6, "h1"], ["s2", 7, "cap"]]);
});

test("anchor_vectors.json 一致（publish 產出後才比）", (t) => {
  const p = join(here, "anchor_vectors.json");
  if (!existsSync(p)) { t.skip("tests/anchor_vectors.json 不存在（publish 路產出後才比對）"); return; }
  const vec = JSON.parse(readFileSync(p, "utf8"));
  const { anchors } = buildAnchors(normalizeContent(loadSample()));
  assert.deepEqual(anchors, vec);
});

const PRIVATE = ["260928-1002.json", "260921-27.json"].map((f) => join(here, "..", "private", "fixtures", f));
for (const p of PRIVATE) {
  test(`私密 fixture 錨點無錯：${p.split("/").pop()}`, (t) => {
    if (!existsSync(p)) { t.skip("私密 fixture 不存在"); return; }
    const c = normalizeContent(JSON.parse(readFileSync(p, "utf8")));
    const { anchors, errors } = buildAnchors(c);
    assert.deepEqual(errors, []);
    assert.ok(anchors.length > c.blocks.length);
    assert.equal(new Set(anchors.map((a) => a.anchor)).size, anchors.length);
  });
}
