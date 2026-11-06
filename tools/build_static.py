"""content.json → 單向靜態報告頁 web/r/<key>.html（給院長快速掃讀）。

用法：python tools/build_static.py "<週資料夾>"
- 讀 <週資料夾>/_src/content.json；同一期沿用 _src/static_key.txt 的亂碼檔名（網址不變）。
- 版面原則：先「30 秒速覽」（數字卡＋重點卡＋決議卡），各節全部展開（2026-10-24 起）。
- 色值只用 web/css/tokens.css 的 CIS 色。
- 2026-11-01 改版：速覽列計「待核定」件數（整節標待核定／待裁示者；2026-11-01 使用者取消獨立的請院長決定卡）、節氣標籤、CIS 四瓣圖示與藍綠漸層線、導覽列短名＋目前位置、手機數字卡改橫列、回頂端鈕。
"""
import html, json, re, secrets, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = (ROOT / "web/css/tokens.css").read_text(encoding="utf-8")
SITE = "https://ken1215.github.io/landseed-work-report/r/"
COLLAPSE = set()                    # 2026-10-24 使用者：全部預設展開，院長不一定會點開；要恢復收合填 {"role", "day"}
BAR_C = {"navy", "blue", "green", "red", "grey"}
PHOTOS = {}                         # ▍日期 → 照片列 HTML（content.json 的 photos，內嵌 base64 保持單檔）


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
    # 2026-11-01：「待院長核定」也算——上週版漏抓，最要緊的一件沒進速覽
    return bool(re.search(r"待裁示|提請裁示|待核示|待(?:院長)?核定", text))


# CIS Logo 四瓣（上綠、左右下藍），當章節編號與標記的小圖示
PETAL = ('<svg class="petal" viewBox="0 0 20 20" aria-hidden="true">'
         '<circle cx="10" cy="4.6" r="4" fill="var(--green)"/><circle cx="4.6" cy="10" r="4" fill="var(--blue)"/>'
         '<circle cx="15.4" cy="10" r="4" fill="var(--blue)"/><circle cx="10" cy="15.4" r="4" fill="var(--blue)"/></svg>')

# 二十四節氣（台灣常用的近似日，年差 ±1 日不影響標籤）
TERMS = [(1, 5, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"), (3, 5, "驚蟄"), (3, 20, "春分"),
         (4, 5, "清明"), (4, 20, "穀雨"), (5, 5, "立夏"), (5, 21, "小滿"), (6, 5, "芒種"), (6, 21, "夏至"),
         (7, 7, "小暑"), (7, 22, "大暑"), (8, 7, "立秋"), (8, 23, "處暑"), (9, 7, "白露"), (9, 23, "秋分"),
         (10, 8, "寒露"), (10, 23, "霜降"), (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 21, "冬至")]
SEASONS = "冬春夏秋"          # 立春 index 2 起算，每 6 個節氣一季


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
        f'<div class="stat-v">{md(it["v"])}<span class="stat-u">{md(it.get("u",""))}</span></div>'
        f'<div class="stat-label">{md(it.get("label",""))}</div>'
        f'<div class="stat-note">{md(it.get("note",""))}</div></div>' for it in items)
    return f'<div class="stats n-{len(items)}">{cards}</div>'


def r_bars(rows):
    out = []
    for r in rows:
        c = r[3] if len(r) > 3 and r[3] in BAR_C else "blue"
        out.append(f'<div class="bar"><span class="bar-l">{md(r[0])}</span>'
                   f'<span class="bar-t"><span class="bar-f c-{c}" style="width:{max(0,min(100,float(r[2]))):.1f}%"></span></span>'
                   f'<span class="bar-v">{md(r[1])}</span></div>')
    return '<div class="bars">' + "".join(out) + "</div>"


def r_seq(rows):
    out = []
    for i, (no, proj, item, res) in enumerate(rows[1:]):
        tone = proj_tone(proj)
        flag = '<span class="flag flag-wait">待裁示</span>' if pending(res) else ""
        out.append(f'<article class="card hl{" top" if i < 3 else ""}">'
                   f'<div class="card-no">{md(no)}</div><div class="card-body">'
                   f'<div class="card-meta"><span class="chip t-{tone}">{md(proj.replace(chr(10), " "))}</span>{flag}</div>'
                   f'<h3 class="card-h">{md(item)}</h3><p class="card-p">{md(res)}</p></div></article>')
    return '<div class="cards">' + "".join(out) + "</div>"


