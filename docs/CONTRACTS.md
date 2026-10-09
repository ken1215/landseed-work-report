# CONTRACTS — 四路平行實作的介面契約（v1，2026-10-09）

> 本檔細化 `docs/PLAN.md`，**不推翻 §1 任何鎖定決策**。四路實作者（db / render / api / publish）只讀本檔即可開工，不需互相溝通；與 PLAN 衝突時以 PLAN §1 為準、其餘以本檔為準。
> 通則：Node v25（`node:test`、ESM、零 npm 相依）；Python 3.9.6（標準庫＋python-docx，禁 `match`、`X | Y` 型別）；Mac 刪檔用 `python3 -c "import os; os.remove(...)"`；伺服器一律 `run_in_background`；SQL 全部標「未實測」；測試失敗照實貼輸出。

---

## 1. 檔案所有權表（一檔一主，別人唯讀）

| 路徑 | 擁有者 | 說明 |
|---|---|---|
| `web/index.html` | render | 單頁外殼：品牌列、首頁容器、報告容器、`<script type="module" src="js/ui.js">` |
| `web/css/tokens.css` | render | **唯一允許出現 hex／rgb()／hsl() 的檔** |
| `web/css/app.css` | render | 版面＋RWD＋print，只能用 `var(--*)` |
| `web/js/render.js` | render | `content → HTML 字串`，純函式 |
| `web/js/anchors.js` | render | `normalizeContent`、`buildAnchors`、`normalizeText`、`sha1hex`（純 JS SHA-1，同步） |
| `web/img/logo-cis.png` | render | 自 `docs/logo-cis.png` 複製 |
| `tests/fixtures/sample.json` | render | **逐字複製本檔 §8.3**，不得改內容 |
| `tests/render.test.js`、`tests/anchors.test.js` | render | |
| `web/js/api.js` | api | `createApi(config)`、`ApiError`、mock 與 supabase 兩實作 |
| `web/js/config.js` | api | `export const CONFIG = { SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }` |
| `tests/api-mock.test.js` | api | |
| `supabase/migrations/0001_schema.sql` | db | 表、索引、RLS deny-all |
| `supabase/migrations/0002_rpc.sql` | db | 全部 `rp_*` RPC |
| `supabase/migrations/0003_notifications.sql` | db | notifications 表與 trigger |
| `supabase/tests/access.sql` | db | PLAN §5 的 ≧8 條存取控制測試（純 SQL，未實測） |
| `tools/readers.py` | db | 建立／撤銷讀者、印個人連結（service_role） |
| `tools/anchors.py`、`tools/__init__.py` | publish | Python 版 `normalize_content`、`build_anchors`（與 anchors.js 等價；只有 strict 模式） |
| `tools/publish.py` | publish | 驗證 → 正規化 → 上傳 → 寫 reports → 錨點遷移；`--mock`、`--dry-run`、`--vectors` |
| `tools/check_leak.sh` | publish | 洩漏探針（探針字串讀 `private/leak_probes.txt`） |
| `tests/test_anchors.py`、`tests/test_publish.py` | publish | python unittest |
| `tests/anchor_vectors.json` | publish | `publish.py --vectors tests/fixtures/sample.json` 產出 |
| `web/js/ui.js` | integrate | 留言抽屜、已閱、狀態鈕、徽章、輪詢、路由 |
| `tests/lint.test.js` | integrate | hex／service_role／探針字串 |
| `tests/e2e/*.mjs`、`package.json`（僅 devDependencies puppeteer） | integrate | |
| `docs/HANDOFF.md`、`README.md` | integrate | |
| `.gitignore` | 已存在，任何人不得改 | `private/ node_modules/ .env* *.local __pycache__/ .DS_Store` |

共用檔的時序規則：publish 的 python 測試讀 `tests/fixtures/sample.json`、render 的 JS 測試讀 `tests/anchor_vectors.json`，**檔案不存在就 `skip`**（印出 skip 原因）；integrate 階段重跑必須 0 skip。本檔 §3.6 的三個手算範例是兩邊共同的硬斷言，不可 skip。

---

## 2. 內容模型

### 2.1 原始 content.json（輸入，與 render.py 相同）
```
title, period, to, from, outfile(忽略),
photos?: { "<day 標籤原文>": [ [path, cap] ×N ] },
blocks: [ block ... ]
```
block 型別判定：依下列順序找**第一個出現在 block 內的型別鍵**（JS 與 Python 皆用此清單順序，不依賴 key 順序）：
`["kicker","h1","cap","stats","bars","callout","table","day","bullets","photos","footnote"]`
一個 block 恰含一個型別鍵；零個或多個 → 未知區塊（render 顯示錯誤區塊＋`console.error`；publish 直接拒收）。
附屬鍵：`h1` 可帶 `note`(str)、`tight`(bool)；`photos` 可帶 `cols`(int)。

型別欄位（字串欄位以外不得進雜湊）：
| 型別 | 形狀 |
|---|---|
| kicker / h1 / cap / callout / day / footnote | 值為字串 |
| stats | `[{v:str, u?:str, label?:str, note?:str, accent?:str}]`，2～4 張；`v` 非字串 → publish 拒收 |
| bars | `[[label:str, vtext:str, pct:number, color?:str]]`；pct 可 int 或 float；color ∈ blue/navy/green/grey/red，缺省 blue |
| table | `{grid: "topic"\|"role"\|"day"\|"decision"\|"agenda"\|"seq", rows: string[][]}`；rows[0] 表頭；每列欄數必須等於 GRIDS 欄數 |
| bullets | `string[]` |
| photos（inline） | 原始 `[{file, cap}]`；正規化後 `[{url, cap, path}]` |

