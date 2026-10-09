"""錨點演算法（CONTRACTS §2.2、§3）。與 web/js/anchors.js 必須逐位元一致；本檔只有 strict 模式。"""
import copy
import hashlib

TYPES = ["kicker", "h1", "cap", "stats", "bars", "callout", "table", "day", "bullets", "photos", "footnote"]
GRIDS = {
    "topic": [2600, 4200, 2946],
    "role": [3000, 3400, 3346],
    "day": [1300, 2900, 5546],
    "decision": [2300, 4100, 3346],
    "agenda": [3200, 6546],
    "seq": [620, 1900, 3480, 3746],
}
TEXT_TYPES = ("kicker", "h1", "cap", "callout", "day", "footnote")
_WS = " \u0009\u000a\u000d\u000c\u000b 　"
_WS_TABLE = {ord(c): None for c in _WS}


def normalize_text(s):
    if not isinstance(s, str):
        raise TypeError("normalize_text 需要字串，收到 %s" % type(s).__name__)
    return s.replace("**", "").replace("!!", "").translate(_WS_TABLE)


def sha1hex(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def block_type(block):
    """回傳型別鍵；零個或多個型別鍵回 None。photos 區塊上的 day 是 normalize 插入的附屬鍵。"""
    if not isinstance(block, dict):
        return None
    keys = [t for t in TYPES if t in block]
    if "photos" in keys and "day" in keys:
        keys.remove("day")
    return keys[0] if len(keys) == 1 else None


def _photo_item(it):
    if isinstance(it, dict) and "url" in it:
        return dict(it)
    if isinstance(it, dict):
        f = it.get("file")
        return {"url": f, "cap": it.get("cap") or "", "path": f}
    if isinstance(it, (list, tuple)) and len(it) >= 1:
        return {"url": it[0], "cap": (it[1] if len(it) > 1 else "") or "", "path": it[0]}
    raise ValueError("無法辨識的照片項目：%r" % (it,))


def normalize_content(raw):
    c = copy.deepcopy(raw)
    c.pop("outfile", None)
    blocks = list(c.get("blocks") or [])
    for b in blocks:
        if block_type(b) == "photos":
            b["photos"] = [_photo_item(it) for it in b["photos"]]
    top = c.pop("photos", None) or {}
    for label, items in top.items():
        di = None
        for i, b in enumerate(blocks):
            if block_type(b) == "day" and b["day"] == label:
                di = i
                break
        if di is None:
            raise ValueError("photos day label not found: %s" % label)
        ti = None
        for j in range(di + 1, len(blocks)):
            if block_type(blocks[j]) == "table":
                ti = j
                break
        if ti is None:
            raise ValueError("no table after day: %s" % label)
        blocks.insert(ti + 1, {"photos": [_photo_item(it) for it in items], "cols": 3, "day": label})
    return {"title": c.get("title"), "period": c.get("period"), "to": c.get("to"),
            "from": c.get("from"), "blocks": blocks}


def _s(v, where):
    if not isinstance(v, str):
        raise ValueError("%s 不是字串：%r" % (where, v))
    return normalize_text(v)


def _sources(block, bi):
    """回傳 (blk 來源字串, [row 欄位 or None], [li 文字])。"""
    t = block_type(block)
    if t is None:
        raise ValueError("未知區塊 bi=%d keys=%s" % (bi, sorted(block.keys()) if isinstance(block, dict) else block))
    v = block[t]
    w = "bi=%d %s" % (bi, t)
    if t in TEXT_TYPES:
        return t, [t, _s(v, w)]
    if t == "stats":
        if not isinstance(v, list):
            raise ValueError("%s 不是陣列" % w)
        parts = ["stats"]
        for k, it in enumerate(v):
            if not isinstance(it, dict):
                raise ValueError("%s 第 %d 張不是物件" % (w, k))
            parts.append(_s(it.get("v"), "%s 第 %d 張 v" % (w, k)))
            parts.append(_s(it.get("u", ""), "%s 第 %d 張 u" % (w, k)))
            parts.append(_s(it.get("label", ""), "%s 第 %d 張 label" % (w, k)))
        return t, parts
    if t == "bars":
        if not isinstance(v, list):
            raise ValueError("%s 不是陣列" % w)
        parts = ["bars"]
        for k, r in enumerate(v):
            if not isinstance(r, list) or len(r) < 2:
                raise ValueError("%s 第 %d 列格式錯誤" % (w, k))
            parts += [_s(r[0], "%s 第 %d 列 label" % (w, k)), _s(r[1], "%s 第 %d 列 vtext" % (w, k))]
        return t, parts
    if t == "table":
        if not isinstance(v, dict):
            raise ValueError("%s 不是物件" % w)
        grid, rows = v.get("grid"), v.get("rows")
        if grid not in GRIDS:
            raise ValueError("%s 未知 grid：%r" % (w, grid))
        if not isinstance(rows, list) or not rows:
            raise ValueError("%s rows 必須是非空陣列" % w)
        n = len(GRIDS[grid])
        parts = ["table", grid]
        for ri, r in enumerate(rows):
            if not isinstance(r, list) or len(r) != n:
                raise ValueError("table bi=%d 第 %d 列 %s 欄，grid %s 需要 %d 欄"
                                 % (bi, ri, len(r) if isinstance(r, list) else "?", grid, n))
            parts += [_s(c, "%s 第 %d 列" % (w, ri)) for c in r]
        return t, parts
    if t == "bullets":
        if not isinstance(v, list):
            raise ValueError("%s 不是陣列" % w)
        return t, ["bullets"] + [_s(x, "%s 第 %d 項" % (w, k)) for k, x in enumerate(v)]
    if t == "photos":
        if not isinstance(v, list):
            raise ValueError("%s 不是陣列" % w)
        caps = []
        for k, it in enumerate(v):
            cap = it.get("cap", "") if isinstance(it, dict) else None
            caps.append(_s(cap if cap is not None else "", "%s 第 %d 張 cap" % (w, k)))
        return t, ["photos"] + caps
    raise ValueError("未知區塊 bi=%d" % bi)


def build_anchors(content, strict=True):
    """content 須已 normalize_content。回傳 AnchorEntry list；任何格式錯誤即 raise（strict）。"""
    if not strict:
        raise ValueError("Python 版只支援 strict 模式")
    blocks = content.get("blocks") or []
    types = [block_type(b) for b in blocks]
    out = []
    seen = {}
    n = 0
    day_label = ""

    def emit(sec, kind, btype, bi, ri, li, statusable, src):
        h = sha1hex(src)[:10]
        key = "%s/%s/%s" % (sec, kind, h)
        seen[key] = seen.get(key, 0) + 1
        anchor = key if seen[key] == 1 else "%s-%d" % (key, seen[key])
        out.append({"anchor": anchor, "sec": sec, "kind": kind, "btype": btype, "bi": bi,
                    "ri": ri, "li": li, "statusable": statusable, "text": src.split("|", 1)[1]})

    for bi, b in enumerate(blocks):
        t = types[bi]
        if t == "kicker" and bi + 1 < len(blocks) and types[bi + 1] == "h1":
            n += 1
        elif t == "h1" and not (bi > 0 and types[bi - 1] == "kicker"):
            n += 1
        sec = "s%d" % n
        t, parts = _sources(b, bi)
        emit(sec, "blk", t, bi, None, None, False, "|".join(parts))
        if t == "day":
            day_label = parts[1]
        elif t == "table":
            grid = b["table"]["grid"]
            for ri, r in enumerate(b["table"]["rows"]):
                if ri == 0:
                    continue
                cols = [normalize_text(r[0]), normalize_text(r[1])]
                head = ["row", "day", day_label] if grid == "day" else ["row", grid]
                emit(sec, "row", "table", bi, ri, None, grid == "decision", "|".join(head + cols))
        elif t == "bullets":
            for li, x in enumerate(b["bullets"]):
                emit(sec, "li", "bullets", bi, None, li, True, "li|" + normalize_text(x))
    return out


def status_anchors(entries):
    return [e["anchor"] for e in entries if e["statusable"]]
