// 路由、留言抽屜、已閱、狀態鈕、徽章、輪詢（CONTRACTS §4.3、§5.5）
// 規則：使用者產生的文字一律 textContent；唯一的 innerHTML 是 render.js 已逐欄 escape 的報告本體。
import { CONFIG } from "./config.js";
import { createApi } from "./api.js";
import { renderReport } from "./render.js";
import { normalizeContent, buildAnchors } from "./anchors.js";

// false＝單向模式：只陳述報告內容，不開留言／狀態鈕／輪詢（已閱仍在背景記錄，作者首頁看得到）
// 要恢復雙向，改回 true 即可
const TWO_WAY = false;
const POLL_MS = 20000;
const FULL_EVERY = 6; // 每 6 次輪詢全量重抓一次（增量抓不到被清除的狀態）
const TOKEN_KEY = "lwr.token";
const MOCK_KEY = "lwr.mock.v1";
const STATUSES = ["同意", "再議", "請補資料"];
const DEMO_PERIOD = "sample";
const DEMO_IDS = [
  ["demo-author", "作者（林踐宇）"],
  ["demo-reader-1", "讀者（張院長）"],
  ["demo-reader-2", "讀者（讀者乙）"],
];
const ERR_TEXT = {
  body_empty: "請輸入留言內容。",
  body_too_long: "留言不可超過 2000 字。",
  forbidden: "沒有權限執行這個動作。",
  not_found: "找不到資料，可能已被刪除。",
  reply_depth: "只能回覆第一層留言。",
  anchor_not_statusable: "這個項目不能標示狀態。",
  invalid_status: "狀態值不正確。",
  network: "連線失敗，請稍後再試。",
};

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) n.append(c);
  return n;
}

const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 私密視窗 */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* 私密視窗 */ } },
};

const fmtTime = (() => {
  const f = new Intl.DateTimeFormat("zh-TW", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  return (iso) => (iso ? f.format(new Date(iso)) : "");
})();
const ms = (iso) => (iso ? new Date(iso).getTime() : 0);

// ---------- demo 資料（mock 模式；GitHub Pages 只發佈 web/，所以讀 web/demo/） ----------

function demoLoaders() {
  let raw = null;
  const getRaw = async () => {
    if (!raw) {
      const r = await fetch("demo/sample.json", { cache: "no-store" });
      if (!r.ok) throw new Error("demo sample HTTP " + r.status);
      raw = await r.json();
    }
    return raw;
  };
  const published_at = "2026-10-07T09:00:00+08:00";
  return {
    loadIndex: async () => {
      const r = await getRaw();
      return { reports: [{ report_id: "m-" + DEMO_PERIOD, period: DEMO_PERIOD, title: r.title, published_at, version: 1, comment_count: 0 }] };
    },
    loadReport: async (period) => {
      if (period !== DEMO_PERIOD) return null;
      const content = normalizeContent(await getRaw());
      for (const b of content.blocks) {
        if (Array.isArray(b.photos)) b.photos = b.photos.map((p) => ({ ...p, url: "demo/photo.svg", path: "demo/photo.svg" }));
      }
      const { anchors } = buildAnchors(content, { strict: true });
      return {
        report_id: "m-" + DEMO_PERIOD, period: DEMO_PERIOD, title: content.title, content, version: 1, published_at,
        status_anchors: anchors.filter((a) => a.statusable).map((a) => a.anchor),
      };
    },
  };
}

// ---------- 狀態 ----------

const isMock = !CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY;
// ?local=1：從專案根目錄起伺服器時改讀 private/mock（publish.py --mock 產物）預覽真實期別；Pages 上沒有 private/，自然 404
const useLocal = isMock && new URLSearchParams(location.search).has("local");
const S = {
  api: createApi(CONFIG, isMock && !useLocal ? demoLoaders() : {}),
  token: null,
  me: null,
  view: null,
  seq: 0,
  report: null,
  comments: new Map(),  // id → comment
  statuses: new Map(),  // anchor\u0000reader_id → status
  units: new Map(),     // anchor → {node, btn, bar, label, statusable}
  since: null,
  pollN: 0,
  timer: null,
  drawer: null,
  busy: false,          // 抽屜內有編輯／回覆表單時不重繪清單
};

function showView(name) {
  S.view = name;
  $("home").hidden = name !== "home";
  $("report").hidden = name !== "report";
  $("notice").hidden = name !== "notice";
}

function showNotice(text) {
  stopPoll();
  closeDrawer();
  $("notice").textContent = text;
  showView("notice");
}

function errText(e) {
  return ERR_TEXT[e && e.code] || "發生錯誤：" + ((e && e.message) || e);
}

function handleFatal(e) {
  if (e && e.code === "invalid_token") {
    store.del(TOKEN_KEY);
    S.token = null;
    S.me = null;
    $("who").hidden = true;
    showNotice("連結無效或已停用，請向林踐宇索取新的專屬連結。");
    return;
  }
  console.error(e);
  showNotice(errText(e));
}

// ---------- 路由 ----------

function parseHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ""));
  return { k: p.get("k"), r: p.get("r"), s: p.get("s") };
}