GRIDS（欄寬比例＝render.py 的 dxa；欄數是硬規則）：
`topic [2600,4200,2946]`、`role [3000,3400,3346]`、`day [1300,2900,5546]`、`decision [2300,4100,3346]`、`agenda [3200,6546]`、`seq [620,1900,3480,3746]`。

文字標記：`**x**` 深藍粗體、`!!x!!` 紅色粗體、`\n` 換行；**所有欄位先 HTML escape 再套標記**。

### 2.2 normalizeContent(raw) → content（兩邊等價，publish 寫 DB 前、render 前端皆以此為準）
1. 複製 raw，刪 `outfile`。
2. 每個 inline `photos` block 的項目 `{file, cap}` → `{url: file, cap: cap || "", path: file}`（publish 上傳後再改寫 url/path，見 §6）。
3. 頂層 `photos` map：對每個鍵（day 標籤原文），在 blocks 找 `day` 值**完全相等**的 block，再找其後第一個 `table` block，於該 table **之後**插入
   `{"photos":[{url:path, cap, path} ×N], "cols":3, "day":"<標籤>"}`；找不到 day 或其後沒有 table → 錯誤（publish 拒收；render 顯示錯誤區塊並 `console.error`）。多個鍵依 JSON 內出現順序處理。處理完刪頂層 `photos`。
4. 回傳 `{title, period, to, from, blocks}`。對已正規化的 content 再跑一次 normalizeContent 結果不變（冪等；沒有頂層 photos、inline 項目已是 url 形狀就原樣保留）。

前端拿到的 `reports.content` 已是正規化版；render.js 仍呼叫 `normalizeContent` 一次（冪等）再 `buildAnchors`。

---

## 3. 錨點演算法（JS `anchors.js` 與 Python `tools/anchors.py` 必須逐位元一致）

### 3.1 正規化 normalizeText(s)
1. `s` 必須是字串，否則丟錯（JS `TypeError`、Python `TypeError`）。
2. 刪除所有子字串 `**` 與 `!!`（字面刪除，不管是否成對）。
3. 刪除下列字元：`U+0020 U+0009 U+000A U+000D U+000C U+000B U+00A0 U+3000`（**只有這 8 個**；不得用 `\s`，JS 與 Python 的 `\s` 範圍不同）。
4. 不做 NFC、不轉全形半形、不轉大小寫。

### 3.2 sec 編號
- 計數器 `n = 0`；逐 block 掃描：
  - block 是 `kicker` **且下一個 block 是 `h1`** → `n += 1`，kicker 屬於新節。
  - block 是 `h1` 且**前一個 block 不是 kicker** → `n += 1`。
  - block 是 `h1` 且前一個是 kicker → 不加（已在 kicker 加過）。
  - 其他 block 沿用當前 `n`。
- sec 字串 `"s" + n`；第一個 h1（或其前導 kicker）之前的 block 是 `s0`。
- DOM `<section id="sec-N">` 的邊界與此一致（從 kicker 起）。

### 3.3 可留言單位與雜湊來源字串
每個 block 都有一個 `blk` 錨點（含 kicker/cap/day；要不要給它們留言鈕是 ui.js 的事）。`table` 另對 rows[1..] 各一個 `row`；`bullets` 另對每項一個 `li`。
來源字串＝`<型別>|<欄位1>|<欄位2>…`，每個欄位各自 normalizeText 後以 ASCII `|` 接合；**只有字串欄位進雜湊**，pct、accent、color、note(h1 與 stats 皆排除)、tight、cols、url/path/file 一律排除。

| 單位 | 來源字串 |
|---|---|
| kicker / h1 / cap / callout / day / footnote | `kicker|<值>`、`h1|<h1 值>`（note 不進）、… |
| stats | `stats|v|u|label|v|u|label…`（缺 u/label 以空字串佔位，`|` 仍要） |
| bars | `bars|label|vtext|label|vtext…` |
| table (blk) | `table|<grid>|<r0c0>|<r0c1>|…|<r1c0>|…`（列主序，**含表頭**，全部格子） |
| bullets (blk) | `bullets|<item1>|<item2>…` |
| photos | `photos|<cap1>|<cap2>…` |
| row | `row|<grid>|<c0>|<c1>`；grid 為 `day` 時為 `row|day|<dayLabel>|<c0>|<c1>`，dayLabel＝文件順序上最近一個 `day` block 的值（normalizeText 後），沒有則空字串（`row|day||<c0>|<c1>`） |
| li | `li|<項目文字>` |

### 3.4 雜湊與去重
- `h = sha1(utf8(來源字串)).hex` 取前 10 個小寫 hex。anchors.js 內建純 JS SHA-1（同步；Web Crypto 是 async 不可用），測試以 `node:crypto` 對照。
- 輸出順序＝文件順序：block 的 blk 先、接著它的 rows（ri=1..）或 li（li=0..）。
- 去重鍵＝`<sec>/<kind>/<h>`；同鍵第 2 次出現加 `-2`、第 3 次 `-3`…（計數跨 block、只在同 sec 內）。
- anchor 字串 = `<sec>/<kind>/<h>[-n]`，例 `s3/row/47b7f70649-2`。

### 3.5 可指示狀態（statusable）
`kind == "row"` 且所屬 table `grid == "decision"`，或 `kind == "li"` → `statusable = true`；其餘 false。`status_anchors` ＝ 所有 statusable 的 anchor 字串陣列（文件順序）。

