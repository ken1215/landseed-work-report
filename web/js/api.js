import { CONFIG } from "./config.js";

export const SUPABASE_CDN = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm";
const STORE_KEY = "lwr.mock.v1";
const STATUSES = ["同意", "再議", "請補資料"];

// 依 message 開頭比對；順序無重疊前綴
const ERROR_PREFIXES = [
  ["invalid token", "invalid_token"],
  ["forbidden", "forbidden"],
  ["not found", "not_found"],
  ["anchor not statusable", "anchor_not_statusable"],
  ["invalid status", "invalid_status"],
  ["body too long", "body_too_long"],
  ["body empty", "body_empty"],
  ["reply depth", "reply_depth"],
];

export class ApiError extends Error {
  constructor(code, message = code, status = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export function codeFromMessage(msg) {
  const m = String(msg || "");
  for (const [p, code] of ERROR_PREFIXES) if (m.startsWith(p)) return code;
  if (/fetch|network/i.test(m)) return "network";
  return "unknown";
}

const fail = (msg) => { throw new ApiError(codeFromMessage(msg), msg); };

export function createApi(config = CONFIG, opts = {}) {
  const c = config || {};
  if (!c.SUPABASE_URL || !c.SUPABASE_ANON_KEY) return new MockApi(opts);
  return new SupabaseApi(c, opts);
}

class BaseApi {
  constructor() { this.token = null; }
  setToken(token) { this.token = token || null; }
  _tok() {
    if (!this.token) fail("invalid token");
    return this.token;
  }
}

// ---------------- Supabase ----------------

class SupabaseApi extends BaseApi {
  constructor(config, opts) {
    super();
    this.mode = "supabase";
    this._config = config;
    this._import = opts.importModule || ((u) => import(u));
    this._client = null;
  }

  _getClient() {
    if (!this._client) {
      this._client = this._import(SUPABASE_CDN).then((mod) =>
        mod.createClient(this._config.SUPABASE_URL, this._config.SUPABASE_ANON_KEY, {
          auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
        }));
      this._client.catch(() => { this._client = null; });
    }
    return this._client;
  }

  async _rpc(fn, params) {
    const p_token = this._tok();
    let res;
    try {
      const client = await this._getClient();
      res = await client.rpc(fn, { p_token, ...params });
    } catch (e) {
      const msg = (e && e.message) || String(e);
      const code = codeFromMessage(msg);
      throw new ApiError(code === "unknown" && e instanceof TypeError ? "network" : code, msg);
    }
    if (res.error) {
      const msg = res.error.message || "";
      throw new ApiError(codeFromMessage(msg), msg, res.status ?? null);
    }
    return res.data;
  }

  whoami() { return this._rpc("rp_whoami", {}); }
  listReports() { return this._rpc("rp_list_reports", {}); }
  getReport(period) { return this._rpc("rp_get_report", { p_period: period }); }
  markRead(report_id) { return this._rpc("rp_mark_read", { p_report_id: report_id }); }
  listComments(report_id, since = null) {
    return this._rpc("rp_list_comments", { p_report_id: report_id, p_since: since ?? null });
  }
  addComment(report_id, anchor, body, parent_id = null) {
    return this._rpc("rp_add_comment", {
      p_report_id: report_id, p_anchor: anchor, p_body: body, p_parent_id: parent_id ?? null,
    });
  }
  editComment(comment_id, body) { return this._rpc("rp_edit_comment", { p_comment_id: comment_id, p_body: body }); }
  deleteComment(comment_id) { return this._rpc("rp_delete_comment", { p_comment_id: comment_id }); }
  setStatus(report_id, anchor, status) {
    return this._rpc("rp_set_status", { p_report_id: report_id, p_anchor: anchor, p_status: status ?? null });
  }
  markSeen(report_id) { return this._rpc("rp_mark_seen", { p_report_id: report_id }); }
}

// ---------------- Mock ----------------

const MOCK_READERS = {
  "demo-author": { reader_id: "r-author", name: "林踐宇", role: "author" },
  "demo-reader-1": { reader_id: "r-1", name: "張院長", role: "reader" },
  "demo-reader-2": { reader_id: "r-2", name: "讀者乙", role: "reader" },
};
const READER_LIST = Object.values(MOCK_READERS);
const nameOf = (id) => (READER_LIST.find((r) => r.reader_id === id) || {}).name || "";
const roleOf = (id) => (READER_LIST.find((r) => r.reader_id === id) || {}).role || "reader";

function memoryStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
  };
}

function defaultStorage() {
  try {
    const s = globalThis.localStorage;
    if (s) { s.getItem(STORE_KEY); return s; }
  } catch (e) { /* 私密視窗等情況 */ }
  return memoryStorage();
}

async function fetchJson(url) {
  let r;
  try { r = await fetch(url, { cache: "no-store" }); } catch (e) { fail("network: " + e.message); }
  if (!r.ok) fail(r.status === 404 ? "not found" : "network: HTTP " + r.status);
  return r.json();
}

