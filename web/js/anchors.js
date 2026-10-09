// 錨點演算法（CONTRACTS §2.2、§3）；須與 tools/anchors.py 逐位元一致

export const TYPES = ["kicker", "h1", "cap", "stats", "bars", "callout", "table", "day", "bullets", "photos", "footnote"];
export const GRIDS = {
  topic: [2600, 4200, 2946],
  role: [3000, 3400, 3346],
  day: [1300, 2900, 5546],
  decision: [2300, 4100, 3346],
  agenda: [3200, 6546],
  seq: [620, 1900, 3480, 3746],
};
const STRING_TYPES = new Set(["kicker", "h1", "cap", "callout", "day", "footnote"]);
// 只刪這 8 個字元；刻意不用 \s（JS 與 Python 範圍不同）
const WS_RE = /[ \u0009\u000A\u000D\u000C\u000B 　]/g;

export function normalizeText(s) {
  if (typeof s !== "string") throw new TypeError("normalizeText expects string, got " + typeof s);
  return s.split("**").join("").split("!!").join("").replace(WS_RE, "");
}

function utf8(str) {
  return new TextEncoder().encode(str);
}

export function sha1hex(str) {
  const msg = utf8(str);
  const len = msg.length;
  const total = (((len + 8) >> 6) + 1) << 6;
  const buf = new Uint8Array(total);
  buf.set(msg);
  buf[len] = 0x80;
  const dv = new DataView(buf.buffer);
  const bits = len * 8;
  dv.setUint32(total - 8, Math.floor(bits / 0x100000000));
  dv.setUint32(total - 4, bits >>> 0);
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Uint32Array(80);
  const rotl = (x, n) => (x << n) | (x >>> (32 - n));
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
    for (let i = 16; i < 80; i++) w[i] = rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      let f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const t = (rotl(a, 5) + f + e + k + w[i]) >>> 0;
      e = d; d = c; c = rotl(b, 30) >>> 0; b = a; a = t;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((x) => x.toString(16).padStart(8, "0")).join("");
}

// 依 TYPES 順序找型別鍵；恰好一個才算數，否則回 null
export function blockType(block) {
  if (!block || typeof block !== "object" || Array.isArray(block)) return null;
  const found = TYPES.filter((t) => Object.prototype.hasOwnProperty.call(block, t));
  // normalizeContent 插入的照片 block 帶附屬鍵 day（§2.2 步驟 3），不算第二個型別
  if (found.length === 2 && found[0] === "day" && found[1] === "photos") return "photos";
  return found.length === 1 ? found[0] : null;
}

const clone = (x) => JSON.parse(JSON.stringify(x));

function normPhotoItem(it) {
  if (it && typeof it === "object" && !Array.isArray(it) && "file" in it && !("url" in it)) {
    return { url: it.file, cap: it.cap || "", path: it.file };
  }
  return it;
}

export function normalizeContent(raw) {
  const c = clone(raw);
  delete c.outfile;
  const blocks = Array.isArray(c.blocks) ? c.blocks : [];
  for (const b of blocks) {
    if (blockType(b) === "photos" && Array.isArray(b.photos)) b.photos = b.photos.map(normPhotoItem);
  }
  const top = c.photos;
  if (top && typeof top === "object") {
    for (const label of Object.keys(top)) {
      const di = blocks.findIndex((b) => blockType(b) === "day" && b.day === label);
      if (di < 0) throw new Error("photos day label not found: " + label);
      let ti = -1;
      for (let i = di + 1; i < blocks.length; i++) if (blockType(blocks[i]) === "table") { ti = i; break; }
      if (ti < 0) throw new Error("no table after day: " + label);
      const items = (top[label] || []).map(([path, cap]) => ({ url: path, cap: cap || "", path }));
      blocks.splice(ti + 1, 0, { photos: items, cols: 3, day: label });
    }
  }
  return { title: c.title, period: c.period, to: c.to, from: c.from, blocks };
}

const isStr = (x) => typeof x === "string";

