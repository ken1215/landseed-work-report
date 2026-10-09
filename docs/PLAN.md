# 林踐宇個人工作報告 — 雙向 HTML 版（PLAN v1）

> 本檔是 workflow 的唯一規格來源。Planner 只「細化」本檔，不推翻已鎖定的決策（§1）。

## 0. 背景
- 每週使用者仍照舊用 `landseed-two-day-report` 技能產 docx，內容正本＝該期資料夾 `_src/content.json`。
- 本專案把同一份 content.json 發佈成線上雙向報告：院長等讀者可閱讀、逐區塊留言、標「已閱」、對決議/追蹤項指示狀態；作者（林踐宇）可回覆。
- 範例資料：`private/fixtures/260928-1002.json`、`260921-27.json`（**私密，不得進 git**）。
- docx 渲染器參考：`~/.claude/skills/landseed-two-day-report/scripts/render.py`（區塊語彙、GRIDS、色票，唯讀，不可修改）。

## 1. 已鎖定決策（使用者 2026-10-09 確認）
1. **託管**：GitHub Pages（public repo，只放網頁外殼）＋ Supabase（報告內容、照片、留言、已閱、狀態）。Supabase 帳號尚未開——所有 DB 相關一律可 mock，SQL 標「未實測」。
2. **身分**：個人專屬永久連結 `index.html#k=<token>`。一人一條連結看得到他被授權的所有期別（不是每週發新連結）。token 只存 SHA-256 雜湊；可撤銷（active=false）。角色 `author | reader`。
3. **留言粒度**：每個區塊、每個表格資料列（表頭 rows[0] 不可留言）、每個 bullet 項都可留言；支援一層回覆串（parent_id）。
4. **雙向功能**：①留言/回覆 ②「已閱」（記錄每位讀者每期首次與最近開啟時間）③狀態指示：僅限 grid=`decision` 的資料列與 `bullets` 項，值＝`同意｜再議｜請補資料`，每位讀者每個錨點一個最新值 ④通知：v1 做站內（作者回覆後讀者看到「新回覆」徽章／未讀數；讀者留言後作者首頁看到未讀）＋ `notifications` outbox 表與 trigger 預留；Email/LINE 外送列為 v2，不在本次範圍。
5. **即時**：v1 用輪詢（每 20 秒＋`visibilitychange` 回前景立即重抓）。原因：表全部 deny-all RLS，`postgres_changes` 對 anon 收不到事件。v2 可改 `realtime.broadcast_changes()`。

## 2. 架構
```
landseed-work-report/            （本機，git repo，將推 GitHub public）
├─ web/                          ← GitHub Pages 發佈根（只放這個）
│  ├─ index.html                 單頁：讀者首頁(期別清單) / 報告頁 (#k=token&r=<period>)
│  ├─ css/tokens.css             CIS 色票＋字級 token（唯一允許出現 hex 的檔）
│  ├─ css/app.css                版面＋RWD（只能用 var(--*)）
│  ├─ js/render.js               content.json → DOM（純函式，可在 node 測）
│  ├─ js/anchors.js              錨點產生（與 publish.py 演算法一致，兩邊共用測試向量）
│  ├─ js/api.js                  介面＋ mock(localStorage) / supabase(RPC) 兩實作
│  ├─ js/ui.js                   留言抽屜、已閱、狀態鈕、徽章、輪詢
│  ├─ js/config.js               SUPABASE_URL / ANON_KEY（空值＝自動走 mock）
│  └─ img/logo-cis.png           5.3929:1，不可壓扁
├─ supabase/migrations/*.sql     schema＋RPC＋RLS
├─ tools/publish.py              期間資料夾 → 上傳 content＋照片 → reports 表；錨點遷移
├─ tools/readers.py              建立/撤銷讀者、印出個人連結（service_role，本機用）
├─ tests/                        node:test（render/anchors/api-mock/lint）＋ python unittest（publish/anchors）
├─ private/                      fixtures、照片、.env.local（gitignore）
└─ docs/PLAN.md, HANDOFF.md, README.md
```

