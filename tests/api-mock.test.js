import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi, ApiError } from "../web/js/api.js";
import { CONFIG } from "../web/js/config.js";

const P1 = "261005-07";
const P2 = "261001-03";
const SA = ["s4/row/aaaaaaaaaa", "s4/li/bbbbbbbbbb"];

const INDEX = {
  reports: [
    { report_id: "m-" + P1, period: P1, title: "報告甲", published_at: "2026-10-07T10:00:00+00:00", version: 1, comment_count: 99 },
    { report_id: "m-" + P2, period: P2, title: "報告乙", published_at: "2026-10-02T10:00:00+00:00", version: 2, comment_count: 99 },
  ],
};

function reportJson(period) {
  const meta = INDEX.reports.find((r) => r.period === period);
  return {
    report_id: meta.report_id, period, title: meta.title, version: meta.version,
    published_at: meta.published_at, status_anchors: SA,
    content: { title: meta.title, period, to: "甲", from: "乙", blocks: [{ h1: "一、測試" }] },
  };
}

function memStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    _map: m,
  };
}

function setup() {
  const storage = memStorage();
  let t = Date.parse("2026-10-09T00:00:00Z");
  const now = () => new Date((t += 1000));
  const opts = {
    storage, now,
    loadIndex: async () => structuredClone(INDEX),
    loadReport: async (p) => {
      if (!INDEX.reports.some((r) => r.period === p)) throw new Error("404");
      return reportJson(p);
    },
    importModule: async () => { throw new Error("mock must not import CDN"); },
  };
  const as = (token) => {
    const api = createApi({ SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }, opts);
    api.setToken(token);
    return api;
  };
  return { storage, as, opts };
}

async function rejects(p, code) {
  await assert.rejects(p, (e) => {
    assert.ok(e instanceof ApiError, "應為 ApiError：" + e);
    assert.equal(e.code, code);
    return true;
  });
}

const RID = "m-" + P1;

test("config：空值走 mock；填值時必須是專案網址＋anon 角色金鑰（絕不可是 service_role）", () => {
  if (!CONFIG.SUPABASE_URL && !CONFIG.SUPABASE_ANON_KEY) {
    assert.equal(createApi(CONFIG, { storage: memStorage() }).mode, "mock");
  } else {
    assert.match(CONFIG.SUPABASE_URL, /^https:\/\/[a-z0-9]{20}\.supabase\.co$/);
    const payload = JSON.parse(Buffer.from(CONFIG.SUPABASE_ANON_KEY.split(".")[1], "base64url").toString());
    assert.equal(payload.role, "anon", "config.js 只能放 anon key");
    assert.equal(CONFIG.SUPABASE_URL, `https://${payload.ref}.supabase.co`, "金鑰與網址須屬同一專案");
    assert.equal(createApi(CONFIG, { storage: memStorage() }).mode, "supabase");
  }
  assert.equal(createApi({ SUPABASE_URL: "https://x.supabase.co" }, { storage: memStorage() }).mode, "mock");
});

test("whoami 三身分與無效 token", async () => {
  const { as, opts } = setup();
  assert.deepEqual(await as("demo-author").whoami(), { reader_id: "r-author", name: "林踐宇", role: "author" });
  assert.deepEqual(await as("demo-reader-1").whoami(), { reader_id: "r-1", name: "張院長", role: "reader" });
  assert.deepEqual(await as("demo-reader-2").whoami(), { reader_id: "r-2", name: "讀者乙", role: "reader" });
  await rejects(as("nope").whoami(), "invalid_token");
  await rejects(as("").listReports(), "invalid_token");
  const noTok = createApi({}, opts);
  await rejects(noTok.whoami(), "invalid_token");
  await assert.rejects(as("nope").whoami(), (e) => e.message === "invalid token");
});