function paintReport(content) {
  const view = $("report");
  const { html } = renderReport(content);
  view.innerHTML = html; // render.js 輸出：所有欄位已 escape
  return view;
}

// 分享連結（#s=<key>）：一把金鑰對應一期，直接顯示、不登入、不顯示期別清單與身分
async function openShared(key, seq) {
  stopPoll();
  closeDrawer();
  $("who").hidden = true;
  $("demo-bar").hidden = true;
  let rep;
  try {
    rep = await S.api.getShared(key);
  } catch (e) {
    if (seq !== S.seq) return;
    if (e && e.code === "invalid_token") {
      showNotice("此報告連結無效或已更換，請向林踐宇索取最新連結。");
      return;
    }
    console.error(e);
    showNotice(errText(e));
    return;
  }
  if (seq !== S.seq) return;
  S.report = rep;
  paintReport(rep.content);
  showView("report");
  document.title = (rep.content && rep.content.period ? rep.content.period + "｜" : "") + "林踐宇工作報告";
}

function drawDemoBar(period) {
  const bar = $("demo-bar");
  if (!isMock) { bar.hidden = true; return; }
  const suffix = period ? "&r=" + encodeURIComponent(period) : "";
  bar.replaceChildren(
    el("strong", { text: "示範模式" }),
    TWO_WAY ? "假資料，留言只存在這台電腦的瀏覽器。切換身分：" : "假資料。切換身分：",
    ...DEMO_IDS.map(([t, label]) => el("a", {
      href: "#k=" + t + suffix, class: S.token === t ? "is-current" : null,
      "aria-current": S.token === t ? "true" : null, text: label,
    })),
    el("button", {
      type: "button", class: "demo-reset", text: "清除示範留言",
      onclick: () => { store.del(MOCK_KEY); location.reload(); },
    }),
  );
  bar.hidden = false;
}

async function route() {
  const seq = ++S.seq;
  const { k, r, s } = parseHash();
  if (s) return openShared(s, seq);
  if (k) {
    // 網址上的 token 優先；存起來後從網址列移除，避免截圖外洩
    if (k !== S.token) S.me = null;
    S.token = k;
    store.set(TOKEN_KEY, k);
    history.replaceState(null, "", location.pathname + location.search + (r ? "#r=" + encodeURIComponent(r) : ""));
  } else if (!S.token) {
    S.token = store.get(TOKEN_KEY);
  }
  drawDemoBar(r);
  if (!S.token) {
    showNotice(isMock ? "請使用專屬連結開啟。示範模式可用上方連結切換身分。" : "請使用專屬連結開啟本報告。");
    return;
  }
  S.api.setToken(S.token);
  try {
    if (!S.me) S.me = await S.api.whoami();
    if (seq !== S.seq) return;
    drawWho();
    if (r) await openReport(r, seq); else await openHome(seq);
  } catch (e) {
    if (seq === S.seq) handleFatal(e);
  }
}

function drawWho() {
  const w = $("who");
  w.textContent = S.me.name + (S.me.role === "author" ? "（作者）" : "（讀者）");
  w.hidden = false;
}

// ---------- 首頁 ----------

function badge(text, kind) {
  return el("span", { class: "badge badge-" + kind, "data-badge": kind, text });
}

async function openHome(seq) {
  stopPoll();
  closeDrawer();
  S.report = null;
  const list = await S.api.listReports();
  if (seq !== S.seq) return;
  drawHome(list);
  showView("home");
  document.title = "林踐宇工作報告";
  if (TWO_WAY) startPoll();
}