### 3.6 手算範例（以 §8.3 sample.json；兩邊測試的硬斷言）
| # | 單位 | 來源字串（已正規化） | SHA-1 | anchor |
|---|---|---|---|---|
| 1 | h1「一、本期重點事項」（bi=1，kicker 在前所以 s1） | `h1|一、本期重點事項` | `cfe6ac6f4d0eca44c553e4357df3b3c001d8cfa6` | `s1/blk/cfe6ac6f4d` |
| 2 | 10月5日 day 表第 2 資料列（bi=13, ri=2）；原文 c2 含 `!!落後 2 天!!` 但 row 只取 c0、c1 | `row|day|10月5日（一）|14:00|甲案進度會` | `2cb4a95d37271bebcb5049a0b67ddde4831a727a` | `s3/row/2cb4a95d37` |
| 3 | bullets 第 1 項與第 3 項同文（bi=21, li=0 與 li=2），statusable | `li|追蹤：甲案補漆查驗10/8。` | `66accc3c3a25ec56b2c6da49dde2884ea3de71b7` | `s4/li/66accc3c3a` 與 `s4/li/66accc3c3a-2` |
| 補 | 10月6日 day 表 ri=1 與 ri=2 的 c0/c1 相同 | `row|day|10月6日（二）|09:00|工地巡檢` | `47b7f70649ba4b4e130a382fc97969b44b5d8f46` | `s3/row/47b7f70649`、`s3/row/47b7f70649-2` |
| 補 | 由頂層 photos map 插入的 photos block（bi=14） | `photos|3F／候診區：天花板補漆完成|B1／機房：水泵更換中|RF／水塔：漏水點已封` | `56c49e21dd…` | `s3/blk/56c49e21dd` |

### 3.7 sample.json 全部錨點（44 個，publish 的 `--vectors` 輸出必須與此逐列相同）
```
s1/blk/f3bb269fce  blk kicker   bi=0
s1/blk/cfe6ac6f4d  blk h1       bi=1
s1/blk/b8da5c2822  blk callout  bi=2
s1/blk/2ae3d27bf0  blk stats    bi=3    src=stats|12|項|本期事項|87|%|甲案進度|3||待決事項|1|件|新啟動專案
s1/blk/884a3891d1  blk cap      bi=4
s1/blk/50a5caa49b  blk bars     bi=5    src=bars|甲案裝修|87/100曆日|乙案機電|60/60曆日|丙案規劃|5/120曆日|丁案保固|已結案|戊案評估|尚未開始
s1/blk/993b636521  blk table    bi=6
s1/row/22233ed062  row          bi=6 ri=1   src=row|seq|1|甲案
s1/row/5045ff3771  row          bi=6 ri=2
s1/row/5c65f0409f  row          bi=6 ri=3
s2/blk/d29ad4e6bf  blk kicker   bi=7
s2/blk/f47a10a6f5  blk h1       bi=8
s2/blk/221b395626  blk table    bi=9    src=table|role|專案|參與角色|權責範圍／本期重點|甲案|PCM|進度管控品質查驗|乙案|PCM|驗收與缺失追蹤
s2/row/20ba44cd63  row          bi=9 ri=1
s2/row/da3d0c7364  row          bi=9 ri=2
s3/blk/4020e6f5e5  blk kicker   bi=10
s3/blk/efb4e41335  blk h1       bi=11
s3/blk/5e160e2629  blk day      bi=12
s3/blk/402a8c4d38  blk table    bi=13
s3/row/1806afac91  row          bi=13 ri=1
s3/row/2cb4a95d37  row          bi=13 ri=2
s3/blk/56c49e21dd  blk photos   bi=14   （由頂層 photos map 插入）
s3/blk/f31a726914  blk day      bi=15
s3/blk/15f04f71a1  blk table    bi=16
s3/row/47b7f70649  row          bi=16 ri=1
s3/row/47b7f70649-2 row         bi=16 ri=2
s3/row/8ad82fd7a7  row          bi=16 ri=3
s3/blk/063728c4b1  blk photos   bi=17   （inline photos）
s4/blk/b0a942ef66  blk kicker   bi=18
s4/blk/a69bc56cda  blk h1       bi=19
s4/blk/07a07f3112  blk table    bi=20
s4/row/42010f0754  row          bi=20 ri=1  statusable
s4/row/ce82e02d91  row          bi=20 ri=2  statusable
s4/blk/f0367e28fc  blk bullets  bi=21
s4/li/66accc3c3a   li           bi=21 li=0  statusable
s4/li/df3b87b7bd   li           bi=21 li=1  statusable
s4/li/66accc3c3a-2 li           bi=21 li=2  statusable
s5/blk/5cd345aa56  blk kicker   bi=22
s5/blk/7713a09072  blk h1       bi=23
s5/blk/daf704c96e  blk stats    bi=24
s5/blk/eb0d05bfe0  blk table    bi=25
s5/row/4746e777c1  row          bi=25 ri=1
s5/row/baa34e642e  row          bi=25 ri=2
s5/blk/1fb6098dc5  blk footnote bi=26
status_anchors = [s4/row/42010f0754, s4/row/ce82e02d91, s4/li/66accc3c3a, s4/li/df3b87b7bd, s4/li/66accc3c3a-2]
```
（bi 以 normalizeContent **之後**的 blocks 索引計。）

### 3.8 API 形狀
JS（ESM）：
```js
export function normalizeText(s)            // §3.1
export function sha1hex(str)                // 完整 40 hex，UTF-8
export function normalizeContent(raw)       // §2.2，回傳新物件
export function buildAnchors(content, {strict = true} = {})   // content 須已正規化；回傳 {anchors: AnchorEntry[], errors: string[]}；strict 語意見 §4.1
// AnchorEntry = {anchor, sec:"s3", kind:"blk"|"row"|"li", btype, bi, ri:number|null, li:number|null, statusable:boolean, text}
// text = 來源字串去掉「<型別>|」前綴（遷移相似度用）
```
Python `tools/anchors.py`：`normalize_text`, `sha1hex`, `normalize_content`, `build_anchors` 同名同形（dict 鍵同上），`TYPES`、`GRIDS` 常數同名。