test("listReports：排序、只取 index 欄位、comment_count 現算", async () => {
  const { as } = setup();
  const list = await as("demo-reader-1").listReports();
  assert.deepEqual(list.map((r) => r.period), [P1, P2]);
  const r = list[0];
  for (const k of ["report_id", "period", "title", "published_at", "version", "first_at", "last_at", "comment_count", "unread_count", "unread_replies", "readers"]) {
    assert.ok(k in r, "缺鍵 " + k);
  }
  assert.equal(r.comment_count, 0);
  assert.equal(r.first_at, null);
  assert.equal(r.last_at, null);
  assert.deepEqual(r.readers, []);
  const al = await as("demo-author").listReports();
  assert.deepEqual(al[0].readers.map((x) => [x.reader_id, x.name, x.first_at, x.last_at]),
    [["r-1", "張院長", null, null], ["r-2", "讀者乙", null, null]]);
});

test("getReport 與 not found", async () => {
  const { as } = setup();
  const rep = await as("demo-reader-1").getReport(P1);
  assert.equal(rep.report_id, RID);
  assert.deepEqual(rep.status_anchors, SA);
  assert.equal(rep.content.blocks[0].h1, "一、測試");
  await rejects(as("demo-reader-1").getReport("999999"), "not_found");
  await rejects(as("bad").getReport(P1), "invalid_token");
});

test("markRead：首次填 first_at，之後只更新 last_at；作者首頁看到讀者已閱", async () => {
  const { as } = setup();
  const r1 = as("demo-reader-1");
  const a = await r1.markRead(RID);
  assert.ok(a.first_at && a.first_at === a.last_at);
  const b = await r1.markRead(RID);
  assert.equal(b.first_at, a.first_at);
  assert.ok(new Date(b.last_at) > new Date(a.last_at));
  const mine = (await r1.listReports()).find((x) => x.report_id === RID);
  assert.equal(mine.first_at, a.first_at);
  assert.equal(mine.last_at, b.last_at);
  const al = await as("demo-author").listReports();
  const rd = al.find((x) => x.report_id === RID).readers;
  assert.equal(rd.find((x) => x.reader_id === "r-1").first_at, a.first_at);
  assert.equal(rd.find((x) => x.reader_id === "r-2").first_at, null);
  await rejects(r1.markRead("m-nope"), "not_found");
});

test("addComment → 回覆 parent → editComment → deleteComment（僅本人）", async () => {
  const { as, storage } = setup();
  const r1 = as("demo-reader-1"), au = as("demo-author"), r2 = as("demo-reader-2");
  const c1 = await r1.addComment(RID, "s1/blk/cfe6ac6f4d", "  請補充說明  ");
  assert.equal(c1.id, "c1");
  assert.deepEqual(Object.keys(c1).sort(),
    ["anchor", "body", "created_at", "deleted", "edited_at", "id", "orphaned", "parent_id", "reader_id", "reader_name", "role"].sort());
  assert.equal(c1.body, "請補充說明");
  assert.equal(c1.reader_name, "張院長");
  assert.equal(c1.role, "reader");
  assert.equal(c1.parent_id, null);
  assert.equal(c1.edited_at, null);
  assert.equal(c1.deleted, false);
  assert.equal(c1.orphaned, false);

  const rep = await au.addComment(RID, "s1/blk/cfe6ac6f4d", "已補充", c1.id);
  assert.equal(rep.id, "c2");
  assert.equal(rep.parent_id, "c1");
  assert.equal(rep.role, "author");
  await rejects(r1.addComment(RID, "s1/blk/cfe6ac6f4d", "再回", rep.id), "reply_depth");
  await rejects(r1.addComment(RID, "s1/blk/cfe6ac6f4d", "x", "c999"), "not_found");
  await rejects(r1.addComment("m-" + P2, "s1/blk/cfe6ac6f4d", "跨報告", c1.id), "not_found");

  await rejects(r1.addComment(RID, "a", "   "), "body_empty");
  await rejects(r1.addComment(RID, "a", ""), "body_empty");
  await rejects(r1.addComment(RID, "a", "字".repeat(2001)), "body_too_long");
  const ok2000 = await r1.addComment(RID, "a", "字".repeat(2000));
  assert.equal(ok2000.body.length, 2000);
  await rejects(r1.addComment("m-nope", "a", "x"), "not_found");

  await rejects(r2.editComment(c1.id, "改別人"), "forbidden");
  await rejects(au.editComment(c1.id, "改別人"), "forbidden");
  await rejects(r1.editComment(c1.id, "  "), "body_empty");
  await rejects(r1.editComment("c999", "x"), "not_found");
  const ed = await r1.editComment(c1.id, "請補充說明（修）");
  assert.equal(ed.body, "請補充說明（修）");
  assert.ok(ed.edited_at);

  await rejects(r2.deleteComment(c1.id), "forbidden");
  assert.deepEqual(await r1.deleteComment(c1.id), { id: c1.id, deleted: true });
  await rejects(r1.editComment(c1.id, "刪後再改"), "forbidden");
  await rejects(r1.deleteComment(c1.id), "forbidden");

  const all = await r2.listComments(RID);
  assert.ok(all.server_time);
  const dc = all.comments.find((c) => c.id === c1.id);
  assert.equal(dc.deleted, true);
  assert.equal(dc.body, "");
  assert.ok(all.comments.find((c) => c.id === rep.id), "回覆保留");
  assert.deepEqual(all.comments.map((c) => c.id), ["c1", "c2", "c3"]);

  // 狀態持久化於 lwr.mock.v1；新實例讀得回
  const raw = JSON.parse(storage.getItem("lwr.mock.v1"));
  for (const k of ["comments", "statuses", "reads", "seen"]) assert.ok(Array.isArray(raw[k]));
  const again = await as("demo-author").listComments(RID);
  assert.equal(again.comments.length, 3);
});