function drawHome(list) {
  const home = $("home");
  const head = el("h1", { class: "home-title", text: "期別清單" });
  if (!list.length) {
    home.replaceChildren(head, el("p", { class: "home-empty", text: "目前沒有可閱讀的期別。" }));
    return;
  }
  const items = list.map((r) => {
    const badges = el("span", { class: "badges" });
    if (S.me.role === "reader") badges.append(r.first_at ? badge("已閱", "read") : badge("未閱", "unseen"));
    if (TWO_WAY && r.unread_replies > 0) badges.append(badge("新回覆 " + r.unread_replies, "reply"));
    if (TWO_WAY && r.unread_count > 0) badges.append(badge("未讀 " + r.unread_count, "unread"));
    const li = el("li", { class: "rep-item", "data-period": r.period },
      el("a", { class: "rep-link", href: "#r=" + encodeURIComponent(r.period) },
        el("span", { class: "rep-title", text: r.title }),
        el("span", { class: "rep-meta", text: "期別 " + r.period + "｜發佈 " + fmtTime(r.published_at) + (r.version > 1 ? "｜第 " + r.version + " 版" : "") }),
      ),
      el("span", { class: "rep-side" }, badges, TWO_WAY ? el("span", { class: "rep-count", text: "留言 " + (r.comment_count || 0) }) : null),
    );
    if (S.me.role === "author" && Array.isArray(r.readers) && r.readers.length) {
      li.append(el("ul", { class: "rep-readers", "aria-label": "讀者已閱狀況" },
        r.readers.map((x) => el("li", { class: x.last_at ? "is-read" : "is-unread" },
          el("span", { class: "rr-name", text: x.name }),
          el("span", { class: "rr-time", text: x.last_at
            ? "已閱 " + fmtTime(x.last_at) + (x.first_at && x.first_at !== x.last_at ? "（首次 " + fmtTime(x.first_at) + "）" : "")
            : "未閱" }),
        ))));
    }
    return li;
  });
  home.replaceChildren(head, el("ul", { class: "rep-list" }, items));
}

// ---------- 報告頁 ----------

async function openReport(period, seq) {
  stopPoll();
  closeDrawer();
  const rep = await S.api.getReport(period);
  if (seq !== S.seq) return;
  S.report = rep;
  S.comments.clear();
  S.statuses.clear();
  S.since = null;
  S.pollN = 0;

  const view = paintReport(rep.content);
  view.prepend(el("nav", { class: "crumb" }, el("a", { href: "#", class: "back-link", text: "← 期別清單" })));
  if (TWO_WAY) decorate(view);
  showView("report");
  document.title = (rep.content && rep.content.period ? rep.content.period + "｜" : "") + "林踐宇工作報告";

  S.api.markRead(rep.report_id).catch((e) => console.error("[ui] markRead", e));
  if (!TWO_WAY) return;
  await poll(true);
  startPoll();
}

function unitLabel(node, kind) {
  const t = kind === "row"
    ? [...node.children].map((td) => td.textContent.trim()).filter(Boolean).join("｜")
    : node.textContent.trim();
  const s = t.replace(/\s+/g, " ");
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}

const AFTER_BLOCK = new Set(["bullets", "stats", "photos"]); // ul／grid 容器內不塞額外子元素

function decorate(view) {
  S.units.clear();
  for (const node of view.querySelectorAll("[data-anchor]")) {
    const kind = node.dataset.kind;
    const btype = node.dataset.btype;
    if (kind === "blk" && btype === "kicker") continue;
    const anchor = node.dataset.anchor;
    const statusable = node.dataset.statusable === "true";
    const label = unitLabel(node, kind);
    const btn = el("button", {
      type: "button", class: "cmt-btn", "data-for": anchor, "aria-label": "留言",
      onclick: () => openDrawer(anchor, btn),
    }, el("span", { class: "cmt-ico", "aria-hidden": "true", text: "💬" }), el("span", { class: "cmt-n" }));
    const slot = el("span", { class: "cmt-slot" }, btn);
    if (kind === "row") node.lastElementChild.append(slot);
    else if (kind === "blk" && AFTER_BLOCK.has(btype)) { slot.classList.add("after-blk"); node.after(slot); }
    else node.append(slot);
    let bar = null;
    if (statusable) {
      bar = el("div", { class: "status-bar", "data-for": anchor });
      slot.after(bar);
    }
    S.units.set(anchor, { node, btn, bar, label, statusable });
  }
}