### 3.9 錨點遷移（publish 專用）
舊版 `reports.anchor_index`（AnchorEntry[]）與新版比對：舊 anchor 若在新版存在 → 不動；否則候選 = 新版中**同 sec 同 kind 且不在舊版**的 entry，以 `difflib.SequenceMatcher(None, old.text, new.text).ratio()` 取最高且 ≧ 0.6，同分取文件順序最前、且一個新錨點只能被對應一次；命中 → `update comments set anchor=new where report_id and anchor=old`，statuses 同（statuses 若撞 pk 則保留 updated_at 較新者）；未命中 → `comments.orphaned=true`、statuses 直接刪除。遷移以 service_role 直連，不走 RPC。

---

## 4. render.js DOM 契約

### 4.1 API
```js
export function renderReport(content, opts = {}) → { html: string, anchors: AnchorEntry[], errors: string[] }
export function renderInline(text) → string      // escape + **/!!/\n 標記
```
- 純字串輸出、不碰 `document`；node 可測。`opts.photoBase`（預設 ""）會前綴到相對 url（絕對 `http(s)://` 不動）。
- 未知 block 不中斷：輸出錯誤區塊並 `console.error("[render] 未知區塊 bi=N keys=[...]")`，`errors` 收錄同一訊息；表格欄數不符亦同（`"[render] table bi=N 第 M 列 K 欄，grid X 需要 J 欄"`）；錯誤 block 以 `data-btype="error"` 輸出且不帶 data-anchor。
- 錯誤 block 與錨點：`buildAnchors(content, {strict})`——`strict=true`（publish／Python 唯一模式）遇未知型別、欄數不符、欄位非字串即 raise；`strict=false`（render.js 用）該 block **不產錨點但仍佔 bi、kicker/h1 仍參與 sec 計數**，錯誤訊息收進回傳的 `errors`。JS 回傳形狀因此為 `{anchors, errors}`（Python `build_anchors` 直接回 list）。render.js 不得自行過濾 blocks，§3.7 的 bi 一律指 normalizeContent 後的原索引。
- JS 版 `normalizeContent` 遇頂層 photos 找不到 day／其後無 table 時 **throw**（訊息 `"photos day label not found: <label>"`／`"no table after day: <label>"`）；render.js 捕捉後丟棄該頂層 photos 鍵重試，並在 `<article>` 文末補一個 `.blk-error` 區塊、`console.error`。

### 4.2 結構
```html
<article class="report" data-period="{period}">
  <header class="report-head">
    <h1 class="report-title">{title}</h1>
    <p class="report-period">{period}</p>
    <p class="report-meta"><span class="meta-k">提報對象：</span>{to}<span class="meta-sep">｜</span><span class="meta-k">報告人：</span>{from}</p>
  </header>
  <nav class="toc" aria-label="章節目錄"><a href="#sec-1">一、本期重點事項</a>…</nav>   <!-- 只列有 h1 的 sec -->
  <section class="sec" id="sec-0">…</section>   <!-- s0 無內容時不輸出 -->
  <section class="sec" id="sec-1">…blocks…</section>
</article>
```
品牌列（logo＋「林踐宇個人工作報告」）由 index.html 靜態提供，不在 render 輸出內。

### 4.3 每種 block 的元素（`data-anchor`、`data-kind`、`data-btype` 必有；`data-statusable="true"` 只在 statusable 單位上出現，否則不輸出該屬性）
| 型別 | 元素與 class |
|---|---|
| kicker | `<p class="kicker" data-btype="kicker" data-kind="blk" data-anchor>` |
| h1 | `<h2 class="h1 [tight]" data-btype="h1" …><span class="h1-text"/>[<span class="h1-note"/>]</h2>` |
| cap | `<p class="cap" …>` |
| stats | `<div class="stats n-{N}" …><div class="stat accent-{navy\|blue\|green\|red\|grey}"><div class="stat-v">{v}[<span class="stat-u"/>]</div><div class="stat-label"/>[<div class="stat-note"/>]</div>…</div>`；accent 對照 `0054A7→navy, 008CD6→blue, 009C42→green, C00000→red, 6E6A67→grey`（比對不分大小寫、可含 `#`），缺省或未知 → navy 並 `console.warn`；**禁止 inline style** |
| bars | `<div class="bars" …><div class="bar-row"><span class="bar-label"/><span class="bar-track"><span class="bar-fill c-{color}" style="width:{pct}%"></span></span><span class="bar-val"/></div>…</div>`；pct 夾在 0～100；**唯一允許的 inline style 是 width 百分比** |
| callout | `<div class="callout" …>` |
| table | `<div class="tbl grid-{grid} cols-{N}" data-btype="table" data-kind="blk" data-anchor><table><thead><tr><th>…</tr></thead><tbody><tr data-kind="row" data-anchor [data-statusable]><td>…</td></tr>…</tbody></table></div>`；`<th>`/`<td>` 內 `\n` → `<br>` |
| day | `<h3 class="day" …>` |
| bullets | `<ul class="bullets" data-btype="bullets" data-kind="blk" data-anchor><li data-kind="li" data-anchor data-statusable="true">…</li></ul>` |
| photos | `<figure class="photos cols-{cols}" …><div class="photo"><img src loading="lazy" alt="{cap 純文字}"><figcaption>…</figcaption></div>…</figure>` |
| footnote | `<p class="footnote" …>` |
| 錯誤 | `<div class="blk-error" data-btype="error">區塊格式錯誤（bi=N）</div>` |