def r_decision(rows):
    out = []
    for name, res, nxt in rows[1:]:
        t, d = split_title(name)
        date = f'<span class="date">{md(d)}</span>' if d else ""
        out.append(f'<article class="dec"><div class="dec-h"><span class="flag flag-ok">已決議</span>'
                   f'<h3 class="card-h">{md(t)}</h3>{date}</div>'
                   f'<p class="card-p">{md(res)}</p>'
                   f'<p class="dec-next"><span class="next-k">後續</span>{md(nxt)}</p></article>')
    return '<div class="decs">' + "".join(out) + "</div>"


def r_agenda(rows, wait):
    out = []
    for k, v in rows[1:]:
        m = re.match(r"(\d+)\s*　?\s*(.*)", k)
        no, title = (m.group(1), m.group(2)) if m else ("", k)
        out.append(f'<li class="ag{" wait" if wait else ""}"><span class="ag-no">{md(no)}</span>'
                   f'<div><div class="ag-t">{md(title)}</div><div class="ag-v">{md(v)}</div></div></li>')
    return '<ol class="agenda">' + "".join(out) + "</ol>"


def r_day(rows):
    out = []
    for t, item, body in rows[1:]:
        routine = "例行業務" in item
        out.append(f'<li class="log{" routine" if routine else ""}"><span class="log-t">{md(t)}</span>'
                   f'<div><div class="log-i">{md(item.replace(chr(10), ""))}</div>'
                   + ("" if routine else f'<div class="log-b">{md(body)}</div>') + "</div></li>")
    return '<ul class="logs">' + "".join(out) + "</ul>"