test("回覆跨錨點 → 一律落在父留言錨點（同 rp_add_comment）", async () => {
  const { as } = setup();
  const r1 = as("demo-reader-1"), au = as("demo-author");
  const c1 = await r1.addComment(RID, "s1/blk/cfe6ac6f4d", "問題");
  const cross = await au.addComment(RID, "s9/row/ffffffffff", "跨錨點回覆", c1.id);
  assert.equal(cross.anchor, c1.anchor);
});

test("listComments since：只回新增／編輯／刪除與狀態異動", async () => {
  const { as } = setup();
  const r1 = as("demo-reader-1");
  const c1 = await r1.addComment(RID, "a", "一");
  const c2 = await r1.addComment(RID, "a", "二");
  const t0 = (await r1.listComments(RID)).server_time;
  assert.equal((await r1.listComments(RID, t0)).comments.length, 0);
  await r1.editComment(c1.id, "一改");
  await r1.deleteComment(c2.id);
  await r1.setStatus(RID, SA[0], "再議");
  const d = await r1.listComments(RID, t0);
  assert.deepEqual(d.comments.map((c) => c.id).sort(), [c1.id, c2.id].sort());
  assert.equal(d.statuses.length, 1);
});

test("setStatus：僅讀者、僅可指示錨點、三選一、null 清除", async () => {
  const { as } = setup();
  const r1 = as("demo-reader-1"), r2 = as("demo-reader-2"), au = as("demo-author");
  const s = await r1.setStatus(RID, SA[0], "同意");
  assert.deepEqual(Object.keys(s).sort(), ["anchor", "reader_id", "reader_name", "status", "updated_at"]);
  assert.equal(s.status, "同意");
  assert.equal(s.reader_name, "張院長");
  const s2 = await r1.setStatus(RID, SA[0], "請補資料");
  assert.equal(s2.status, "請補資料");
  await r2.setStatus(RID, SA[0], "再議");
  await r2.setStatus(RID, SA[1], "同意");

  await rejects(au.setStatus(RID, SA[0], "同意"), "forbidden");
  await rejects(r1.setStatus(RID, "s1/blk/cfe6ac6f4d", "同意"), "anchor_not_statusable");
  await rejects(r1.setStatus(RID, SA[0], "OK"), "invalid_status");
  await rejects(as("x").setStatus(RID, SA[0], "同意"), "invalid_token");

  let st = (await au.listComments(RID)).statuses;
  assert.equal(st.length, 3, "每位讀者每錨點一個最新值");
  assert.equal(st.find((x) => x.reader_id === "r-1" && x.anchor === SA[0]).status, "請補資料");

  assert.equal(await r2.setStatus(RID, SA[1], null), null);
  st = (await au.listComments(RID)).statuses;
  assert.equal(st.length, 2);
});

