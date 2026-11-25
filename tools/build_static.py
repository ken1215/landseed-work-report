"""content.json → 單向靜態報告頁 web/r/<key>.html（給院長快速掃讀）。

用法：python tools/build_static.py "<週資料夾>" [--preview] [--no-dexin]
- 讀 <週資料夾>/_src/content.json；同一期沿用 _src/static_key.txt 的亂碼檔名（網址不變）。
- 色值只放 web/css/tokens.css。
- 2026-11-25 改版（使用者於 Design 畫布定案；舊版＝git tag design-v3-20261121，回滾還原本檔與 tokens.css）：
  聯新 LOGO 大、德新略小；頁首依節氣換客家四季主題（春桐花／夏藍衫／秋柿染／冬擂茶）＋飄動花朵；
  「30 秒看完本週」摘要；決議節提前到重點之後；重點同專案併組；行程改一週橫向對照。
- content.json 新增兩個選填鍵（docx 不讀）：
  "summary": [["完成"|"留意"|"進行", "一句話"], …]   → 30 秒摘要；「留意」會計入頁首數字卡
  "hero_stats": [{"label": "板新累計出工", "v": "732", "u": "人日"}, …] → 頁首數字卡（純數字會跑數）
"""
import html, json, re, secrets, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = (ROOT / "web/css/tokens.css").read_text(encoding="utf-8")
SITE = "https://ken1215.github.io/landseed-work-report/r/"
BAR_C = {"navy", "blue", "green", "red", "grey"}
PHOTOS = {}                         # ▍日期／節標題／節標題#序號 → 照片列 HTML（內嵌 base64 保持單檔）
VIDEOS = {}                         # 節標題／節標題#序號 → 影片 HTML（mp4 另存 web/r/<key>_v<n>.mp4）
DEXIN = "--no-dexin" not in sys.argv
DEXIN_MARK = ('<svg class="dx-mark" viewBox="34 32 68 74" aria-hidden="true">'
              '<path d="M52 104 C40 96 34 82 36 68 C38 54 48 44 62 42 C60 56 56 66 50 76 C46 84 46 96 52 104 Z" fill="var(--blue)"/>'
              '<path d="M56 96 C58 74 70 50 98 34 C86 58 78 78 66 92 C63 96 59 98 56 96 Z" fill="var(--sprout)"/></svg>')
SEASON = {"春": ("sp", "春・桐花"), "夏": ("su", "夏・藍衫"), "秋": ("au", "秋・柿染"), "冬": ("wi", "冬・擂茶")}
# 頁首花朵：(top px, left %, 大小 px, 飄動秒數)；大朵慢、小朵快
PETALS = [(6, 2, 14, 6), (30, 9, 30, 8), (4, 18, 20, 5), (40, 25, 10, 4.5), (14, 32, 36, 9), (48, 41, 16, 6.5),
          (2, 47, 12, 5.5), (26, 54, 24, 7), (6, 63, 18, 6), (44, 69, 11, 5), (10, 76, 40, 10), (50, 85, 14, 6.5),
          (4, 89, 22, 7.5), (34, 95, 28, 8.5)]
FLOWER = ('<circle cx="12" cy="6" r="5"/><circle cx="17.7" cy="10.1" r="5"/><circle cx="15.5" cy="16.9" r="5"/>'
          '<circle cx="8.5" cy="16.9" r="5"/><circle cx="6.3" cy="10.1" r="5"/><circle class="core" cx="12" cy="12" r="2.6"/>')


def inline_jpg(p, w=900):
    import base64, io
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    im.thumbnail((w, w))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def md(s):
    """**粗體**→深藍粗體、!!紅字!!→紅色粗體、\\n→換行。"""
    s = html.escape(str(s))
    s = re.sub(r"\*\*(.+?)\*\*", r'<strong class="mk-navy">\1</strong>', s)
    s = re.sub(r"!!(.+?)!!", r'<strong class="mk-red">\1</strong>', s)
    return s.replace("\n", "<br>")


def split_title(s):
    """「板新檢驗科深水槽\\n（10/16）」→（標題, 日期標籤）。"""
    m = re.search(r"\s*[（(]([^（）()]*\d+/\d+[^（）()]*)[）)]\s*$", s)
    return (s[:m.start()].replace("\n", ""), m.group(1)) if m else (s.replace("\n", ""), "")


def proj_tone(name):
    # ponytail: 關鍵字分色，新專案落到 grey；專案多了再改成設定表
    for k, t in (("板", "navy"), ("桃新", "green"), ("體育", "blue"), ("聯新國際醫院", "blue")):
        if k in name:
            return t
    return "grey"