def r_table(grid, rows):
    head = "".join(f"<th>{md(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{md(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
    return f'<div class="tbl"><table class="g-{grid}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def sections(blocks):
    """依 h1 切節；kicker 歸給下一個 h1。"""
    secs, cur, kick = [], None, ""
    for b in blocks:
        if "kicker" in b:
            kick = b["kicker"]
        elif "h1" in b:
            cur = {"h1": b["h1"], "note": b.get("note", ""), "kicker": kick, "blocks": []}
            secs.append(cur)
            kick = ""
        elif cur is not None:
            cur["blocks"].append(b)
    return secs


def render_sec(i, s):
    wait = pending(s["note"])
    parts = []
    day = None
    for b in s["blocks"]:
        if "day" in b: day = b["day"]
        if "stats" in b: parts.append(r_stats(b["stats"]))
        elif "bars" in b: parts.append(r_bars(b["bars"]))
        elif "cap" in b: parts.append(f'<p class="cap">{md(b["cap"])}</p>')
        elif "callout" in b: parts.append(f'<div class="callout">{md(b["callout"])}</div>')
        elif "day" in b: parts.append(f'<h3 class="day">{md(b["day"])}</h3>')
        elif "bullets" in b: parts.append("<ul class='bul'>" + "".join(f"<li>{md(x)}</li>" for x in b["bullets"]) + "</ul>")
        elif "footnote" in b: parts.append(f'<p class="foot">{md(b["footnote"])}</p>')
        elif "table" in b:
            g, rows = b["table"]["grid"], b["table"]["rows"]
            parts.append({"seq": lambda: r_seq(rows), "decision": lambda: r_decision(rows),
                          "agenda": lambda: r_agenda(rows, wait), "day": lambda: r_day(rows)}
                         .get(g, lambda: r_table(g, rows))())
            if g == "day" and day in PHOTOS: parts.append(PHOTOS[day])
            elif s["h1"] in PHOTOS: parts.append(PHOTOS.pop(s["h1"]))  # 節標題為鍵：放在該節第一張表後
    grids = {b["table"]["grid"] for b in s["blocks"] if "table" in b}
    title = re.sub(r"^[一二三四五六七八九十]+、", "", s["h1"])
    badge = '<span class="flag flag-wait">待裁示</span>' if wait else ""
    note = f'<span class="sec-note">{md(s["note"])}</span>' if s["note"] else ""
    head = (f'<p class="kicker">{md(s["kicker"])}</p>' if s["kicker"] else "") + \
           f'<h2 class="h2"><span class="h2-no">{PETAL}{i:02d}</span>{md(title)}{badge}{note}</h2>'
    body = "".join(parts)
    if grids & COLLAPSE:
        return (f'<section class="sec" id="s{i}"><details><summary>{head}'
                f'<span class="more">展開</span></summary>{body}</details></section>'), title
    return f'<section class="sec" id="s{i}">{head}{body}</section>', title


def build(c):
    secs = sections(c["blocks"])
    n_dec = sum(len(b["table"]["rows"]) - 1 for s in secs for b in s["blocks"]
                if "table" in b and b["table"]["grid"] == "decision")
    rendered = [render_sec(i + 1, s) for i, s in enumerate(secs)]
    asks = ask_items(secs)
    nav = "".join(f'<a href="#s{i+1}" title="{html.escape(t)}"><i>{i+1:02d}</i>{html.escape(short_title(t))}</a>'
                  for i, (_, t) in enumerate(rendered))
    glance = (f'<div class="glance"><span><b>{n_dec}</b> 項已決議</span>'
              + (f'<span class="w"><b>{len(asks)}</b> 項待核定</span>' if asks else "")
              + '<span class="hint">先看 01 重點與 04 決議</span>'
              + "".join(f'<a class="wn" href="#s{n}"><b>{md(t)}</b>{"：" + md(why) if why else ""}</a>'
                        for n, t, why in asks)
              + "</div>")
    term = solar_term(c["period"])
    term_tag = f'<span class="term">{html.escape(term)}</span>' if term else ""
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(c["title"])}｜{html.escape(c["period"])}</title>
<style>{TOKENS}{CSS}</style></head>
<body>
<header class="brand"><img src="../img/logo-cis.png" alt="LANDSEED 聯新國際醫療集團"></header>
<main class="wrap" id="top">
<div class="head"><h1>{html.escape(c["title"])}</h1>
<p class="period">{html.escape(c["period"])}{term_tag}</p>
<p class="meta">提報對象　{html.escape(c["to"])}<span>｜</span>報告人　{html.escape(c["from"])}</p>
{glance}</div>
<nav class="nav" id="nav">{nav}</nav>
{"".join(h for h, _ in rendered)}
<p class="copy">Copyright © Landseed International Medical Group　本頁僅供提報對象閱覽</p>
</main>
<a class="totop" href="#top" aria-label="回到頂端">↑</a>
<script>{JS}</script></body></html>"""


def ask_items(secs):
    """速覽列「待核定」：整節標待核定／待裁示者一節一件，說明取副標「待核定，」後面那段
    （如「下週工務會議與簡院長討論」）；沒有整節的才退回 01 重點卡逐列抓。"""
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


JS = """
(function(){var nav=document.getElementById('nav'),links=[].slice.call(nav.querySelectorAll('a')),
secs=[].slice.call(document.querySelectorAll('.sec')),t=document.querySelector('.totop'),cur=-1,tick=0;
function upd(){tick=0;var k=-1;for(var i=0;i<secs.length;i++){if(secs[i].getBoundingClientRect().top<=140)k=i;}
if(k!==cur){if(cur>=0)links[cur].classList.remove('on');cur=k;if(k>=0){var a=links[k];a.classList.add('on');
nav.scrollLeft=a.offsetLeft-nav.clientWidth/2+a.offsetWidth/2;}}t.classList.toggle('show',scrollY>600);}
addEventListener('scroll',function(){if(!tick){tick=1;requestAnimationFrame(upd);}},{passive:true});upd();})();
"""


CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-sans);font-size:var(--fs-body);line-height:1.65;overflow-wrap:anywhere}
.brand{position:relative;padding:12px 16px;background:var(--bg)}
.brand::after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--navy),var(--blue) 55%,var(--green))}
.brand img{height:var(--logo-h);width:auto;display:block}
.petal{width:.8em;height:.8em;margin-right:6px;vertical-align:-.05em;flex:none}
.term{display:inline-block;margin-left:10px;padding:0 10px;border:1px solid var(--green);border-radius:999px;color:var(--green);font-size:12px;font-weight:700;line-height:1.9;vertical-align:2px;letter-spacing:.08em}
.nav a i{font-style:normal;margin-right:4px;color:var(--blue);font-weight:700}
.nav a.on{background:var(--navy);border-color:var(--navy);color:var(--white)}.nav a.on i{color:var(--white)}
.totop{position:fixed;right:16px;bottom:20px;z-index:6;width:44px;height:44px;border-radius:50%;background:var(--navy);color:var(--white);font-size:20px;line-height:44px;text-align:center;text-decoration:none;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .2s}
.totop.show{opacity:.9;pointer-events:auto}
.wrap{max-width:960px;margin:0 auto;padding:0 16px 48px}
.head{padding:24px 0 12px}
.head h1{margin:0;color:var(--navy);font-size:26px;line-height:1.3}
.period{margin:4px 0 0;color:var(--navy);font-weight:700}
.meta{margin:2px 0 0;color:var(--grey);font-size:var(--fs-small)}.meta span{margin:0 8px}
.glance{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:14px;padding:10px 14px;background:var(--light);border-left:4px solid var(--navy);border-radius:var(--radius)}
.glance b{font-size:20px;color:var(--navy)}.glance .w b{color:var(--red)}
.glance .hint{color:var(--grey);font-size:var(--fs-small);margin-left:auto}
.glance .wn{flex-basis:100%;padding-top:6px;border-top:1px dashed var(--band);color:var(--ink);font-size:14px;text-decoration:none}
.glance .wn b{font-size:14px;color:var(--navy);margin-right:2px}.glance .wn:hover b{text-decoration:underline}
.nav{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;padding:10px 0;background:var(--bg);border-bottom:1px solid var(--band);scrollbar-width:none}
.nav a{flex:none;padding:3px 12px;border:1px solid var(--band);border-radius:999px;color:var(--navy);font-size:var(--fs-small);text-decoration:none;white-space:nowrap}
.nav a:hover,.nav a:focus-visible{background:var(--headfill);border-color:var(--blue)}
.sec{scroll-margin-top:56px;margin-top:28px}
.kicker{margin:0;color:var(--blue);font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase}
.h2{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin:2px 0 14px;padding-bottom:6px;border-bottom:2px solid var(--blue);color:var(--navy);font-size:20px;line-height:1.4}
.h2-no{color:var(--blue);font-size:15px}
.sec-note{color:var(--grey);font-size:var(--fs-small);font-weight:400}
details>summary{list-style:none;cursor:pointer;position:relative}
details>summary::-webkit-details-marker{display:none}
.more{position:absolute;right:0;bottom:12px;padding:1px 10px;border:1px solid var(--blue);border-radius:999px;color:var(--blue);font-size:12px;background:var(--bg)}
details[open] .more{display:none}
.mk-navy{color:var(--navy)}.mk-red{color:var(--red)}
.stats{display:grid;gap:10px;margin:0 0 16px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.stat{background:var(--light);border-top:4px solid var(--navy);border-radius:0 0 var(--radius) var(--radius);padding:10px 12px}
.stat.a-green{border-top-color:var(--green)}
.stat-v{color:var(--navy);font-size:30px;font-weight:700;line-height:1.15}
.stat.a-green .stat-v{color:var(--green)}
.stat-u{margin-left:4px;font-size:var(--fs-small);font-weight:700}
.stat-label{font-weight:700;font-size:14px;margin-top:2px}
.stat-note{color:var(--grey);font-size:12px}
.cards,.decs{display:grid;gap:10px}
.card{display:flex;gap:12px;padding:12px 14px;border:1px solid var(--band);border-radius:var(--radius);background:var(--white)}
.card.top{border-left:4px solid var(--navy)}
.card-no{flex:none;width:30px;color:var(--blue);font-size:20px;font-weight:700;line-height:1.3}
.card-body{min-width:0}
.card-meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
.card-h{margin:0;color:var(--navy);font-size:16px;line-height:1.45}
.card-p{margin:4px 0 0}
.chip{display:inline-block;padding:0 8px;border-radius:999px;font-size:12px;line-height:1.8;font-weight:700;border:1px solid}
.t-navy{color:var(--navy);border-color:var(--navy);background:var(--navy-soft)}
.t-green{color:var(--green);border-color:var(--green);background:var(--white)}
.t-blue{color:var(--blue);border-color:var(--blue);background:var(--blue-soft)}
.t-grey{color:var(--grey);border-color:var(--band)}
.flag{display:inline-block;padding:0 8px;border-radius:3px;font-size:12px;line-height:1.8;font-weight:700;color:var(--white)}
.flag-ok{background:var(--green)}.flag-wait{background:var(--red)}
.h2 .flag{font-size:12px}
.dec{padding:12px 14px;border:1px solid var(--band);border-left:4px solid var(--green);border-radius:var(--radius)}
.dec-h{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.date{color:var(--grey);font-size:var(--fs-small)}
.dec-next{margin:8px 0 0;padding-top:6px;border-top:1px dashed var(--band);color:var(--grey);font-size:14px}
.next-k{display:inline-block;margin-right:8px;color:var(--navy);font-weight:700}
.cap{margin:14px 0 6px;color:var(--grey);font-size:var(--fs-small);font-weight:700}
.bars{margin:0 0 8px}
.bar{display:grid;grid-template-columns:minmax(7em,11em) minmax(0,1fr) auto;gap:10px;align-items:center;padding:4px 0}
.bar-l{font-size:var(--fs-small);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-t{height:12px;background:var(--track);border-radius:2px;overflow:hidden}
.bar-f{display:block;height:100%}
.c-navy{background:var(--navy)}.c-blue{background:var(--blue)}.c-green{background:var(--green)}.c-red{background:var(--red)}.c-grey{background:var(--band)}
.bar-v{color:var(--navy);font-weight:700;font-size:var(--fs-small);white-space:nowrap}
.agenda{list-style:none;margin:0;padding:0;display:grid;gap:0}
.ag{display:flex;gap:12px;padding:10px 4px;border-bottom:1px solid var(--band)}
.ag-no{flex:none;width:30px;color:var(--blue);font-weight:700}
.ag.wait .ag-no{color:var(--red)}
.ag-t{color:var(--navy);font-weight:700}
.ag-v{font-size:14px}
.day{margin:18px 0 6px;font-size:16px;color:var(--ink)}
.day::before{content:"▍";color:var(--green)}
.pics{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:10px 0}
.pics figure{margin:0}.pics img{width:100%;border-radius:var(--radius);display:block}
.pics figcaption{font-size:var(--fs-small);color:var(--grey);margin-top:4px}
.logs{list-style:none;margin:0;padding:0}
.log{display:flex;gap:12px;padding:8px 4px;border-bottom:1px solid var(--band)}
.log-t{flex:none;width:6.5em;color:var(--grey);font-size:var(--fs-small);padding-top:2px}
.log-i{color:var(--navy);font-weight:700}
.log-b{font-size:14px}
.log.routine .log-i{color:var(--grey);font-weight:400}
.tbl{overflow-x:auto;margin:0 0 12px}
.tbl table{width:100%;border-collapse:collapse;min-width:520px}
.tbl th,.tbl td{padding:8px 10px;border-bottom:1px solid var(--band);text-align:left;vertical-align:top;font-size:14px}
.tbl th{background:var(--headfill);color:var(--navy)}
.callout{padding:12px 14px;background:var(--light);border-left:3px solid var(--blue);border-radius:var(--radius)}
.foot{color:var(--grey);font-size:var(--fs-small)}
.copy{margin-top:40px;padding-top:10px;border-top:1px solid var(--band);color:var(--grey);font-size:12px;text-align:center}
.stat-note,.sec-note,.log-t,.date,.dec-next,.meta,.foot{color:var(--note)}
@media (max-width:600px){
body{font-size:16px;line-height:1.7}
.brand img{height:30px}
.head h1{font-size:22px}.glance .hint{margin-left:0}
.term{margin:4px 0 0;display:table}
.period{font-size:15px}
.stats{grid-template-columns:1fr;gap:6px}
.stat{display:grid;grid-template-columns:7.2em minmax(0,1fr);grid-template-rows:auto auto;column-gap:10px;align-items:center;border-top:0;border-left:4px solid var(--navy);border-radius:0 var(--radius) var(--radius) 0;padding:8px 12px}
.stat.a-green{border-left-color:var(--green)}
.stat-v{grid-row:1/3;font-size:26px}.stat-u{display:block;margin:0;font-size:12px}
.stat-label{margin:0;font-size:15px}.stat-note{font-size:13px}
.card-p,.log-b,.ag-v,.tbl th,.tbl td{font-size:15px}
.card-h{font-size:17px}
.bar{grid-template-columns:7em minmax(0,1fr) auto}.log-t{width:4.5em}.tbl table{min-width:0}}
@media print{.nav,.more,.totop{display:none}details>*{display:block}.sec{break-inside:avoid-page}}
"""


def main():
    week = Path(sys.argv[1])
    c = json.loads((week / "_src/content.json").read_text(encoding="utf-8"))
    for d, ps in c.get("photos", {}).items():
        PHOTOS[d] = '<div class="pics">' + "".join(
            f'<figure><img src="{inline_jpg(week / "_src" / p)}" alt="{html.escape(t)}"><figcaption>{md(t)}</figcaption></figure>'
            for p, t in ps) + "</div>"
    kf = week / "_src/static_key.txt"
    key = kf.read_text().strip() if kf.exists() else secrets.token_urlsafe(16)
    kf.write_text(key)
    out = ROOT / "web/r" / f"{key}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(c), encoding="utf-8")
    print(out)
    print(SITE + key + ".html")


if __name__ == "__main__":
    main()