test("未讀：作者回覆後讀者 +1（unread_replies），markSeen 後歸零", async () => {
  const { as } = setup();
  const r1 = as("demo-reader-1"), r2 = as("demo-reader-2"), au = as("demo-author");
  const pick = async (api) => (await api.listReports()).find((x) => x.report_id === RID);

  const c1 = await r1.addComment(RID, "a", "讀者留言");
  let A = await pick(au);
  assert.equal(A.unread_count, 1, "讀者留言 → 作者未讀 1");
  assert.equal(A.unread_replies, 0);
  assert.equal(A.comment_count, 1);
  assert.equal((await pick(r1)).unread_count, 0, "自己的留言不算未讀");

  await r1.markSeen(RID);
  await au.addComment(RID, "a", "作者回覆", c1.id);
  let R = await pick(r1);
  assert.equal(R.unread_count, 1);
  assert.equal(R.unread_replies, 1);
  let R2 = await pick(r2);
  assert.equal(R2.unread_count, 2);
  assert.equal(R2.unread_replies, 0, "非回覆本人");

  const seen = await r1.markSeen(RID);
  assert.ok(seen.last_seen_comment_at);
  R = await pick(r1);
  assert.equal(R.unread_count, 0);
  assert.equal(R.unread_replies, 0);

  const c3 = await au.addComment(RID, "b", "作者新留言");
  assert.equal((await pick(r1)).unread_count, 1);
  await au.deleteComment(c3.id);
  assert.equal((await pick(r1)).unread_count, 0, "已刪不算未讀");

  // 無留言時 markSeen 也回時間
  const e = await r1.markSeen("m-" + P2);
  assert.ok(e.last_seen_comment_at);
});

test("ApiError 形狀", () => {
  const e = new ApiError("forbidden", "forbidden");
  assert.ok(e instanceof Error);
  assert.equal(e.code, "forbidden");
  assert.equal(e.message, "forbidden");
});

test("storage setItem 失敗（配額滿）→ 退回記憶體，狀態不遺失", async () => {
  const st = memStorage();
  let n = 0;
  const flaky = { getItem: st.getItem, removeItem: st.removeItem,
    setItem: (k, v) => { if (++n > 1) throw new Error("QuotaExceededError"); st.setItem(k, v); } };
  const api = createApi({}, {
    storage: flaky,
    loadIndex: async () => structuredClone(INDEX),
    loadReport: async (p) => reportJson(p),
  });
  api.setToken("demo-reader-1");
  await api.addComment(RID, "a", "第一則");
  await api.addComment(RID, "a", "第二則");
  await api.addComment(RID, "a", "第三則");
  const got = await api.listComments(RID);
  assert.deepEqual(got.comments.map((c) => c.body), ["第一則", "第二則", "第三則"]);
});

// ---- supabase 實作：以假 client 驗 RPC 名稱與參數名 ----

function fakeSupabase(respond) {
  const calls = [];
  const created = [];
  const mod = {
    createClient: (url, key, o) => {
      created.push([url, key, o]);
      return {
        rpc: async (fn, params) => {
          calls.push([fn, params]);
          return respond(fn, params);
        },
      };
    },
  };
  return { calls, created, mod };
}

const SBCFG = { SUPABASE_URL: "https://proj.supabase.co", SUPABASE_ANON_KEY: "anon-key" };