ui.js 掛留言鈕的位置（render 不輸出按鈕）：`row` → 最後一個 `<td>` 末尾插 `<span class="cmt-slot">`；`li` → `<li>` 末尾；`blk` → 元素末尾（table 為 `.tbl` 內、`<table>` 之後）。狀態鈕區 `<div class="status-bar">` 由 ui.js 插在 `cmt-slot` 旁，內含 `<button class="status-btn" data-status="同意|再議|請補資料" aria-label="…">` 與 `<span class="status-chip">讀者名：狀態</span>`。

### 4.4 其他
- 行內標記輸出：`**x**` → `<b class="mk-navy">x</b>`；`!!x!!` → `<b class="mk-red">x</b>`；`\n` → `<br>`；escape `& < > " '`。
- class 名與 id 必須避開純 hex 字母組合（`add`、`bed`、`face`、`cafe`…），否則 lint 的 hex 探測會誤判。
- 表格 min-width（app.css）：2 欄不捲、3 欄 ≧ 560px、4 欄 ≧ 640px，外層 `.tbl { overflow-x:auto }`。stats ≦600px 變 2 欄。

---

## 5. api.js 介面

### 5.1 建立
```js
import { CONFIG } from "./config.js";
export class ApiError extends Error { code; status; }   // code 見 5.4
export function createApi(config = CONFIG, opts = {}) → Api
```
- `config.SUPABASE_URL` 或 `SUPABASE_ANON_KEY` 為空字串／undefined → **MockApi**，且完全不 `import()` CDN；否則 **SupabaseApi**，以 `await import("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm")` 延遲載入。
- `api.mode` ∈ `"mock" | "supabase"`。
- `api.setToken(token)`：之後所有呼叫帶此 token；未設 token 呼叫 → `ApiError("invalid_token")`。
- `opts`（mock 用，node 測試注入）：`storage`（具 `getItem/setItem/removeItem`，預設 `localStorage`，取用失敗時退回記憶體物件）、`loadIndex: async()=>IndexJson`、`loadReport: async(period)=>ReportJson`（預設 `fetch("../private/mock/index.json")` 與 `fetch("../private/mock/<period>.json")`）、`now: ()=>Date`。

### 5.2 方法、RPC 與回傳 JSON（RPC 皆 `returns jsonb`，api.js 原樣透傳，不改鍵名）
時間一律 ISO 8601 字串（PG 會吐 `+00:00`，前端用 `new Date()` 解析，不比對字串）。

| 方法 | RPC（參數名與 SQL 一致） | 回傳 |
|---|---|---|
| `whoami()` | `rp_whoami(p_token)` | `{reader_id, name, role}` |
| `listReports()` | `rp_list_reports(p_token)` | `[{report_id, period, title, published_at, version, first_at, last_at, comment_count, unread_count, unread_replies, readers}]`，最新 period 在前；`first_at/last_at` 本人已閱時間或 null；`unread_count`＝非本人、未刪、`created_at > seen.last_seen_comment_at`（無 seen 列則全部）的留言數；`unread_replies`＝其中 `parent_id` 指向本人留言者；`readers` 僅 author 回傳 `[{reader_id, name, first_at, last_at}]`（有 report_access 的 reader，未閱 null），reader 回傳 `[]` |
| `getReport(period)` | `rp_get_report(p_token, p_period)` | `{report_id, period, title, content, version, published_at, status_anchors}`（content 形狀見 §6） |
| `markRead(report_id)` | `rp_mark_read(p_token, p_report_id)` | `{first_at, last_at}`（upsert：首次填 first_at，之後只更新 last_at） |
| `listComments(report_id, since=null)` | `rp_list_comments(p_token, p_report_id, p_since)` | `{server_time, comments:[{id, anchor, reader_id, reader_name, role, parent_id, body, created_at, edited_at, deleted, orphaned}], statuses:[{anchor, reader_id, reader_name, status, updated_at}]}`；`p_since` null → 全部；否則回傳 `greatest(created_at, coalesce(edited_at,created_at)) > p_since` 的留言與 `updated_at > p_since` 的狀態（含 deleted=true 者，前端據此隱藏；deleted 的 body 回空字串）；排序 created_at asc |
| `addComment(report_id, anchor, body, parent_id=null)` | `rp_add_comment(p_token, p_report_id, p_anchor, p_body, p_parent_id)` | 新留言物件（同 comments 元素形狀） |
| `editComment(comment_id, body)` | `rp_edit_comment(p_token, p_comment_id, p_body)` | 更新後留言物件 |
| `deleteComment(comment_id)` | `rp_delete_comment(p_token, p_comment_id)` | `{id, deleted:true}`（軟刪：deleted=true、body 清空；回覆保留） |
| `setStatus(report_id, anchor, status)` | `rp_set_status(p_token, p_report_id, p_anchor, p_status)` | status 非 null → `{anchor, reader_id, reader_name, status, updated_at}`；null → 刪列並回 `null` |
| `markSeen(report_id)` | `rp_mark_seen(p_token, p_report_id)` | `{last_seen_comment_at}`（設為該報告目前最大 comment created_at，或 now()） |

規則（db 與 mock 都要實作）：body `trim` 後長度 1～2000；`parent_id` 所指留言須同 report 且 `parent_id is null`（只允許一層）；edit/delete 僅本人且未刪；setStatus 僅 `role='reader'` 且 anchor ∈ `reports.status_anchors`，status ∈ `同意|再議|請補資料`；reader 只能存取 `report_access` 有列的報告，author 全部可看；任何 token 失敗（找不到／`active=false`）一律 `invalid token`。