## 3. 區塊語彙（必須與 render.py 完全對應）
頂層：`title, period, to, from, outfile(忽略), photos{日期標籤:[[路徑,圖說]×3]}, blocks[]`。
block 以第一個 key 判型：`kicker | h1(+note,+tight) | cap | stats[{v,u,label,note,accent}] | bars[[標籤,數值文字,百分比,顏色]] | callout | table{grid,rows} | day | bullets[] | photos | footnote`；未知 key → 顯示錯誤區塊並 console.error（不可靜默略過）。
- 文字標記：`**深藍粗體**`、`!!紅色粗體!!`、`\n` 換行。一律先 escape HTML 再套標記（防 XSS）。
- table：grid 名稱 → 欄寬比例（GRIDS: topic/role/day/decision/agenda/seq）；rows[0] 為表頭；欄數不符 grid → 錯誤區塊。
- bars：百分比只決定條長，數值文字照抄。顏色 blue/navy/green/grey/red。
- photos：依 `day` 標籤原文對應，接在該日行程表之後；網頁版圖片來源由 publish 改寫為 Storage 簽章 URL（或 mock 時的相對路徑）。

## 4. 錨點（anchor）規則
- `anchor = <sec>/<kind>/<h>`：sec＝所屬 h1 序號（無 h1 前為 `s0`）；kind＝`blk|row|li`；h＝內容雜湊（SHA-1 前 10 hex），來源字串：
  - 區塊：block 型別＋正規化全文
  - 表格列：grid 名稱＋該列第 1、2 欄正規化文字（day 表另加所屬 day 標籤）
  - bullet：正規化全文
  - 正規化＝去空白、去 `**`/`!!` 標記、全形半形不轉
- 同 sec 內重複雜湊 → 加 `-2`,`-3` 後綴。
- JS（`anchors.js`）與 Python（`publish.py`）必須產生相同結果：`tests/anchor_vectors.json` 為共用測試向量（由 fixture 產生的 輸入→期望錨點），兩邊都跑。
- 改版重發佈時 `publish.py` 做錨點遷移：舊錨點在新版不存在者 → 同 sec 同 kind 內以文字相似度（difflib ratio ≧ 0.6）找最佳對應並更新 comments/statuses 的 anchor；找不到的標 `orphaned=true`，頁面底部「未對應留言」區顯示。

## 5. 資料模型（Supabase）
表一律 `enable row level security` 且**不給 anon 任何 policy**（deny-all）；所有讀寫經 `security definer` RPC，第一個參數為 token。
- `readers(id uuid pk, name text, role text check in ('author','reader'), token_sha256 text unique, active bool default true, created_at)`
- `reports(id uuid pk, period text unique, title text, content jsonb, published_at, version int)`
- `report_access(report_id, reader_id, pk(report_id,reader_id))`（author 自動可看全部）
- `comments(id uuid pk, report_id, anchor text, reader_id, parent_id uuid null, body text check(length 1..2000), created_at, edited_at, deleted bool default false, orphaned bool default false)`
- `reads(report_id, reader_id, first_at, last_at, pk)`
- `statuses(report_id, anchor, reader_id, status text check in ('同意','再議','請補資料'), updated_at, pk(report_id,anchor,reader_id))`
- `seen(reader_id, report_id, last_seen_comment_at)` — 用來算未讀
- `notifications(id, reader_id, report_id, comment_id, kind, created_at, sent_at null)` — trigger：作者回覆讀者的留言 → 寫給該讀者；讀者留言 → 寫給所有 author。v1 不外送。
RPC（全部 `set search_path = public, extensions`、grant execute to anon）：
`rp_whoami(token)`、`rp_list_reports(token)`（含每期未讀數、是否已閱）、`rp_get_report(token, period)`（content＋版本）、`rp_mark_read(token, report_id)`、`rp_list_comments(token, report_id, since timestamptz null)`（含 statuses、作者名）、`rp_add_comment(token, report_id, anchor, body, parent_id)`、`rp_edit_comment` / `rp_delete_comment`（僅本人）、`rp_set_status(token, report_id, anchor, status|null)`（僅讀者；anchor 須屬可指示類型——由 publish 寫入 `reports.status_anchors text[]` 檢查）、`rp_mark_seen(token, report_id)`。
token 驗證：`readers.token_sha256 = encode(digest(token,'sha256'),'hex') and active`；失敗一律 raise `invalid token`（不洩漏原因）。
存取控制測試（HANDOFF 用，帳號開好後實跑）：無效 token、撤銷 token、讀者讀未授權期別、讀者改他人留言、anon 直接 select 表、狀態寫到不可指示錨點、body 超長、author 讀全部 —— 共 ≥ 8 條。

