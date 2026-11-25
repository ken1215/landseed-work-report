"""系統建置專區：把歷次系統說明影片收在同一頁 web/r/<key>.html，各期報告頁的章節列掛連結過來。

用法：python tools/build_systems.py "<專區資料夾>"
- 專區資料夾＝「個人工作日報(2日)\\_系統建置專區」，內含 systems.json、各系統的 mp4 與封面圖、zone_key.txt。
- systems.json：
  {"title": "系統建置專區", "intro": "一句說明",
   "systems": [{"id": "quote", "name": "系統名稱", "unit": "所屬／使用單位", "date": "2026/11/25",
                "status": "已上線", "desc": "一句定位", "points": ["重點一", "重點二"],
                "video": "x.mp4", "poster": "x.jpg", "length": "3 分 21 秒"}]}
  "video" 也可寫 web/r 內已上傳的檔名（"web:<檔名>.mp4"），不重複佔 repo 空間。
- 新增系統：把 mp4 與封面放進專區資料夾、systems.json 加一筆（新的排最前）、重跑本檔、commit＋push。
- 網址固定：key 存專區資料夾 zone_key.txt，並同步寫 tools/systems_key.txt 供 build_static.py 掛連結。
"""
import html, json, secrets, shutil, sys
from pathlib import Path

sys.argv.append("--systems")          # build_static 以 sys.argv 判斷 --no-dexin，這裡不影響
from build_static import CSS, DEXIN_MARK, FLOWER, PETALS, ROOT, SITE, TOKENS, inline_jpg, md

EXTRA = """
.zone{display:flex;flex-direction:column;gap:28px;padding-top:40px}
.sys{background:var(--white);border-radius:16px;padding:28px;display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:28px;align-items:start;scroll-margin-top:16px}
.sys-t{display:flex;flex-direction:column;gap:12px}
.sys-h{font-size:26px;line-height:1.3;font-weight:900;color:var(--ink-strong)}
.sys-d{font-size:17px;color:var(--ink2);text-wrap:pretty}
.sys-meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.sys-date{font-size:13px;color:var(--mute)}
.sys ul{list-style:disc;padding-left:1.3em;color:var(--sub);display:flex;flex-direction:column;gap:4px}
.toc{display:flex;flex-wrap:wrap;gap:8px}
.toc a{min-height:44px;padding:9px 18px;border-radius:999px;background:var(--white);border:1px solid var(--pill-line);color:var(--ink2);text-decoration:none;font-weight:500;font-size:15px}
@media (max-width:820px){.sys{grid-template-columns:1fr;padding:20px;gap:18px}.sys-h{font-size:22px}}
"""


def main():
    zone = Path(sys.argv[1])
    c = json.loads((zone / "systems.json").read_text(encoding="utf-8"))
    kf = zone / "zone_key.txt"
    key = kf.read_text().strip() if kf.exists() else secrets.token_urlsafe(16)
    kf.write_text(key)
    (ROOT / "tools/systems_key.txt").write_text(key)
    rdir = ROOT / "web/r"
    cards, toc = [], []
    for s in c["systems"]:
        v = s["video"]
        if v.startswith("web:"):
            name = v[4:]
            assert (rdir / name).exists(), f"web/r 找不到 {name}"
        else:
            name = f"{key}_{s['id']}.mp4"
            shutil.copyfile(zone / v, rdir / name)
        pts = "".join(f"<li>{md(p)}</li>" for p in s.get("points", []))
        cards.append(
            f'<article class="sys" id="{html.escape(s["id"])}"><div class="sys-t">'
            f'<div class="sys-meta"><span class="chip t-navy">{md(s["unit"])}</span>'
            f'<span class="flag flag-ok">{md(s["status"])}</span><span class="sys-date">{md(s["date"])}</span></div>'
            f'<h2 class="sys-h">{md(s["name"])}</h2><p class="sys-d">{md(s["desc"])}</p>'
            + (f"<ul>{pts}</ul>" if pts else "") + "</div>"
            f'<figure class="vid"><video controls playsinline preload="none" '
            f'poster="{inline_jpg(zone / s["poster"], 1280)}" src="{name}"></video>'
            f'<figcaption>說明影片（{md(s["length"])}，案例資料為虛構）</figcaption></figure></article>')
        toc.append(f'<a href="#{html.escape(s["id"])}">{md(s["name"])}</a>')
    petals = "".join(f'<svg viewBox="0 0 24 24" style="top:{t}px;left:{l}%;width:{z}px;height:{z}px;animation-duration:{d}s">{FLOWER}</svg>'
                     for t, l, z, d in PETALS)
    page = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(c["title"])}｜德新物業</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap">
<style>{TOKENS}{CSS}{EXTRA}</style></head>
<body class="s-wi" id="top">
<header class="brand"><div class="in"><img src="../img/logo-cis.png" alt="LANDSEED 聯新國際醫療集團"><div class="dx" aria-label="報告單位 德新物業">{DEXIN_MARK}<b>德新物業</b></div></div></header>
<section class="hero"><div class="petals" aria-hidden="true">{petals}</div>
<div class="in hero-in"><div class="hero-t">
<div class="tags"><span class="kind">林踐宇個人工作報告</span></div>
<h1>{html.escape(c["title"])}</h1>
<p>{md(c["intro"])}</p></div>
<div class="tiles"><div class="tile"><span class="tile-l">已收錄系統</span><span class="tile-v navy"><b>{len(cards)}</b> <i>套</i></span></div></div></div></section>
<main class="in zone">
<nav class="toc" aria-label="系統清單">{"".join(toc)}</nav>
{"".join(cards)}
</main>
<footer class="copy"><div class="in">報告單位：德新物業 LANDSEED PROPERTY　｜　Copyright © Landseed International Medical Group　本頁僅供提報對象閱覽</div></footer>
</body></html>"""
    out = rdir / f"{key}.html"
    out.write_text(page, encoding="utf-8")
    print(out)
    print(SITE + key + ".html")


if __name__ == "__main__":
    main()