const ms = (iso) => (iso ? Date.parse(iso) : -Infinity);

class MockApi extends BaseApi {
  constructor(opts = {}) {
    super();
    this.mode = "mock";
    this._storage = opts.storage || defaultStorage();
    this._fallback = null;
    this._loadIndex = opts.loadIndex || (() => fetchJson("../private/mock/index.json"));
    this._loadReport = opts.loadReport ||
      ((period) => fetchJson("../private/mock/" + encodeURIComponent(period) + ".json"));
    this._now = opts.now || (() => new Date());
    this._index = null;
    this._reports = new Map();
  }

  _nowIso() { return this._now().toISOString(); }

  // storage 任一操作失敗（私密模式、配額滿）→ 改用記憶體，並帶入最後已知狀態
  _degrade() {
    const mem = memoryStorage();
    if (this._fallback != null) mem.setItem(STORE_KEY, this._fallback);
    this._storage = mem;
  }

  _read() {
    let raw = null;
    try { raw = this._storage.getItem(STORE_KEY); } catch (e) {
      this._degrade();
      raw = this._storage.getItem(STORE_KEY);
    }
    if (raw != null) this._fallback = raw;
    let s = null;
    try { s = raw ? JSON.parse(raw) : null; } catch (e) { s = null; }
    s = s && typeof s === "object" ? s : {};
    for (const k of ["comments", "statuses", "reads", "seen"]) if (!Array.isArray(s[k])) s[k] = [];
    return s;
  }

  _write(s) {
    const raw = JSON.stringify(s);
    this._fallback = raw;
    try { this._storage.setItem(STORE_KEY, raw); } catch (e) { this._degrade(); }
  }

  _me() {
    const me = MOCK_READERS[this._tok()];
    if (!me) fail("invalid token");
    return me;
  }

  async _indexRows() {
    if (!this._index) {
      const idx = await this._loadIndex();
      this._index = ((idx && idx.reports) || []).slice()
        .sort((a, b) => (a.period < b.period ? 1 : a.period > b.period ? -1 : 0));
    }
    return this._index;
  }

  async _metaById(report_id) {
    const row = (await this._indexRows()).find((r) => r.report_id === report_id);
    if (!row) fail("not found");
    return row;
  }

  async _report(period) {
    if (!this._reports.has(period)) {
      let rep;
      try { rep = await this._loadReport(period); } catch (e) {
        if (e instanceof ApiError) throw e;
        fail("not found");
      }
      if (!rep) fail("not found");
      this._reports.set(period, rep);
    }
    return this._reports.get(period);
  }

  _outComment(c) {
    return {
      id: c.id, anchor: c.anchor, reader_id: c.reader_id, reader_name: nameOf(c.reader_id),
      role: roleOf(c.reader_id), parent_id: c.parent_id, body: c.deleted ? "" : c.body,
      created_at: c.created_at, edited_at: c.edited_at, deleted: !!c.deleted, orphaned: !!c.orphaned,
    };
  }

  _outStatus(s) {
    return { anchor: s.anchor, reader_id: s.reader_id, reader_name: nameOf(s.reader_id), status: s.status, updated_at: s.updated_at };
  }

  _checkBody(body) {
    const b = typeof body === "string" ? body.trim() : "";
    if (b.length === 0) fail("body empty");
    if (b.length > 2000) fail("body too long");
    return b;
  }

  _nextId(s) {
    let max = 0;
    for (const c of s.comments) {
      const n = parseInt(String(c.id).slice(1), 10);
      if (n > max) max = n;
    }
    return "c" + (max + 1);
  }

  async whoami() {
    return { ...this._me() };
  }

  async listReports() {
    const me = this._me();
    const rows = await this._indexRows();
    const s = this._read();
    return rows.map((r) => {
      const rid = r.report_id;
      const live = s.comments.filter((c) => c.report_id === rid && !c.deleted);
      const seen = s.seen.find((x) => x.report_id === rid && x.reader_id === me.reader_id);
      const after = seen ? ms(seen.last_seen_comment_at) : -Infinity;
      const mineIds = new Set(s.comments.filter((c) => c.report_id === rid && c.reader_id === me.reader_id).map((c) => c.id));
      const unread = live.filter((c) => c.reader_id !== me.reader_id && ms(c.created_at) > after);
      const read = s.reads.find((x) => x.report_id === rid && x.reader_id === me.reader_id);
      const readers = me.role === "author"
        ? READER_LIST.filter((x) => x.role === "reader").map((x) => {
          const rd = s.reads.find((y) => y.report_id === rid && y.reader_id === x.reader_id);
          return { reader_id: x.reader_id, name: x.name, first_at: rd ? rd.first_at : null, last_at: rd ? rd.last_at : null };
        })
        : [];
      return {
        report_id: rid, period: r.period, title: r.title, published_at: r.published_at, version: r.version,
        first_at: read ? read.first_at : null, last_at: read ? read.last_at : null,
        comment_count: live.length,
        unread_count: unread.length,
        unread_replies: unread.filter((c) => c.parent_id && mineIds.has(c.parent_id)).length,
        readers,
      };
    });
  }