### 5.3 SQL 錯誤字串 → ApiError.code 對照（db 以 `raise exception '<字串>'` 逐字使用；api.js 以 `message` 開頭比對）
| raise 字串 | code | 觸發 |
|---|---|---|
| `invalid token` | `invalid_token` | token 空／不存在／撤銷 |
| `forbidden` | `forbidden` | 無權報告、改他人留言、author 設狀態 |
| `not found` | `not_found` | period／comment／parent 不存在 |
| `anchor not statusable` | `anchor_not_statusable` | anchor ∉ status_anchors |
| `invalid status` | `invalid_status` | status 值不在三選一 |
| `body too long` | `body_too_long` | > 2000 |
| `body empty` | `body_empty` | trim 後為空 |
| `reply depth` | `reply_depth` | parent 本身是回覆 |
| （其他／網路） | `network`（fetch 失敗）、`unknown` | |
`ApiError.message` 保留原字串；mock 丟相同 code 與 message。

### 5.4 Mock 行為
- 讀者表（固定）：`demo-author` → `{reader_id:"r-author", name:"林踐宇", role:"author"}`；`demo-reader-1` → `{reader_id:"r-1", name:"張院長", role:"reader"}`；`demo-reader-2` → `{reader_id:"r-2", name:"讀者乙", role:"reader"}`；其餘 token → `invalid token`。兩位 reader 對 index.json 所有報告都有 access。
- 報告來源：`loadIndex()` 讀 `private/mock/index.json`（§6.3），`loadReport(period)` 讀 `private/mock/<period>.json`（§6.2）。
- 狀態持久化：`storage` 一把鍵 `lwr.mock.v1`，值為 JSON `{comments:[], statuses:[], reads:[], seen:[]}`；留言 id 為 `"c" + 遞增整數`。
- 所有方法 `async`，與 supabase 版同簽名；節流不做。

### 5.5 token 與路由（ui.js／integrate 參考，api 不處理）
`#k=<token>[&r=<period>]`；token 存 `localStorage["lwr.token"]`（try/catch）後 `history.replaceState` 改為 `#r=<period>` 或空；無 token 且 storage 無 → 顯示「連結無效」。

---

## 6. reports.content 與 mock 檔格式

### 6.1 `reports.content`（jsonb）＝ §2.2 normalizeContent 後的物件，其中照片項：
```json
{"url": "https://<proj>.supabase.co/storage/v1/object/sign/report-photos/<period>/<basename>?token=…", "cap": "圖說", "path": "<period>/<basename>"}
```
- bucket `report-photos`（private）；publish 用 service_role 上傳到 `<period>/<basename>`（重名加 `-2`），簽章 URL `expiresIn = 315360000`（10 年）；重發佈時重新簽。
- `reports` 表另有欄位：`status_anchors text[] not null default '{}'`、`anchor_index jsonb not null default '[]'`（AnchorEntry[]）、`version int not null default 1`（重發佈 +1）。
- 前端只讀 `content`、`status_anchors`；`anchor_index` 只給 publish 遷移。
- 內容驗證（publish 拒收條件）：缺 title/period/from；未知 block；table 欄數不符；stats 張數 ∉ 2～4 或 v 非字串；bars 列長 < 3 或 pct 非數字；頂層 photos 找不到 day；照片檔不存在（`--mock`/正式皆檢查，`--dry-run` 亦檢查但不上傳）。

### 6.2 `private/mock/<period>.json` ＝ `rp_get_report` 回傳形狀
```json
{"report_id":"m-<period>", "period":"<period>", "title":"…", "content":{…}, "version":1, "published_at":"<ISO>", "status_anchors":[…]}
```
照片 `url` 改寫為 `../private/mock/photos/<period>/<basename>`（相對 `web/index.html`，publish 負責複製檔案到該處；`path` 同值）。

### 6.3 `private/mock/index.json`
```json
{"reports":[{"report_id":"m-<period>", "period":"…", "title":"…", "published_at":"…", "version":1, "comment_count":0}]}
```
publish `--mock` 每次合併（同 period 覆蓋）、依 period 字串降冪。mock 的 `listReports` 只取 index.json 的 report_id/period/title/published_at/version，`comment_count`、`unread_count`、`unread_replies`、`first_at/last_at`、`readers` 一律自 storage 現算（index.json 的 `comment_count` 忽略）。

### 6.4 publish.py 指令
```
python3 tools/publish.py <content.json 或期間資料夾(含 _src/content.json)> [--mock] [--dry-run] [--vectors]
```
- `--mock`：不碰網路，寫 §6.2／§6.3。
- `--dry-run`：驗證＋正規化＋錨點＋（若環境有舊版 json 路徑 `--prev <file>`）遷移報告，印 JSON 摘要，不寫任何檔、不碰網路。
- `--vectors`：stdout 印 AnchorEntry[] JSON（整合時 `> tests/anchor_vectors.json`）。
- `--skip-photos`：跳過照片檔存在檢查；`--mock` 時不複製照片檔、url 仍照 §6.2 改寫。僅供測試與 sample.json（其照片檔不存在）。
- `--prev <file>`：`--dry-run` 時以該 json（舊版 `anchor_index` 陣列或整份 §6.2 報告物件）做遷移試算並印對應表。
- 正式模式讀 `private/.env.local`（`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`），用 `urllib` 打 PostgREST／Storage REST，無第三方套件；帳號未開，**正式路徑只寫不跑**，測試用 `--dry-run`/`--mock`。
- `period` 取自 content.json 檔名所在資料夾名（如 `260928-1002`）或 `--period`。

### 6.5 tools/readers.py（db）
`python3 tools/readers.py add --name 張院長 --role reader [--periods 260928-1002,…]` → 產生 32 bytes 隨機 token（base64url 無填充），印 `https://<pages-host>/index.html#k=<token>`，DB 只存 `lower(hex(sha256(token)))`；`revoke --name`／`list`；`grant --name --period`。service_role 直連、讀 `private/.env.local`。

---

## 7. 測試指令總表