function liveComments(anchor) {
  return [...S.comments.values()].filter((c) => c.anchor === anchor && !c.deleted);
}

function drawCounts() {
  for (const [anchor, u] of S.units) {
    const n = liveComments(anchor).length;
    u.btn.querySelector(".cmt-n").textContent = n ? String(n) : "";
    u.btn.classList.toggle("has-cmt", n > 0);
    u.btn.setAttribute("aria-label", n ? "留言（" + n + " 則）" : "留言");
  }
}

function statusesOf(anchor) {
  return [...S.statuses.values()].filter((s) => s.anchor === anchor)
    .sort((a, b) => a.reader_name.localeCompare(b.reader_name, "zh-Hant"));
}

function drawStatus(anchor) {
  const u = S.units.get(anchor);
  if (!u || !u.bar) return;
  const list = statusesOf(anchor);
  const mine = list.find((s) => s.reader_id === S.me.reader_id);
  const kids = [];
  if (S.me.role === "reader") {
    for (const st of STATUSES) {
      const on = !!mine && mine.status === st;
      kids.push(el("button", {
        type: "button", class: "status-btn" + (on ? " is-on" : ""), "data-status": st,
        "aria-pressed": on ? "true" : "false",
        "aria-label": on ? "取消「" + st + "」" : "標示為「" + st + "」",
        text: st,
        onclick: (ev) => setStatus(anchor, on ? null : st, ev.currentTarget),
      }));
    }
  }
  for (const s of list) {
    kids.push(el("span", { class: "status-chip st-" + STATUSES.indexOf(s.status), "data-reader": s.reader_id, text: s.reader_name + "：" + s.status }));
  }
  u.bar.replaceChildren(...kids);
  u.bar.hidden = kids.length === 0;
}

async function setStatus(anchor, status, btnEl) {
  if (btnEl) btnEl.disabled = true;
  try {
    const res = await S.api.setStatus(S.report.report_id, anchor, status);
    const key = anchor + "\u0000" + S.me.reader_id;
    if (res) S.statuses.set(key, res); else S.statuses.delete(key);
    drawStatus(anchor);
  } catch (e) {
    if (e.code === "invalid_token") return handleFatal(e);
    alertMsg(errText(e));
    if (btnEl) btnEl.disabled = false;
  }
}

function alertMsg(text) {
  const n = $("notice");
  n.textContent = text;
  n.hidden = false;
  clearTimeout(alertMsg.t);
  alertMsg.t = setTimeout(() => { if (S.view !== "notice") n.hidden = true; }, 5000);
}

function drawOrphans() {
  const article = $("report").querySelector("article.report");
  if (!article) return;
  let box = article.querySelector(".orphans");
  const groups = new Map();
  for (const c of S.comments.values()) {
    if (c.deleted) continue;
    if (!c.orphaned && S.units.has(c.anchor)) continue;
    if (!groups.has(c.anchor)) groups.set(c.anchor, []);
    groups.get(c.anchor).push(c);
  }
  if (!groups.size) { if (box) box.remove(); return; }
  if (!box) {
    box = el("section", { class: "orphans", "aria-label": "未對應留言" });
    article.append(box);
  }
  box.replaceChildren(
    el("h2", { class: "orphans-title", text: "未對應留言" }),
    el("p", { class: "orphans-note", text: "報告改版後找不到原位置的留言，保留在這裡。" }),
    el("ul", { class: "orphans-list" }, [...groups].map(([anchor, cs]) => {
      const first = cs.slice().sort((a, b) => ms(a.created_at) - ms(b.created_at))[0];
      const b = el("button", {
        type: "button", class: "orphan-open", "data-for": anchor,
        text: first.reader_name + "：" + (first.body.length > 40 ? first.body.slice(0, 40) + "…" : first.body) + "（共 " + cs.length + " 則）",
        onclick: () => openDrawer(anchor, b),
      });
      return el("li", {}, b);
    })),
  );
}

function redrawAll() {
  drawCounts();
  for (const anchor of S.units.keys()) drawStatus(anchor);
  drawOrphans();
  if (S.drawer && !S.busy) drawThread();
}

// ---------- 輪詢 ----------

