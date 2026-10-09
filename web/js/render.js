// content.json → HTML 字串（CONTRACTS §4）；純函式，不碰 document
import { normalizeContent, buildAnchors, validateBlock, secNumbers, GRIDS } from "./anchors.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
}

export function renderInline(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<b class="mk-navy">$1</b>')
    .replace(/!!(.+?)!!/g, '<b class="mk-red">$1</b>')
    .replace(/\r?\n/g, "<br>");
}

const plain = (s) => escapeHtml(String(s == null ? "" : s).split("**").join("").split("!!").join(""));

const ACCENTS = { "0054A7": "navy", "008CD6": "blue", "009C42": "green", "C00000": "red", "6E6A67": "grey" };
const BAR_COLORS = new Set(["blue", "navy", "green", "grey", "red"]);

function accentClass(acc) {
  if (acc == null || acc === "") return "navy";
  const k = String(acc).replace(/^#/, "").toUpperCase();
  if (ACCENTS[k]) return ACCENTS[k];
  console.warn(`[render] 未知 stats accent：${acc}，改用 navy`);
  return "navy";
}

function attrs(btype, anchor, statusable) {
  let s = ` data-btype="${btype}" data-kind="blk" data-anchor="${escapeHtml(anchor)}"`;
  if (statusable) s += ' data-statusable="true"';
  return s;
}

function unitAttrs(kind, a) {
  let s = ` data-kind="${kind}" data-anchor="${escapeHtml(a.anchor)}"`;
  if (a.statusable) s += ' data-statusable="true"';
  return s;
}

function photoSrc(url, base) {
  const u = String(url == null ? "" : url);
  if (!base || /^https?:\/\//i.test(u)) return u;
  return base + u;
}

function renderBlock(type, b, blk, subs, opts) {
  const at = attrs(type, blk.anchor, false);
  switch (type) {
    case "kicker": return `<p class="kicker"${at}>${renderInline(b.kicker)}</p>`;
    case "cap": return `<p class="cap"${at}>${renderInline(b.cap)}</p>`;
    case "callout": return `<div class="callout"${at}>${renderInline(b.callout)}</div>`;
    case "day": return `<h3 class="day"${at}>${renderInline(b.day)}</h3>`;
    case "footnote": return `<p class="footnote"${at}>${renderInline(b.footnote)}</p>`;
    case "h1": {
      const note = typeof b.note === "string" && b.note ? `<span class="h1-note">${renderInline(b.note)}</span>` : "";
      return `<h2 class="h1${b.tight ? " tight" : ""}"${at}><span class="h1-text">${renderInline(b.h1)}</span>${note}</h2>`;
    }
    case "stats": {
      const cards = b.stats.map((it) => {
        const u = it.u ? `<span class="stat-u">${renderInline(it.u)}</span>` : "";
        const note = it.note ? `<div class="stat-note">${renderInline(it.note)}</div>` : "";
        return `<div class="stat accent-${accentClass(it.accent)}"><div class="stat-v">${renderInline(it.v)}${u}</div>` +
          `<div class="stat-label">${renderInline(it.label || "")}</div>${note}</div>`;
      }).join("");
      return `<div class="stats n-${b.stats.length}"${at}>${cards}</div>`;
    }
    case "bars": {
      const rows = b.bars.map((r) => {
        const pct = Math.max(0, Math.min(100, Number(r[2]) || 0));
        const color = BAR_COLORS.has(r[3]) ? r[3] : "blue";
        return `<div class="bar-row"><span class="bar-label">${renderInline(r[0])}</span>` +
          `<span class="bar-track"><span class="bar-fill c-${color}" style="width:${pct}%"></span></span>` +
          `<span class="bar-val">${renderInline(r[1])}</span></div>`;
      }).join("");
      return `<div class="bars"${at}>${rows}</div>`;
    }
    case "table": {
      const { grid, rows } = b.table;
      const n = GRIDS[grid].length;
      const head = `<thead><tr>${rows[0].map((c) => `<th>${renderInline(c)}</th>`).join("")}</tr></thead>`;
      const body = rows.slice(1).map((r, i) =>
        `<tr${unitAttrs("row", subs[i])}>${r.map((c) => `<td>${renderInline(c)}</td>`).join("")}</tr>`).join("");
      return `<div class="tbl grid-${grid} cols-${n}"${at}><table>${head}<tbody>${body}</tbody></table></div>`;
    }
    case "bullets": {
      const items = b.bullets.map((t, i) => `<li${unitAttrs("li", subs[i])}>${renderInline(t)}</li>`).join("");
      return `<ul class="bullets"${at}>${items}</ul>`;
    }
    case "photos": {
      const cols = Number.isInteger(b.cols) && b.cols > 0 ? b.cols : 3;
      const ph = b.photos.map((p) =>
        `<div class="photo"><img src="${escapeHtml(photoSrc(p.url, opts.photoBase))}" loading="lazy" alt="${plain(p.cap)}">` +
        `<figcaption>${renderInline(p.cap || "")}</figcaption></div>`).join("");
      return `<figure class="photos cols-${cols}"${at}>${ph}</figure>`;
    }
  }
  return "";
}

const errorBlock = (label) => `<div class="blk-error" data-btype="error">${escapeHtml(label)}</div>`;

// 頂層 photos 對應失敗時丟棄該鍵重試（§4.1）
function safeNormalize(content, errors) {
  const work = JSON.parse(JSON.stringify(content || {}));
  const tail = [];
  for (;;) {
    try {
      return { content: normalizeContent(work), tail };
    } catch (e) {
      const m = /^(?:photos day label not found|no table after day): ([\s\S]*)$/.exec(e.message);
      if (!m || !work.photos || !(m[1] in work.photos)) throw e;
      delete work.photos[m[1]];
      const msg = "[render] " + e.message;
      console.error(msg);
      errors.push(msg);
      tail.push(errorBlock(`照片對應失敗（${m[1]}）`));
    }
  }
}

export function renderReport(content, opts = {}) {
  const o = { photoBase: "", ...opts };
  const errors = [];
  const { content: c, tail } = safeNormalize(content, errors);
  const { anchors } = buildAnchors(c, { strict: false });
  const byBi = new Map();
  for (const a of anchors) {
    if (!byBi.has(a.bi)) byBi.set(a.bi, { blk: null, subs: [] });
    const e = byBi.get(a.bi);
    if (a.kind === "blk") e.blk = a; else e.subs.push(a);
  }

  const secs = secNumbers(c.blocks);
  const sections = new Map();
  const toc = [];
  c.blocks.forEach((b, bi) => {
    let html;
    try {
      const v = validateBlock(b, bi);
      const e = byBi.get(bi);
      html = renderBlock(v.type, b, e.blk, e.subs, o);
      if (v.type === "h1") toc.push(`<a href="#sec-${secs[bi]}">${plain(b.h1)}</a>`);
    } catch (err) {
      console.error(err.message);
      errors.push(err.message);
      html = errorBlock(`區塊格式錯誤（bi=${bi}）`);
    }
    const n = secs[bi];
    if (!sections.has(n)) sections.set(n, []);
    sections.get(n).push(html);
  });

  let out = `<article class="report" data-period="${escapeHtml(c.period)}">` +
    `<header class="report-head"><h1 class="report-title">${renderInline(c.title)}</h1>` +
    `<p class="report-period">${renderInline(c.period)}</p>` +
    `<p class="report-meta"><span class="meta-k">提報對象：</span>${renderInline(c.to)}` +
    `<span class="meta-sep">｜</span><span class="meta-k">報告人：</span>${renderInline(c.from)}</p></header>`;
  if (toc.length) out += `<nav class="toc" aria-label="章節目錄">${toc.join("")}</nav>`;
  for (const [n, parts] of sections) out += `<section class="sec" id="sec-${n}">${parts.join("")}</section>`;
  out += tail.join("") + "</article>";
  return { html: out, anchors, errors };
}