def pending(text):
    return bool(re.search(r"待裁示|提請裁示|待核示|待(?:院長)?核定", text))


# 二十四節氣（台灣常用的近似日，年差 ±1 日不影響標籤）
TERMS = [(1, 5, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"), (3, 5, "驚蟄"), (3, 20, "春分"),
         (4, 5, "清明"), (4, 20, "穀雨"), (5, 5, "立夏"), (5, 21, "小滿"), (6, 5, "芒種"), (6, 21, "夏至"),
         (7, 7, "小暑"), (7, 22, "大暑"), (8, 7, "立秋"), (8, 23, "處暑"), (9, 7, "白露"), (9, 23, "秋分"),
         (10, 8, "寒露"), (10, 23, "霜降"), (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 21, "冬至")]


def solar_term(period):
    """取期間最後一天所在節氣 →「霜降・晚秋」。"""
    ds = re.findall(r"(\d{1,2})月(\d{1,2})日", period)
    if not ds:
        return ""
    m, d = map(int, ds[-1])
    idx = max([i for i, (tm, td, _) in enumerate(TERMS) if (tm, td) <= (m, d)], default=23)
    k = (idx - 2) % 24                  # 0 = 立春
    season = "春夏秋冬"[k // 6]
    stage = ("初", "仲", "晚")[k % 6 // 2]
    return f"{TERMS[idx][2]}・{stage}{season}"


SHORT = {"本期重點事項": "重點", "專案角色與延續事項": "角色", "行程與工作內容": "行程",
         "關鍵決議與成果重點": "決議"}


def short_title(t):
    if t in SHORT:
        return SHORT[t]
    s = re.sub(r"^(板新|本期)\s*", "", t)
    s = re.sub(r"(簡報)?摘要$|事項$", "", s)
    s = s.split("與")[0]
    return s if len(s) <= 9 else s[:8] + "…"


def r_stats(items):
    cards = "".join(
        f'<div class="stat a-{"green" if it.get("accent","").upper()=="009C42" else "navy"}">'
        f'<div class="stat-label">{md(it.get("label",""))}</div>'
        f'<div class="stat-v">{md(it["v"])}<span class="stat-u">{md(it.get("u",""))}</span></div>'
        f'<div class="stat-note">{md(it.get("note",""))}</div></div>' for it in items)
    return f'<div class="stats">{cards}</div>'


def r_bars(rows):
    out = []
    for r in rows:
        c = r[3] if len(r) > 3 and r[3] in BAR_C else "blue"
        out.append(f'<div class="bar"><span class="bar-l">{md(r[0])}</span>'
                   f'<span class="bar-t"><span class="bar-f c-{c}" style="width:{max(0,min(100,float(r[2]))):.1f}%"></span></span>'
                   f'<span class="bar-v">{md(r[1])}</span></div>')
    return '<div class="bars">' + "".join(out) + "</div>"


def r_seq(rows, h1=""):
    """重點卡：連續同專案 2 列以上併成一組大卡，其餘各自一張小卡（順序不變＝重要性）。"""
    groups = []
    for no, proj, item, res in rows[1:]:
        proj = proj.replace("\n", " ")
        media = PHOTOS.pop(f"{h1}#{no}", "") + VIDEOS.pop(f"{h1}#{no}", "")   # 鍵「節標題#序號」
        if media: res = res.replace("（影片見網頁版）", "").replace("，現況照片如下", "")
        flag = '<span class="flag flag-wait">待裁示</span>' if pending(res) else ""
        if groups and groups[-1][0] == proj:
            groups[-1][1].append((item, res, media, flag))
        else:
            groups.append((proj, [(item, res, media, flag)]))
    out, singles = [], []

    def flush():
        if singles:
            out.append('<div class="cards">' + "".join(singles) + "</div>")
            singles.clear()
    for proj, items in groups:
        tone = proj_tone(proj)
        if len(items) == 1:
            item, res, media, flag = items[0]
            singles.append(f'<article class="card"><div class="card-meta"><span class="chip t-{tone}">{md(proj)}</span>{flag}</div>'
                           f'<h3 class="card-h">{md(item)}</h3><p class="card-p">{md(res)}</p>{media}</article>')
            continue
        flush()
        cells, medias = [], []
        for item, res, media, flag in items:
            t, d = split_title(item)
            cells.append(f'<div class="gi"><span class="gi-d">{md(d)}</span><h3 class="gi-h">{md(t)}{flag}</h3>'
                         f'<p class="card-p">{md(res)}</p></div>')
            medias.append(media)
        out.append(f'<article class="grp"><div class="card-meta"><span class="chip solid">{md(proj)}</span>'
                   f'<span class="grp-n">本週 {len(items)} 項</span></div>'
                   f'<div class="gis">{"".join(cells)}</div>{"".join(medias)}</article>')
    flush()
    return "".join(out)


def r_decision(rows):
    out = []
    for name, res, nxt in rows[1:]:
        t, d = split_title(name)
        date = f'<span class="date">{md(d)}</span>' if d else ""
        # 後續列底色：有延宕字眼或 !!紅字!! 才用琥珀，其餘淡藍
        warn = " warn" if re.search(r"!!|暫停|延後|延遲|逾期|落後", nxt) else ""
        out.append(f'<article class="dec"><div class="dec-b"><div class="dec-h"><span class="flag flag-ok">已決議</span>{date}</div>'
                   f'<h3 class="gi-h">{md(t)}</h3><p class="card-p">{md(res)}</p></div>'
                   f'<div class="dec-next{warn}"><span class="next-k">後續</span><p>{md(nxt)}</p></div></article>')
    return '<div class="decs">' + "".join(out) + "</div>"


def r_agenda(rows, wait):
    out = []
    for k, v in rows[1:]:
        m = re.match(r"(\d+)\s*　?\s*(.*)", k)
        no, title = (m.group(1), m.group(2)) if m else ("", k)
        out.append(f'<li class="ag{" wait" if wait else ""}"><span class="ag-no">{md(no)}</span>'
                   f'<div><h3 class="ag-t">{md(title)}</h3><p class="ag-v">{md(v)}</p></div></li>')
    return '<ol class="agenda">' + "".join(out) + "</ol>"


KEY_ITEM = re.compile(r"會|查驗|驗收|討論|選樣|簡報|拜訪|訪視")   # 一週對照裡加粗的列：會議與查驗


def r_daycol(day, rows):
    m = re.search(r"(\d{1,2})月(\d{1,2})日[（(](.)[）)]", day)
    d, w = (f"{m.group(1)}/{m.group(2)}", m.group(3)) if m else (day, "")
    its = []
    for t, item, body in rows[1:]:
        item = item.replace("\n", "")
        routine = "例行業務" in item
        cls = " routine" if routine else (" key" if KEY_ITEM.search(item) else "")
        its.append(f'<li class="wi{cls}"><span class="wi-t">{md(t)}</span><span class="wi-i">{md(item)}</span>'
                   + ("" if routine or not body else f'<span class="wi-b">{md(body)}</span>') + "</li>")
    return (f'<div class="wd{" we" if w in "六日" and w else ""}"><h3 class="wd-h"><b>{md(d)}</b>'
            + (f'<span>（{md(w)}）</span>' if w else "") + f'</h3><ul>{"".join(its)}</ul></div>')


def r_table(grid, rows):
    head = "".join(f"<th>{md(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{md(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
    return f'<div class="tbl"><table class="g-{grid}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def sections(blocks):
    """依 h1 切節（kicker 新版不顯示）。順序：重點 → 決議 → 行程 → 其餘，院長先看結論。"""
    secs, cur = [], None
    for b in blocks:
        if "h1" in b:
            cur = {"h1": b["h1"], "note": b.get("note", ""), "blocks": []}
            secs.append(cur)
        elif cur is not None and "kicker" not in b:
            cur["blocks"].append(b)
    has = lambda s, g: any("table" in b and b["table"]["grid"] == g for b in s["blocks"])
    rank = lambda s: 0 if has(s, "decision") else 1 if has(s, "day") else 2   # 重點 → 決議 → 行程 → 其餘（原順序）
    return secs[:1] + sorted(secs[1:], key=rank)


def render_sec(i, s):
    wait = pending(s["note"])
    parts, week, wpics = [], [], []
    day = None

    def flush():
        if week:
            parts.append('<div class="week">' + "".join(week) + "</div>" + "".join(wpics))
            week.clear(); wpics.clear()
    for b in s["blocks"]:
        if "day" in b:
            day = b["day"]
            continue
        if "table" in b and b["table"]["grid"] == "day":
            week.append(r_daycol(day or "", b["table"]["rows"]))
            if day in PHOTOS: wpics.append(PHOTOS[day])
            continue
        flush()
        if "stats" in b: parts.append(r_stats(b["stats"]))
        elif "bars" in b: parts.append(r_bars(b["bars"]))
        elif "cap" in b: parts.append(f'<p class="cap">{md(b["cap"])}</p>')
        elif "callout" in b: parts.append(f'<p class="callout">{md(b["callout"])}</p>')
        elif "bullets" in b: parts.append("<ul class='bul'>" + "".join(f"<li>{md(x)}</li>" for x in b["bullets"]) + "</ul>")
        elif "footnote" in b: parts.append(f'<p class="foot">{md(b["footnote"])}</p>')
        elif "table" in b:
            g, rows = b["table"]["grid"], b["table"]["rows"]
            parts.append({"seq": lambda: r_seq(rows, s["h1"]), "decision": lambda: r_decision(rows),
                          "agenda": lambda: r_agenda(rows, wait)}.get(g, lambda: r_table(g, rows))())
            if s["h1"] in PHOTOS: parts.append(PHOTOS.pop(s["h1"]))   # 節標題為鍵：放在該節第一張表後
            if s["h1"] in VIDEOS: parts.append(VIDEOS.pop(s["h1"]))   # 影片接在照片之後
    flush()
    title = re.sub(r"^[一二三四五六七八九十]+、", "", s["h1"])
    badge = '<span class="flag flag-wait">待裁示</span>' if wait else ""
    note = f'<span class="sec-note">{md(s["note"])}</span>' if s["note"] else ""
    head = f'<div class="sh"><span class="sh-no">{i:02d}</span><h2>{md(title)}</h2>{badge}{note}</div>'
    return f'<section class="sec" id="s{i}">{head}{"".join(parts)}</section>', title


def ask_items(secs):
    """「待核定」：整節標待核定／待裁示者一節一件；沒有整節的才退回重點卡逐列抓。"""
    out = []
    for n, s in enumerate(secs, 1):
        if pending(s["note"]):
            m = re.search(r"(?:待(?:院長)?(?:核定|裁示|核示)|提請裁示)[，,、\s]*([^）)]*)", s["note"])
            out.append((n, re.sub(r"^[一二三四五六七八九十]+、", "", s["h1"]), m.group(1).strip() if m else ""))
    if out:
        return out
    for n, s in enumerate(secs, 1):
        for b in s["blocks"]:
            if "table" in b and b["table"]["grid"] == "seq":
                out += [(n, r[2], "") for r in b["table"]["rows"][1:] if pending(r[3])]
    return out


def tile(label, v, u, tone):
    count = f' data-count="{v}"' if re.fullmatch(r"\d+", str(v)) and int(v) > 20 else ""
    return (f'<div class="tile"><span class="tile-l">{md(label)}</span>'
            f'<span class="tile-v {tone}"><b{count}>{md(v)}</b> <i>{md(u)}</i></span></div>')


def build(c):
    secs = sections(c["blocks"])
    n_dec = sum(len(b["table"]["rows"]) - 1 for s in secs for b in s["blocks"]
                if "table" in b and b["table"]["grid"] == "decision")
    rendered = [render_sec(i + 1, s) for i, s in enumerate(secs)]
    asks = ask_items(secs)
    summary = c.get("summary", [])
    n_warn = sum(1 for tag, _ in summary if tag == "留意")

    term = solar_term(c["period"])
    skey, sname = SEASON.get(term[-1:] if term else "", ("wi", "冬・擂茶"))
    ds = re.findall(r"(\d{1,2})月(\d{1,2})日", c["period"])
    h1 = (f'{ds[0][0]}/{ds[0][1]} <span>–</span> {ds[-1][0]}/{ds[-1][1]}' if len(ds) >= 2
          else html.escape(c["period"]))
    petals = "".join(f'<svg viewBox="0 0 24 24" style="top:{t}px;left:{l}%;width:{z}px;height:{z}px;animation-duration:{s}s">{FLOWER}</svg>'
                     for t, l, z, s in PETALS)
    tiles = ((tile("已決議", n_dec, "項", "ok") if n_dec else "")
             + (tile("待核定", len(asks), "項", "warn") if asks else "")
             + "".join(tile(x["label"], x["v"], x.get("u", ""), "navy") for x in c.get("hero_stats", []))
             + (tile("需留意", n_warn, "項", "warn") if n_warn else ""))
    tagcls = {"完成": "ok", "留意": "warn"}
    sm = "".join(f'<li><span class="tag {tagcls.get(tag, "info")}">{md(tag)}</span><p>{md(text)}</p></li>'
                 for tag, text in summary)
    sm += "".join(f'<li><span class="tag warn">待核定</span><p><a href="#s{n}">{md(t)}</a>{"：" + md(why) if why else ""}</p></li>'
                  for n, t, why in asks)
    sm_html = (f'<section class="sum" aria-label="三十秒摘要"><h2>30 秒看完本週</h2><ul>{sm}</ul></section>' if sm else "")
    nav = "".join(f'<a href="#s{i+1}" title="{html.escape(t)}">{i+1:02d} {html.escape(short_title(t))}</a>'
                  for i, (_, t) in enumerate(rendered))
    zk = ROOT / "tools/systems_key.txt"   # 系統建置專區（build_systems.py 產生）；有就在章節列尾端掛連結
    if zk.exists():
        nav += f'<a class="zone-link" href="{zk.read_text().strip()}.html">系統建置專區 →</a>'
    dx = (f'<div class="dx" aria-label="報告單位 德新物業">{DEXIN_MARK}<b>德新物業</b></div>' if DEXIN else "")
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(c["title"])}｜{html.escape(c["period"])}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap">
<style>{TOKENS}{CSS}</style></head>
<body class="s-{skey}" id="top">
<header class="brand"><div class="in"><img src="../img/logo-cis.png" alt="LANDSEED 聯新國際醫療集團">{dx}</div></header>
<section class="hero"><div class="petals" aria-hidden="true">{petals}</div>
<div class="in hero-in"><div class="hero-t">
<div class="tags"><span class="kind">{html.escape(c["title"])}</span>{f'<span class="term">{html.escape(term)}｜{sname}</span>' if term else ''}</div>
<h1>{h1}</h1>
<p>{html.escape(c["period"])}</p>
<p>提報對象　{html.escape(c["to"])}　｜　報告人　{html.escape(c["from"])}</p></div>
<div class="tiles">{tiles}</div></div></section>
<main class="in">
{sm_html}
<nav class="nav" id="nav" aria-label="章節">{nav}</nav>
{"".join(h for h, _ in rendered)}
</main>
<footer class="copy"><div class="in">{'報告單位：德新物業 LANDSEED PROPERTY　｜　' if DEXIN else ''}Copyright © Landseed International Medical Group　本頁僅供提報對象閱覽</div></footer>
<a class="totop" href="#top" aria-label="回到頂端">↑</a>
<script>{JS}</script></body></html>"""


JS = """
(function(){var nav=document.getElementById('nav'),links=[].slice.call(nav.querySelectorAll('a:not(.zone-link)')),
secs=[].slice.call(document.querySelectorAll('.sec')),t=document.querySelector('.totop'),cur=-1,tick=0;
function upd(){tick=0;var k=-1;for(var i=0;i<secs.length;i++){if(secs[i].getBoundingClientRect().top<=140)k=i;}
if(k!==cur){if(cur>=0)links[cur].classList.remove('on');cur=k;if(k>=0){var a=links[k];a.classList.add('on');
nav.scrollLeft=a.offsetLeft-nav.clientWidth/2+a.offsetWidth/2;}}t.classList.toggle('show',scrollY>600);}
addEventListener('scroll',function(){if(!tick){tick=1;requestAnimationFrame(upd);}},{passive:true});upd();
if(!matchMedia('(prefers-reduced-motion: reduce)').matches){[].forEach.call(document.querySelectorAll('[data-count]'),function(el){
var n=+el.getAttribute('data-count'),t0=Date.now(),id=setInterval(function(){var k=Math.min(1,(Date.now()-t0)/900);
el.textContent=Math.round(n*(1-Math.pow(1-k,3)));if(k>=1)clearInterval(id);},30);});}})();
"""


CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--ground);color:var(--ink2);font-family:"Noto Sans TC",var(--font-sans);font-size:16px;line-height:1.65;overflow-wrap:anywhere}
h1,h2,h3,p,ul,ol,figure{margin:0}ul,ol{padding:0;list-style:none}
a{color:var(--navy)}
.s-sp{--tint:var(--sp-tint);--accent:var(--sp-accent);--petal:var(--sp-petal);--core:var(--sp-core)}
.s-su{--tint:var(--su-tint);--accent:var(--su-accent);--petal:var(--su-petal);--core:var(--su-core)}
.s-au{--tint:var(--au-tint);--accent:var(--au-accent);--petal:var(--au-petal);--core:var(--au-core)}
.s-wi{--tint:var(--wi-tint);--accent:var(--wi-accent);--petal:var(--wi-petal);--core:var(--wi-core)}
.in{max-width:1160px;margin:0 auto;padding-left:24px;padding-right:24px}
.brand{background:var(--white);border-bottom:1px solid var(--line)}
.brand .in{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;padding-top:16px;padding-bottom:16px}
.brand img{height:48px;width:auto;display:block}
.dx{display:flex;align-items:center;gap:8px}.dx-mark{height:40px;width:auto}
.dx b{font-size:20px;color:var(--sub)}
.hero{position:relative;overflow:hidden;background:var(--tint)}
.petals{position:absolute;top:0;right:0;width:62%;height:84px;pointer-events:none}
.petals svg{position:absolute;opacity:.8;fill:var(--petal);animation:drift 6s ease-in-out infinite}
.petals .core{fill:var(--core)}
@keyframes drift{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(12px) rotate(24deg)}}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hero-in{position:relative;display:flex;flex-wrap:wrap;gap:32px;align-items:flex-end;padding-top:88px;padding-bottom:40px}
.hero-t{flex:999 1 420px;min-width:0;display:flex;flex-direction:column;gap:10px;font-size:15px;color:var(--sub)}
.tags{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.kind{font-size:14px;font-weight:700;letter-spacing:.08em;color:var(--accent)}
.term{font-size:13px;font-weight:500;padding:3px 12px;border-radius:999px;background:var(--white);color:var(--accent)}
.hero h1{font-size:52px;line-height:1.15;font-weight:900;color:var(--ink-strong)}
.hero h1 span{font-weight:400;color:var(--mute)}
.tiles{flex:1 1 420px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(130px,100%),1fr));gap:12px}
.tile{background:var(--white);border-radius:14px;padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.tile-l{font-size:13px;color:var(--mute)}
.tile-v{font-size:40px;line-height:1.1;font-weight:900;font-variant-numeric:tabular-nums}
.tile-v b{font-weight:900}.tile-v i{font-style:normal;font-size:15px;font-weight:500}
.ok{color:var(--green-deep)}.warn{color:var(--amber)}.navy,.info{color:var(--navy)}
main.in{display:flex;flex-direction:column;gap:56px;padding-bottom:64px}
.sum{margin-top:-20px;position:relative;background:var(--white);border-radius:16px;box-shadow:var(--card-shadow);padding:24px 28px;display:flex;flex-direction:column;gap:14px}
.sum h2{font-size:15px;font-weight:700;letter-spacing:.08em;color:var(--mute)}
.sum ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:20px}
.sum li{display:flex;gap:12px;align-items:flex-start;animation:rise .5s ease-out both}
.sum li:nth-child(2){animation-delay:.12s}.sum li:nth-child(3){animation-delay:.24s}.sum li:nth-child(n+4){animation-delay:.36s}
.sum p{font-size:18px;font-weight:500;line-height:1.5;color:var(--ink2)}
.tag{flex:none;margin-top:4px;font-size:13px;font-weight:700;padding:2px 10px;border-radius:999px;display:flex;align-items:center;gap:6px}
.tag.ok{background:var(--green-tint)}.tag.info{background:var(--navy-tint)}.tag.warn{background:var(--amber-tint)}
.tag.warn::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--amber-dot);animation:pulse 1.6s ease-in-out infinite}
.sum:first-child{margin-top:-20px}main.in>.nav:first-child{margin-top:32px}
.nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;overflow-x:auto;padding:8px 0;margin:-8px 0;background:var(--ground);scrollbar-width:none}
.nav a{flex:none;min-height:44px;padding:9px 18px;border-radius:999px;background:var(--white);border:1px solid var(--pill-line);color:var(--ink2);text-decoration:none;font-weight:500;font-size:15px;white-space:nowrap}
.nav a.zone-link{border-color:var(--navy);color:var(--navy);font-weight:700}
.nav a.on{background:var(--navy);border-color:var(--navy);color:var(--white);font-weight:700}
.totop{position:fixed;right:16px;bottom:20px;z-index:6;width:44px;height:44px;border-radius:50%;background:var(--navy);color:var(--white);font-size:20px;line-height:44px;text-align:center;text-decoration:none;opacity:0;pointer-events:none;transition:opacity .2s}
.totop.show{opacity:.9;pointer-events:auto}
.sec{scroll-margin-top:72px;display:flex;flex-direction:column;gap:20px}
.sh{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.sh-no{font-size:44px;line-height:1;font-weight:900;color:var(--accent)}
.sh h2{font-size:28px;font-weight:900;color:var(--ink-strong)}
.sec-note{font-size:14px;color:var(--mute)}
.mk-navy{color:var(--navy)}.mk-red{color:var(--red)}
.grp,.card,.dec,.ag,.tbl,.stat{background:var(--white);border-radius:16px}
.grp{padding:28px;display:flex;flex-direction:column;gap:22px}
.card-meta{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.grp-n{font-size:14px;color:var(--mute)}
.chip{padding:3px 12px;border-radius:999px;font-size:13px;font-weight:500}
.chip.solid{padding:4px 14px;background:var(--navy);color:var(--white);font-size:14px;font-weight:700}
.t-navy,.t-blue{background:var(--navy-tint);color:var(--navy)}
.t-green{background:var(--green-tint);color:var(--green-deep)}
.t-grey{background:var(--grey-tint);color:var(--sub)}
.gis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:24px}
.gi{display:flex;flex-direction:column;gap:6px}
.gi-d{min-height:21px;font-size:13px;font-weight:700;color:var(--navy)}
.gi-h{font-size:21px;font-weight:700;line-height:1.35;color:var(--ink2)}
.card-p{color:var(--sub);text-wrap:pretty}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:16px}
.card{padding:24px;display:flex;flex-direction:column;gap:8px}
.card-h{font-size:19px;font-weight:700}
.flag{display:inline-block;padding:3px 12px;border-radius:999px;font-size:13px;font-weight:700;vertical-align:middle}
.flag-ok{background:var(--green-tint);color:var(--green-deep)}.flag-wait{background:var(--amber-tint);color:var(--amber)}
.gi-h .flag{margin-left:8px}
.decs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:16px}
.dec{overflow:hidden;display:flex;flex-direction:column}
.dec-b{padding:24px 24px 20px;display:flex;flex-direction:column;gap:8px}
.dec-h{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.date{font-size:13px;color:var(--mute)}
.dec-next{margin-top:auto;padding:14px 24px;background:var(--navy-tint);display:flex;gap:12px;align-items:flex-start;font-size:15px;color:var(--navy-ink)}
.next-k{flex:none;font-size:13px;font-weight:700;color:var(--navy);margin-top:2px}
.dec-next.warn{background:var(--amber-tint);color:var(--amber-ink)}.dec-next.warn .next-k{color:var(--amber)}
.week{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(148px,100%),1fr));gap:10px}
.wd{background:var(--white);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:12px}
.wd.we{background:var(--weekend)}
.wd-h{display:flex;align-items:baseline;gap:6px;padding-bottom:8px;border-bottom:2px solid var(--accent);font-weight:400}
.wd-h b{font-size:22px;font-weight:900;color:var(--ink-strong);font-variant-numeric:tabular-nums}.wd-h span{font-size:13px;color:var(--mute)}
.wd ul{display:flex;flex-direction:column;gap:12px}
.wi{display:flex;flex-direction:column;gap:2px}
.wi-t{font-size:12px;font-weight:700;color:var(--mute)}
.wi-i{font-size:15px;line-height:1.4;color:var(--sub)}
.wi.key .wi-i{font-weight:700;color:var(--ink-strong)}.wi.routine .wi-i{color:var(--mute)}
.wi-b{font-size:13px;line-height:1.5;color:var(--mute)}
.tbl{overflow-x:auto}
.tbl table{width:100%;min-width:720px;border-collapse:collapse}
.tbl th,.tbl td{padding:16px 24px;text-align:left;vertical-align:top;font-size:15px;color:var(--sub)}
.tbl th{padding:14px 24px;background:var(--navy-tint);color:var(--navy);font-size:14px}
.tbl td{border-top:1px solid var(--line2)}.tbl td:first-child{font-weight:700;color:var(--ink2)}
.callout{padding:22px 26px;background:var(--tint);border-radius:16px;font-size:18px;line-height:1.6;text-wrap:pretty}
.callout .mk-navy{color:var(--accent)}
.agenda{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:16px}
.ag{padding:22px;display:flex;gap:16px;align-items:flex-start}
.ag-no{flex:none;font-size:32px;line-height:1;font-weight:900;color:var(--accent);font-variant-numeric:tabular-nums}
.ag.wait .ag-no{color:var(--amber)}
.ag-t{font-size:18px;font-weight:700}.ag-v{font-size:15px;color:var(--sub);margin-top:4px;text-wrap:pretty}
.pics{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:14px}
.pics figure{display:flex;flex-direction:column;gap:6px}
.pics img{width:100%;border-radius:10px;display:block;background:var(--white)}
.grp .pics img,.card .pics img{aspect-ratio:4/3;object-fit:cover}
.pics figcaption,.vid figcaption{font-size:13px;color:var(--mute)}
.vid{display:flex;flex-direction:column;gap:6px}
.vid video{width:100%;aspect-ratio:16/9;background:var(--ink-strong);border-radius:12px;display:block}
.stats{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))}
.stat{padding:16px 18px}.stat-label{font-size:13px;color:var(--mute)}
.stat-v{font-size:34px;line-height:1.15;font-weight:900;color:var(--navy)}.stat.a-green .stat-v{color:var(--green-deep)}
.stat-u{margin-left:4px;font-size:14px;font-weight:500}.stat-note{font-size:13px;color:var(--mute)}
.cap{color:var(--mute);font-size:14px;font-weight:700}
.bar{display:grid;grid-template-columns:minmax(7em,11em) minmax(0,1fr) auto;gap:10px;align-items:center;padding:4px 0}
.bar-l{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-t{height:12px;background:var(--line2);border-radius:6px;overflow:hidden}.bar-f{display:block;height:100%}
.c-navy{background:var(--navy)}.c-blue{background:var(--blue)}.c-green{background:var(--green)}.c-red{background:var(--red)}.c-grey{background:var(--pill-line)}
.bar-v{color:var(--navy);font-weight:700;font-size:14px;white-space:nowrap}
.bul{list-style:disc;padding-left:1.4em;color:var(--sub)}
.foot{color:var(--mute);font-size:13px}
.copy{background:var(--white);border-top:1px solid var(--line);font-size:13px;color:var(--mute)}
.copy .in{padding-top:22px;padding-bottom:22px}
@media (max-width:600px){
.in{padding-left:16px;padding-right:16px}
.brand .in{padding-top:12px;padding-bottom:12px;flex-wrap:nowrap}
.brand img{height:38px}.dx{gap:4px}.dx-mark{height:32px}.dx b{font-size:16px}
.petals{width:78%;height:62px}.petals svg:nth-child(n+11){display:none}
.hero-in{padding-top:70px;padding-bottom:36px;gap:20px}
.hero h1{font-size:40px}.hero-t{font-size:14px;gap:8px}
.tiles{grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px}
.tile{padding:12px;border-radius:12px}.tile-l{font-size:12px}.tile-v{font-size:28px}.tile-v i{font-size:12px}
main.in{gap:36px;padding-bottom:40px}
.sum{padding:20px}.sum p{font-size:17px}
.sh-no{font-size:34px}.sh h2{font-size:22px}
.grp{padding:20px}.gi-h{font-size:19px}.card{padding:20px}
.dec-b{padding:20px 20px 16px}.dec-next{padding:12px 20px}
.week{grid-template-columns:1fr}
.tbl table{min-width:560px}.tbl th,.tbl td{padding:12px 16px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}html{scroll-behavior:auto}}
@media print{.nav,.totop,.petals{display:none}.sec{break-inside:avoid-page}}
"""


def main():
    week = Path(sys.argv[1])
    c = json.loads((week / "_src/content.json").read_text(encoding="utf-8"))
    anchor = c.get("web_anchor", {})     # 網頁版照片改掛重點卡：{"節標題": "03"}（docx 不讀此鍵）
    for d, ps in c.get("photos", {}).items():
        if d in anchor: d = f"{d}#{anchor[d]}"
        PHOTOS[d] = '<div class="pics">' + "".join(
            f'<figure><img src="{inline_jpg(week / "_src" / p)}" alt="{html.escape(t)}"><figcaption>{md(t)}</figcaption></figure>'
            for p, t in ps) + "</div>"
    kf = week / "_src/static_key.txt"
    if "--preview" in sys.argv:   # 試看版：另產一把 key 存 _src/preview_key.txt，不動正式網址
        kf = week / "_src/preview_key.txt"
    key = kf.read_text().strip() if kf.exists() else secrets.token_urlsafe(16)
    kf.write_text(key)
    out = ROOT / "web/r" / f"{key}.html"
    out.parent.mkdir(exist_ok=True)
    import shutil
    n = 0
    for sec, vs in c.get("videos", {}).items():
        figs = []
        for mp4, poster, cap in vs:
            n += 1
            name = f"{key}_v{n}.mp4"
            sk = week / "_src/static_key.txt"   # 試看版沿用正式版已上傳的影片，不重複佔 repo 空間
            official = f"{sk.read_text().strip()}_v{n}.mp4" if sk.exists() else ""
            if official and official != name and (out.parent / official).exists(): name = official
            else: shutil.copyfile(week / "_src" / mp4, out.parent / name)
            figs.append(f'<figure class="vid"><video controls playsinline preload="none" '
                        f'poster="{inline_jpg(week / "_src" / poster, 1280)}" src="{name}"></video>'
                        f'<figcaption>{md(cap)}</figcaption></figure>')
        VIDEOS[sec] = "".join(figs)
    out.write_text(build(c), encoding="utf-8")
    print(out)
    print(SITE + key + ".html")


if __name__ == "__main__":
    main()