async function poll(full = false) {
  if (S.view === "home") {
    const seq = S.seq;
    try {
      const list = await S.api.listReports();
      if (seq === S.seq && S.view === "home") drawHome(list);
    } catch (e) { if (e.code === "invalid_token") handleFatal(e); else console.error("[ui] poll", e); }
    return;
  }
  if (S.view !== "report" || !S.report) return;
  const rep = S.report;
  const doFull = full || S.since == null || S.pollN % FULL_EVERY === 0;
  S.pollN += 1;
  let res;
  try {
    res = await S.api.listComments(rep.report_id, doFull ? null : S.since);
  } catch (e) {
    if (e.code === "invalid_token") handleFatal(e); else console.error("[ui] poll", e);
    return;
  }
  if (S.report !== rep) return;
  let fresh = false;
  const known = new Set(S.comments.keys());
  if (doFull) { S.comments.clear(); S.statuses.clear(); }
  for (const c of res.comments || []) {
    if (!known.has(c.id) && c.reader_id !== S.me.reader_id) fresh = true;
    S.comments.set(c.id, c);
  }
  for (const s of res.statuses || []) S.statuses.set(s.anchor + "\u0000" + s.reader_id, s);
  S.since = res.server_time || S.since;
  redrawAll();
  // 首次載入或有他人新留言、且頁面在前景 → 視為已看過（首頁未讀歸零）
  if ((full || fresh) && !document.hidden) {
    S.api.markSeen(rep.report_id).catch((e) => console.error("[ui] markSeen", e));
  }
}

function startPoll() {
  stopPoll();
  S.timer = setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);
}

function stopPoll() {
  if (S.timer) clearInterval(S.timer);
  S.timer = null;
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.timer) poll();
});

// ---------- 留言抽屜 ----------

const D = (() => {
  const backdrop = el("div", { class: "drawer-backdrop", hidden: true, onclick: () => closeDrawer() });
  const title = el("h2", { class: "drawer-title", id: "drawer-title", text: "留言" });
  const ctx = el("p", { class: "drawer-ctx" });
  const list = el("div", { class: "drawer-list", "aria-live": "polite" });
  const input = el("textarea", { class: "composer-input", rows: "3", maxlength: "2000", "aria-label": "新增留言", placeholder: "輸入留言…（Ctrl／⌘＋Enter 送出）" });
  const err = el("span", { class: "composer-err", role: "alert" });
  const send = el("button", { type: "submit", class: "btn-primary", text: "送出" });
  const form = el("form", { class: "composer" }, input, el("div", { class: "composer-row" }, err, send));
  const close = el("button", { type: "button", class: "drawer-close", "aria-label": "關閉留言", text: "×", onclick: () => closeDrawer() });
  const panel = el("aside", { class: "drawer", role: "dialog", "aria-labelledby": "drawer-title", hidden: true },
    el("header", { class: "drawer-head" }, title, close), ctx, list, form);
  form.addEventListener("submit", (ev) => { ev.preventDefault(); submitNew(); });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); submitNew(); }
  });
  document.body.append(backdrop, panel);
  return { backdrop, panel, ctx, list, input, err, send };
})();

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && S.drawer) closeDrawer();
});

function openDrawer(anchor, opener) {
  if (S.drawer && S.drawer.anchor !== anchor) unmarkActive();
  S.drawer = { anchor, opener };
  S.busy = false;
  const u = S.units.get(anchor);
  if (u) u.node.classList.add("is-active");
  D.ctx.textContent = u ? u.label : "（原位置已不存在）";
  D.err.textContent = "";
  D.panel.hidden = false;
  D.backdrop.hidden = false;
  document.body.classList.add("drawer-open");
  drawThread();
  D.input.focus();
}

function unmarkActive() {
  const u = S.drawer && S.units.get(S.drawer.anchor);
  if (u) u.node.classList.remove("is-active");
}

function closeDrawer() {
  if (!S.drawer) return;
  unmarkActive();
  const opener = S.drawer.opener;
  S.drawer = null;
  S.busy = false;
  D.panel.hidden = true;
  D.backdrop.hidden = true;
  document.body.classList.remove("drawer-open");
  if (opener && opener.isConnected) opener.focus();
}