// 驗證 block 並回傳 [blk 欄位, 子單位[]]；格式錯誤丟 Error
function blockUnits(type, b, bi) {
  const v = b[type];
  if (STRING_TYPES.has(type)) {
    if (!isStr(v)) throw new Error(`[anchors] ${type} bi=${bi} 值非字串`);
    return { fields: [v], subs: [] };
  }
  if (type === "stats") {
    if (!Array.isArray(v) || v.length < 2 || v.length > 4) throw new Error(`[anchors] stats bi=${bi} 張數須 2～4`);
    const f = [];
    for (const it of v) {
      if (!it || !isStr(it.v)) throw new Error(`[anchors] stats bi=${bi} v 非字串`);
      for (const k of ["u", "label"]) if (it[k] != null && !isStr(it[k])) throw new Error(`[anchors] stats bi=${bi} ${k} 非字串`);
      f.push(it.v, it.u || "", it.label || "");
    }
    return { fields: f, subs: [] };
  }
  if (type === "bars") {
    if (!Array.isArray(v)) throw new Error(`[anchors] bars bi=${bi} 非陣列`);
    const f = [];
    for (const r of v) {
      if (!Array.isArray(r) || r.length < 3 || !isStr(r[0]) || !isStr(r[1]) || typeof r[2] !== "number") {
        throw new Error(`[anchors] bars bi=${bi} 列格式錯誤`);
      }
      f.push(r[0], r[1]);
    }
    return { fields: f, subs: [] };
  }
  if (type === "table") {
    const grid = v && v.grid;
    if (!Object.prototype.hasOwnProperty.call(GRIDS, grid)) throw new Error(`[anchors] table bi=${bi} 未知 grid ${grid}`);
    const rows = v.rows;
    if (!Array.isArray(rows) || rows.length === 0) throw new Error(`[anchors] table bi=${bi} rows 為空`);
    const need = GRIDS[grid].length;
    rows.forEach((r, ri) => {
      if (!Array.isArray(r) || r.length !== need) {
        throw new Error(`[render] table bi=${bi} 第 ${ri} 列 ${Array.isArray(r) ? r.length : 0} 欄，grid ${grid} 需要 ${need} 欄`);
      }
      if (!r.every(isStr)) throw new Error(`[anchors] table bi=${bi} 第 ${ri} 列含非字串`);
    });
    return { fields: [grid, ...rows.flat()], subs: rows.slice(1).map((r, i) => ({ kind: "row", ri: i + 1, row: r })) };
  }
  if (type === "bullets") {
    if (!Array.isArray(v) || !v.every(isStr)) throw new Error(`[anchors] bullets bi=${bi} 項目非字串`);
    return { fields: v, subs: v.map((t, i) => ({ kind: "li", li: i, item: t })) };
  }
  if (type === "photos") {
    if (!Array.isArray(v)) throw new Error(`[anchors] photos bi=${bi} 非陣列`);
    const f = v.map((it) => (it && isStr(it.cap) ? it.cap : it && it.cap == null ? "" : null));
    if (f.some((x) => x === null)) throw new Error(`[anchors] photos bi=${bi} cap 非字串`);
    return { fields: f, subs: [] };
  }
  throw new Error(`[anchors] 未處理型別 ${type}`);
}

export function validateBlock(b, bi) {
  const type = blockType(b);
  if (!type) {
    const keys = b && typeof b === "object" ? Object.keys(b) : [];
    throw new Error(`[render] 未知區塊 bi=${bi} keys=[${keys.join(",")}]`);
  }
  return { type, ...blockUnits(type, b, bi) };
}

export function secNumbers(blocks) {
  let n = 0;
  return blocks.map((b, i) => {
    const t = blockType(b);
    if (t === "kicker" && blockType(blocks[i + 1]) === "h1") n += 1;
    else if (t === "h1" && blockType(blocks[i - 1]) !== "kicker") n += 1;
    return n;
  });
}

export function buildAnchors(content, { strict = true } = {}) {
  const blocks = content.blocks || [];
  const secs = secNumbers(blocks);
  const anchors = [];
  const errors = [];
  const seen = new Map();
  let dayLabel = "";
  const push = (sec, kind, btype, bi, ri, li, statusable, src) => {
    const h = sha1hex(src).slice(0, 10);
    const key = `${sec}/${kind}/${h}`;
    const k = (seen.get(key) || 0) + 1;
    seen.set(key, k);
    anchors.push({
      anchor: k === 1 ? key : `${key}-${k}`, sec, kind, btype, bi, ri, li, statusable,
      text: src.slice(src.indexOf("|") + 1),
    });
  };
  blocks.forEach((b, bi) => {
    let u;
    try {
      u = validateBlock(b, bi);
    } catch (e) {
      if (strict) throw e;
      errors.push(e.message);
      return;
    }
    const sec = "s" + secs[bi];
    const norm = (xs) => xs.map(normalizeText).join("|");
    if (u.type === "day") dayLabel = normalizeText(b.day);
    push(sec, "blk", u.type, bi, null, null, false, u.type + "|" + norm(u.fields));
    const grid = u.type === "table" ? b.table.grid : null;
    for (const s of u.subs) {
      if (s.kind === "row") {
        const cells = [s.row[0], s.row[1]].map(normalizeText);
        const parts = grid === "day" ? ["row", "day", dayLabel, ...cells] : ["row", grid, ...cells];
        push(sec, "row", "table", bi, s.ri, null, grid === "decision", parts.join("|"));
      } else {
        push(sec, "li", "bullets", bi, null, s.li, true, "li|" + normalizeText(s.item));
      }
    }
  });
  return { anchors, errors };
}