test("supabase：RPC 名稱與 p_* 參數名、CDN URL 釘版、data 原樣透傳", async () => {
  const f = fakeSupabase((fn) => ({ data: { fn }, error: null }));
  const imported = [];
  const api = createApi(SBCFG, { importModule: async (u) => { imported.push(u); return f.mod; } });
  assert.equal(api.mode, "supabase");
  assert.equal(imported.length, 0, "延遲載入");
  await rejects(api.whoami(), "invalid_token");
  api.setToken("tok");

  const T = "tok";
  const exp = [
    [() => api.whoami(), "rp_whoami", { p_token: T }],
    [() => api.listReports(), "rp_list_reports", { p_token: T }],
    [() => api.getReport("P"), "rp_get_report", { p_token: T, p_period: "P" }],
    [() => api.markRead("R"), "rp_mark_read", { p_token: T, p_report_id: "R" }],
    [() => api.listComments("R"), "rp_list_comments", { p_token: T, p_report_id: "R", p_since: null }],
    [() => api.listComments("R", "2026-10-09T00:00:00Z"), "rp_list_comments", { p_token: T, p_report_id: "R", p_since: "2026-10-09T00:00:00Z" }],
    [() => api.addComment("R", "A", "B"), "rp_add_comment", { p_token: T, p_report_id: "R", p_anchor: "A", p_body: "B", p_parent_id: null }],
    [() => api.addComment("R", "A", "B", "P0"), "rp_add_comment", { p_token: T, p_report_id: "R", p_anchor: "A", p_body: "B", p_parent_id: "P0" }],
    [() => api.editComment("C", "B"), "rp_edit_comment", { p_token: T, p_comment_id: "C", p_body: "B" }],
    [() => api.deleteComment("C"), "rp_delete_comment", { p_token: T, p_comment_id: "C" }],
    [() => api.setStatus("R", "A", "同意"), "rp_set_status", { p_token: T, p_report_id: "R", p_anchor: "A", p_status: "同意" }],
    [() => api.setStatus("R", "A", null), "rp_set_status", { p_token: T, p_report_id: "R", p_anchor: "A", p_status: null }],
    [() => api.markSeen("R"), "rp_mark_seen", { p_token: T, p_report_id: "R" }],
  ];
  for (const [call, fn, params] of exp) {
    const out = await call();
    assert.deepEqual(out, { fn });
    assert.deepEqual(f.calls.at(-1), [fn, params]);
  }
  assert.deepEqual(imported, ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm"]);
  assert.equal(f.created.length, 1);
  assert.equal(f.created[0][0], SBCFG.SUPABASE_URL);
  assert.equal(f.created[0][1], SBCFG.SUPABASE_ANON_KEY);
});

test("supabase：error.message 開頭比對映射 code", async () => {
  const table = [
    ["invalid token", "invalid_token"],
    ["forbidden", "forbidden"],
    ["not found", "not_found"],
    ["anchor not statusable", "anchor_not_statusable"],
    ["invalid status", "invalid_status"],
    ["body too long", "body_too_long"],
    ["body empty", "body_empty"],
    ["reply depth", "reply_depth"],
    ["TypeError: Failed to fetch", "network"],
    ["something weird", "unknown"],
  ];
  for (const [msg, code] of table) {
    const f = fakeSupabase(() => ({ data: null, error: { message: msg, code: "P0001" } }));
    const api = createApi(SBCFG, { importModule: async () => f.mod });
    api.setToken("t");
    await assert.rejects(api.whoami(), (e) => {
      assert.ok(e instanceof ApiError);
      assert.equal(e.code, code, msg);
      assert.equal(e.message, msg);
      return true;
    });
  }
  const f = fakeSupabase(() => { throw new TypeError("fetch failed"); });
  const api = createApi(SBCFG, { importModule: async () => f.mod });
  api.setToken("t");
  await rejects(api.whoami(), "network");
});

// publish --mock 產出存在才跑（整合階段應存在）：驗 §6.2／§6.3 形狀可被 mock 直接吃
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
const MOCK_DIR = fileURLToPath(new URL("../private/mock/", import.meta.url));
const hasMock = existsSync(MOCK_DIR + "index.json");
test("private/mock 對接（publish --mock 產出）", { skip: hasMock ? false : "private/mock/index.json 不存在（尚未跑 publish --mock）" }, async () => {
  const rd = (f) => JSON.parse(readFileSync(MOCK_DIR + f, "utf8"));
  const api = createApi({}, {
    storage: memStorage(),
    loadIndex: async () => rd("index.json"),
    loadReport: async (p) => rd(p + ".json"),
  });
  api.setToken("demo-reader-1");
  const list = await api.listReports();
  assert.ok(list.length >= 1);
  const rep = await api.getReport(list[0].period);
  assert.equal(rep.report_id, list[0].report_id);
  assert.ok(Array.isArray(rep.status_anchors));
  for (const b of rep.content.blocks) {
    if (!b.photos) continue;
    for (const ph of b.photos) assert.ok(ph.url.startsWith("../private/mock/photos/"), ph.url);
  }
  if (rep.status_anchors.length) {
    const s = await api.setStatus(rep.report_id, rep.status_anchors[0], "同意");
    assert.equal(s.status, "同意");
  }
});