function drawThread() {
  if (!S.drawer) return;
  const anchor = S.drawer.anchor;
  const all = [...S.comments.values()].filter((c) => c.anchor === anchor)
    .sort((a, b) => ms(a.created_at) - ms(b.created_at));
  const tops = all.filter((c) => !c.parent_id);
  const replies = (id) => all.filter((c) => c.parent_id === id && !c.deleted);
  const threads = tops
    .filter((t) => !t.deleted || replies(t.id).length)
    .map((t) => el("div", { class: "thread", "data-id": t.id },
      commentNode(t, false),
      el("div", { class: "replies" }, replies(t.id).map((r) => commentNode(r, true))),
    ));
  D.list.replaceChildren(...(threads.length ? threads : [el("p", { class: "drawer-empty", text: "還沒有留言。" })]));
}

function commentNode(c, isReply) {
  const mine = c.reader_id === S.me.reader_id;
  const box = el("article", { class: "cmt" + (isReply ? " is-reply" : "") + (mine ? " is-mine" : ""), "data-id": c.id },
    el("header", { class: "cmt-head" },
      el("span", { class: "cmt-name", text: c.reader_name || "" }),
      c.role === "author" ? el("span", { class: "cmt-role", text: "作者" }) : null,
      el("time", { class: "cmt-time", datetime: c.created_at, text: fmtTime(c.created_at) }),
      c.edited_at && !c.deleted ? el("span", { class: "cmt-edited", text: "（已編輯）" }) : null,
    ),
    el("div", { class: "cmt-body" + (c.deleted ? " is-deleted" : ""), text: c.deleted ? "（此留言已刪除）" : c.body }),
  );
  if (!c.deleted) {
    const acts = el("div", { class: "cmt-actions" });
    if (!isReply) acts.append(el("button", { type: "button", class: "lnk", text: "回覆", onclick: () => openInline(box, c, "reply") }));
    if (mine) {
      acts.append(el("button", { type: "button", class: "lnk", text: "編輯", onclick: () => openInline(box, c, "edit") }));
      acts.append(el("button", { type: "button", class: "lnk lnk-danger", text: "刪除", onclick: () => removeComment(c) }));
    }
    if (acts.childElementCount) box.append(acts);
  }
  return box;
}

function openInline(box, c, mode) {
  for (const f of D.list.querySelectorAll(".inline-form")) f.remove();
  S.busy = true;
  const ta = el("textarea", { class: "composer-input", rows: "2", maxlength: "2000", "aria-label": mode === "reply" ? "回覆內容" : "編輯留言" });
  if (mode === "edit") ta.value = c.body;
  const err = el("span", { class: "composer-err", role: "alert" });
  const cancel = el("button", { type: "button", class: "lnk", text: "取消", onclick: () => { S.busy = false; drawThread(); } });
  const ok = el("button", { type: "submit", class: "btn-primary", text: mode === "reply" ? "送出回覆" : "儲存" });
  const form = el("form", { class: "inline-form" }, ta, el("div", { class: "composer-row" }, err, cancel, ok));
  const go = async () => {
    ok.disabled = true;
    try {
      const res = mode === "reply"
        ? await S.api.addComment(S.report.report_id, c.anchor, ta.value, c.id)
        : await S.api.editComment(c.id, ta.value);
      S.comments.set(res.id, res);
      S.busy = false;
      redrawAll();
    } catch (e) {
      if (e.code === "invalid_token") return handleFatal(e);
      err.textContent = errText(e);
      ok.disabled = false;
    }
  };
  form.addEventListener("submit", (ev) => { ev.preventDefault(); go(); });
  ta.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); go(); }
  });
  box.append(form);
  ta.focus();
}

async function submitNew() {
  if (!S.drawer || !S.report) return;
  D.send.disabled = true;
  D.err.textContent = "";
  try {
    const c = await S.api.addComment(S.report.report_id, S.drawer.anchor, D.input.value, null);
    S.comments.set(c.id, c);
    D.input.value = "";
    redrawAll();
  } catch (e) {
    if (e.code === "invalid_token") return handleFatal(e);
    D.err.textContent = errText(e);
  } finally {
    D.send.disabled = false;
  }
}

async function removeComment(c) {
  if (!window.confirm("確定刪除這則留言？")) return;
  try {
    await S.api.deleteComment(c.id);
    S.comments.set(c.id, { ...c, deleted: true, body: "" });
    redrawAll();
  } catch (e) {
    if (e.code === "invalid_token") return handleFatal(e);
    alertMsg(errText(e));
  }
}

// ---------- 啟動 ----------

document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#sec-"]');
  if (!a) return;
  e.preventDefault();
  const t = document.getElementById(a.getAttribute("href").slice(1));
  if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
});
window.addEventListener("hashchange", route);
route();