  async getReport(period) {
    this._me();
    const row = (await this._indexRows()).find((r) => r.period === period);
    if (!row) fail("not found");
    return structuredClone(await this._report(period));
  }

  async markRead(report_id) {
    const me = this._me();
    await this._metaById(report_id);
    const s = this._read();
    const now = this._nowIso();
    let r = s.reads.find((x) => x.report_id === report_id && x.reader_id === me.reader_id);
    if (r) r.last_at = now;
    else { r = { report_id, reader_id: me.reader_id, first_at: now, last_at: now }; s.reads.push(r); }
    this._write(s);
    return { first_at: r.first_at, last_at: r.last_at };
  }

  async listComments(report_id, since = null) {
    this._me();
    await this._metaById(report_id);
    const server_time = this._nowIso();
    const s = this._read();
    const t = since == null ? null : ms(since);
    const comments = s.comments
      .filter((c) => c.report_id === report_id)
      .filter((c) => t === null || Math.max(ms(c.created_at), ms(c.edited_at || c.created_at)) > t)
      .sort((a, b) => ms(a.created_at) - ms(b.created_at))
      .map((c) => this._outComment(c));
    const statuses = s.statuses
      .filter((x) => x.report_id === report_id && (t === null || ms(x.updated_at) > t))
      .map((x) => this._outStatus(x));
    return { server_time, comments, statuses };
  }

  async addComment(report_id, anchor, body, parent_id = null) {
    const me = this._me();
    await this._metaById(report_id);
    const b = this._checkBody(body);
    const s = this._read();
    if (parent_id != null) {
      const p = s.comments.find((c) => c.id === parent_id && c.report_id === report_id);
      if (!p) fail("not found");
      if (p.parent_id != null) fail("reply depth");
      anchor = p.anchor;  // 同 rp_add_comment：回覆沿用父留言錨點
    }
    const c = {
      id: this._nextId(s), report_id, anchor, reader_id: me.reader_id, parent_id: parent_id ?? null,
      body: b, created_at: this._nowIso(), edited_at: null, deleted: false, orphaned: false,
    };
    s.comments.push(c);
    this._write(s);
    return this._outComment(c);
  }

  _ownLive(s, comment_id, me) {
    const c = s.comments.find((x) => x.id === comment_id);
    if (!c) fail("not found");
    if (c.reader_id !== me.reader_id || c.deleted) fail("forbidden");
    return c;
  }

  async editComment(comment_id, body) {
    const me = this._me();
    const s = this._read();
    const c = this._ownLive(s, comment_id, me);
    c.body = this._checkBody(body);
    c.edited_at = this._nowIso();
    this._write(s);
    return this._outComment(c);
  }

  async deleteComment(comment_id) {
    const me = this._me();
    const s = this._read();
    const c = this._ownLive(s, comment_id, me);
    c.deleted = true;
    c.body = "";
    // 讓 listComments(since) 的增量輪詢能收到刪除
    c.edited_at = this._nowIso();
    this._write(s);
    return { id: c.id, deleted: true };
  }

  async setStatus(report_id, anchor, status) {
    const me = this._me();
    const meta = await this._metaById(report_id);
    if (me.role !== "reader") fail("forbidden");
    const rep = await this._report(meta.period);
    if (!(rep.status_anchors || []).includes(anchor)) fail("anchor not statusable");
    if (status != null && !STATUSES.includes(status)) fail("invalid status");
    const s = this._read();
    const i = s.statuses.findIndex((x) => x.report_id === report_id && x.anchor === anchor && x.reader_id === me.reader_id);
    if (status == null) {
      if (i >= 0) s.statuses.splice(i, 1);
      this._write(s);
      return null;
    }
    const row = { report_id, anchor, reader_id: me.reader_id, status, updated_at: this._nowIso() };
    if (i >= 0) s.statuses[i] = row; else s.statuses.push(row);
    this._write(s);
    return this._outStatus(row);
  }

  async markSeen(report_id) {
    const me = this._me();
    await this._metaById(report_id);
    const s = this._read();
    const times = s.comments.filter((c) => c.report_id === report_id).map((c) => c.created_at);
    const last = times.length
      ? times.reduce((a, b) => (ms(b) > ms(a) ? b : a))
      : this._nowIso();
    const row = s.seen.find((x) => x.report_id === report_id && x.reader_id === me.reader_id);
    if (row) row.last_seen_comment_at = last;
    else s.seen.push({ reader_id: me.reader_id, report_id, last_seen_comment_at: last });
    this._write(s);
    return { last_seen_comment_at: last };
  }
}