| 指令 | 覆蓋 |
|---|---|
| `node --test tests/` | render：sample 每種 block 都產出對應 class；table 欄數錯 → `.blk-error`＋errors；`<script>` 被 escape；未知 block 錯誤區塊＋console.error；`data-statusable` 只在 decision row／li。anchors：§3.6 三例硬斷言；44 個錨點與 `anchor_vectors.json`（存在才比）；`-2` 後綴；normalizeText 八種空白；sha1hex 對 `node:crypto`。api-mock：whoami 三身分、listReports 未讀數、addComment→reply→editComment→deleteComment、setStatus 合法／不可指示／author 被拒、markRead first/last、markSeen 後 unread=0、invalid token。lint：`web/**` 除 tokens.css 無 `#[0-9a-fA-F]{3}(…)`／`rgb(`／`hsl(`；`web/**` 無 `service_role`；`private/leak_probes.txt` 存在時逐字 grep `web/`、`tests/`、`docs/`、`tools/`、`supabase/` 0 筆 |
| `python3 -m unittest discover -s tests -p "test_*.py"` | anchors：§3.6 三例；sample 44 錨點；normalize_content 冪等；與 `anchor_vectors.json` 一致。publish：驗證拒收各條件；`--dry-run` 不產生網路呼叫（monkeypatch `urllib.request.urlopen` 必須不被呼叫）；遷移：改一字 → ratio ≧ 0.6 對上；完全不同 → orphaned；私密 fixture 存在才跑「兩期都能正規化、錨點無錯」 |
| `bash tools/check_leak.sh` | 探針讀 `private/leak_probes.txt`（每行一探針，自行填 fixture 專屬字串，**不得寫進腳本**）；對 `web/` 與 `git ls-files -co --exclude-standard`（含未追蹤但非 ignore）grep 須 0 筆，**排除 `docs/PLAN.md`**（使用者的規格檔，其 §9 本身就引用探針範例字串，不可改）；陽性對照：每個探針在 `private/fixtures/` ≧ 1 筆，否則 exit 2「探針失效」；探針檔不存在 → exit 0 並印警告 |

補充：python 測試檔開頭 `sys.path.insert(0, <repo_root>)` 後 `from tools import anchors`（tools/ 放空的 `__init__.py`，publish 擁有）。lint 的探針 grep 同樣排除 `docs/PLAN.md`。

### 7.1 sample.json 必含（§8.3 已滿足，render 逐字落檔）
kicker、h1(note+tight)、h1(無 note)、callout（含 `**`、`!!`、`\n`）、stats×4（含 accent 三色、一張缺 u）、stats×2、cap、bars（5 列：navy/green/blue/缺色/grey；pct int 與 float；一列 3 元素）、table：seq/role/day×2/decision/agenda（含 `\n` 格、`<script>` 格）、day×2、頂層 photos map（3 張）、inline photos block（2 張、cols=2）、bullets×3（含重複項）、footnote、outfile（須被忽略）。

### 7.2 E2E（integrate）
`python3 -m http.server 8787 --directory ~/Projects/landseed-work-report`（背景）→ puppeteer 開 `http://localhost:8787/web/index.html#k=demo-reader-1&r=<period>`；流程：留言 → 切 `#k=demo-author` 回覆 → 切回 reader 設狀態「同意」→ reload 仍在；`setViewport({width:390})` 與 1280 各截圖到 `private/shots/`；斷言 `document.documentElement.scrollWidth <= 390`。

---

## 8. CIS token 與 sample.json

### 8.1 `web/css/tokens.css`（唯一持有 hex 的檔；名稱固定，值來自 render.py）
```css
:root {
  --navy:#0054A7; --blue:#008CD6; --green:#009C42; --light:#EFF6FC; --grey:#6E6A67;
  --red:#C00000; --band:#D9E4EE; --ink:#3E3A39; --headfill:#D3EDFB;
  --thead-bg:#EAF2F9; --thead-fg:#0054A7; --white:#FFFFFF;
  --bg:#FFFFFF; --bg-muted:#EFF6FC;          /* body 背景須明確設 var(--bg) */
  --font-sans:"Microsoft JhengHei","微軟正黑體","PingFang TC","Noto Sans TC",sans-serif;
  --fs-body:15px; --fs-small:13px; --fs-h1:20px; --fs-title:26px; --fs-stat:30px; --lh-body:1.6;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-6:24px; --sp-8:32px;
  --radius:6px; --logo-h:36px;               /* logo 只設 height，width:auto，比例 5.3929:1 */
}
```
需要透明度或衍生色（hover、陰影）一律在 tokens.css 另開 token（如 `--shadow`、`--blue-soft`），app.css 不得出現任何色值字面。斷點（600/1023/1024）是 media query 字面值，不是 token。禁止深藍底白字橫條；表頭 `--thead-bg`／`--thead-fg`；框線 `--band`；內文 `--ink`。

### 8.2 lint 規則（integrate 實作，render 必須遵守）
- `web/**/*.{html,css,js}` 除 `web/css/tokens.css`：正則 `#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])` 與 `/\b(rgba?|hsla?)\(/` 皆 0 筆。
- `web/**` 無 `service_role`。
- 第三方 CDN 只允許 §5.1 那一條 URL。