## 6. 前端
- 無建置步驟、無 npm 相依；supabase-js 以 ESM CDN 釘版本（`https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm`）；config 為空時完全不載 CDN、走 mock。
- 路由：`#k=<token>` → 首頁期別清單（最新在上，顯示 未讀/已閱/新回覆 徽章）；`#k=..&r=<period>` → 報告頁。token 讀到後存 localStorage（try/catch），並從網址列移除（`history.replaceState`）避免截圖外洩。
- 報告頁：頂部品牌列（logo-cis＋「林踐宇個人工作報告」）、期間/提報對象；左側（≧1024px）章節目錄 sticky；每個可留言單位 hover/點選出現 💬 計數鈕；留言抽屜：桌機右側面板、手機底部 sheet；狀態鈕（同意/再議/請補資料）在 decision 列與 bullets 旁，顯示各讀者的最新狀態。
- 已閱：開啟報告頁即 `rp_mark_read`；作者在首頁看到每期每位讀者的已閱時間。
- 列印：`@media print` 隱藏互動元件，版面接近 docx。
- 無障礙：按鈕有 aria-label；對比 ≧ 4.5:1。

## 7. CIS／視覺規範（硬性）
- 色票只來自 render.py：NAVY `#0054A7`、BLUE `#008CD6`、GREEN `#009C42`、LIGHT `#EFF6FC`、GREY `#6E6A67`、RED `#C00000`、BAND `#D9E4EE`、INK `#3E3A39`、HEADFILL `#D3EDFB`；soft-palette 補充：表頭 `#EAF2F9`/字 `#0054A7`；白 `#FFFFFF`。tokens.css 以外不得出現 hex（lint 測試強制）。
- **禁止深藍底白字橫條**；表頭淺藍底深藍字；框線 BAND；內文墨色、行距 1.6 左右。
- 字型：`"Microsoft JhengHei","微軟正黑體","PingFang TC","Noto Sans TC",sans-serif`；不載外部字型以外的東西（Google Fonts Noto Sans TC 可選）。
- Logo 寬高比 5.3929:1，CSS 只設 height、width:auto。
- 中文文件比較符號用全形 ≧ ≦。
- 深色模式：v1 不做（報告為正式文件，固定淺色），但 body 明確設背景色。

## 8. RWD（硬性）
- 斷點：≦ 600 手機、601–1023 平板、≧ 1024 桌機。
- 多欄表格：外層 `.tbl` 橫向捲動，依 grid 欄數設 min-width（3 欄 ≧ 560px、4 欄 ≧ 640px、2 欄不捲）；stats 手機變 2 欄；bars 標籤欄縮窄但不換行。
- 無水平整頁捲動；左右 16px gutter。
- 驗證：Puppeteer `page.setViewport({width:390})` 與 1280 各截一張（不要用 `--window-size`）＋斷言 `document.documentElement.scrollWidth <= 390`。

## 9. 測試與驗證（全部須實跑貼輸出）
- `node --test tests/` ：render（fixture 每種 block 都產出、table 欄數、XSS escape、未知 block 報錯）、anchors（向量、重複後綴）、api mock（留言/回覆/狀態/已閱/未讀流程）、lint（hex 只在 tokens.css、`service_role` 不在 web/、fixture 專屬字串不在 web/ 與 git 追蹤檔）。
- `python3 -m unittest discover tests`：publish（content 驗證、錨點向量一致、遷移相似度、dry-run 不碰網路）。
- E2E（puppeteer，裝在本機專案 devDependencies，`npm i -D puppeteer` 可）：mock 模式下以 fixture 開報告頁 → 留言 → 回覆 → 設狀態 → 重整後仍在；390/1280 截圖存 `private/shots/`。
- **洩漏防呆**：`tools/check_leak.sh` 以 fixture 專屬字串（探針清單見 private/leak_probes.txt）grep `web/` 與 `git ls-files`，必須 0 筆；陽性對照：同字串在 `private/fixtures` 必須 ≧1 筆，否則判探針失效。
- Python 3.9 相容（本機為 3.9.6）；SQL 未實測須明講。

## 10. 不做（本次）
- 不建 GitHub repo、不 push、不開 Pages（等使用者看過本機 demo）。
- 不連真 Supabase（帳號未開）。
- 不改 landseed-two-day-report 技能本體。
- Email/LINE 外送通知（v2）。