### 8.3 `tests/fixtures/sample.json`（render 逐字落檔；假資料，涵蓋全部區塊）
```json
{
  "title": "林踐宇個人工作報告",
  "period": "2026年10月5日（一）～2026年10月7日（三）",
  "to": "張院長",
  "from": "林踐宇",
  "outfile": "D:/ignored/工作報告_sample_v1.docx",
  "photos": {
    "10月5日（一）": [
      ["photos/p1.jpg", "3F／候診區：天花板補漆完成"],
      ["photos/p2.jpg", "B1／機房：水泵 **更換** 中"],
      ["photos/p3.jpg", "RF／水塔：!!漏水點!! 已封"]
    ]
  },
  "blocks": [
    {"kicker": "Section 01 · Highlights"},
    {"h1": "一、本期重點事項", "note": "截至 10 月 7 日", "tight": true},
    {"callout": "本期 **三項** 重點：甲案進度 !!落後 2 天!!，乙案完成驗收，丙案啟動。\n次週重點：補齊甲案人力。"},
    {"stats": [
      {"v": "12", "u": "項", "label": "本期事項", "note": "較上期 +2"},
      {"v": "87", "u": "%", "label": "甲案進度", "note": "預定 90%", "accent": "009C42"},
      {"v": "3", "label": "待決事項", "accent": "C00000"},
      {"v": "1", "u": "件", "label": "新啟動專案", "accent": "008CD6"}
    ]},
    {"cap": "各專案進度（曆日）"},
    {"bars": [
      ["甲案 裝修", "87 / 100 曆日", 87, "navy"],
      ["乙案 機電", "60 / 60 曆日", 100.0, "green"],
      ["丙案 規劃", "5 / 120 曆日", 4.2, "blue"],
      ["丁案 保固", "已結案", 100],
      ["戊案 評估", "尚未開始", 0, "grey"]
    ]},
    {"table": {"grid": "seq", "rows": [
      ["序", "所屬專案", "重點事項", "結果與後續"],
      ["1", "甲案", "3F 天花板補漆", "完成；10/8 辦理查驗"],
      ["2", "乙案", "機電驗收", "**通過**；缺失 3 項 10/10 前改善"],
      ["3", "丙案", "規劃啟動會議 <script>alert(1)</script>", "會議紀錄 10/9 送出"]
    ]}},
    {"kicker": "Section 02 · Roles"},
    {"h1": "二、專案角色與權責", "tight": true},
    {"table": {"grid": "role", "rows": [
      ["專案", "參與角色", "權責範圍／本期重點"],
      ["甲案", "PCM", "進度管控\n品質查驗"],
      ["乙案", "PCM", "驗收與缺失追蹤"]
    ]}},
    {"kicker": "Section 03 · Schedule"},
    {"h1": "三、行程與工作內容", "note": "10/5～10/7", "tight": true},
    {"day": "10月5日（一）"},
    {"table": {"grid": "day", "rows": [
      ["時間", "工作項目", "工作內容／預期產出"],
      ["09:00", "工地巡檢", "3F 補漆現況確認\n拍照存證"],
      ["14:00", "甲案進度會", "確認 !!落後 2 天!! 的補救方案"]
    ]}},
    {"day": "10月6日（二）"},
    {"table": {"grid": "day", "rows": [
      ["時間", "工作項目", "工作內容／預期產出"],
      ["09:00", "工地巡檢", "B1 機房泵浦更換"],
      ["09:00", "工地巡檢", "RF 水塔漏水點複查"],
      ["16:00", "乙案驗收", "缺失清單定稿"]
    ]}},
    {"photos": [
      {"file": "photos/p4.jpg", "cap": "B1／機房：新泵浦就位"},
      {"file": "photos/p5.jpg", "cap": "B1／機房：舊泵浦拆除"}
    ], "cols": 2},
    {"kicker": "Section 04 · Decisions"},
    {"h1": "四、關鍵決議", "note": "已發生之決議", "tight": true},
    {"table": {"grid": "decision", "rows": [
      ["事項", "決議／結果", "後續作業"],
      ["甲案 人力補強", "同意增派 2 名木工", "10/8 進場"],
      ["乙案 缺失改善期限", "10/10 前完成", "PCM 複驗"]
    ]}},
    {"bullets": [
      "追蹤：甲案補漆查驗 10/8。",
      "追蹤：乙案缺失複驗 10/11。",
      "追蹤：甲案補漆查驗 10/8。"
    ]},
    {"kicker": "Section 05 · Digest"},
    {"h1": "五、會議摘錄", "note": "工務週會", "tight": true},
    {"stats": [
      {"v": "2", "u": "場", "label": "本期會議"},
      {"v": "5", "u": "項", "label": "待辦"}
    ]},
    {"table": {"grid": "agenda", "rows": [
      ["項目", "重點"],
      ["空調汰換", "預算 ≧ 300 萬，11 月提案"],
      ["消防改善", "圖審 10/20 送件"]
    ]}},
    {"footnote": "資料來源：各專案日報與會議紀錄（2026/10/5～10/7）。"}
  ]
}
```
sample 的照片檔不存在：render 測試不需要實體圖；publish 的 `--mock`/`--dry-run` 測試對 sample 須以 `--skip-photos` 旗標跳過照片存在檢查（publish 自行提供此旗標，僅測試用）。

---

## 9. 各路開工自檢
- db ↔ api：RPC 名稱／參數名（§5.2）、raise 字串（§5.3）、回傳鍵名逐字相同；`rp_list_comments` 的 `p_since` 為 `timestamptz default null`。
- render ↔ publish：`normalizeContent`（§2.2）、來源字串（§3.3）、空白字元集（§3.1）、sec 規則（§3.2）、去重鍵（§3.4）；§3.6 三例與 §3.7 44 列相同。
- render ↔ integrate：`data-anchor/data-kind/data-statusable` 與 `cmt-slot` 掛點（§4.3）。
- api ↔ publish：`private/mock/*.json` 形狀（§6.2、§6.3）、照片 url 相對路徑以 `web/index.html` 為基準。
- 全體：hex 只在 tokens.css；`service_role` 只在 tools/、supabase/；本檔與 sample.json 皆為假資料，不得抄 fixture 任何原句；不 commit、不 push。
