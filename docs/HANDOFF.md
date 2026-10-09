# HANDOFF：Supabase 帳號開好後的上線清單

> **⚠ SQL 未實測。** `supabase/migrations/*.sql` 與 `supabase/tests/access.sql` 撰寫時沒有 Supabase 帳號，本機也沒有 psql/docker，只做過靜態自檢（`python3 -m unittest tests.test_sql_static`）。第一次 `db push` 很可能會遇到語法或權限細節問題，請照下面的順序逐步做，每一步確認後再往下。
> 本檔由 db 路起草，integrate 階段會補前端與 E2E 段落（請合併，不要整份覆寫）。

## 0. 前置
- 建立 Supabase 專案，記下 `Project URL`、`anon key`、`service_role key`（Settings → API）。
- 建立 `private/.env.local`（已被 .gitignore 排除，**不得 commit**）：
  ```
  SUPABASE_URL=https://<project-ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=<service_role key>
  PAGES_BASE_URL=https://<github-user>.github.io/<repo>/
  ```
  `PAGES_BASE_URL` 只用來印個人連結，Pages 還沒開時可先寫 `http://localhost:8787/web/`。
- shell 變數（後續 curl 用）：
  ```bash
  export URL=https://<project-ref>.supabase.co
  export ANON=<anon key>
  ```

## 1. 連結專案
```bash
cd ~/Projects/landseed-work-report
supabase login
supabase link --project-ref <project-ref>
```
CLI 以 `^[0-9]+_.*\.sql$` 讀 migration，`0001_`／`0002_`／`0003_` 應可直接用；若你的 CLI 版本要求 14 位時間戳，改名為 `20261009000001_schema.sql`、`…02_rpc.sql`、`…03_notifications.sql`（順序不可變）。

## 2. 推 schema
```bash
supabase db push
```
內容：pgcrypto（`extensions` schema）、8 張表（全部 RLS enable、無任何 policy、對 anon/authenticated revoke 表權限）、`report-photos` private bucket、10 支 `rp_*` RPC（security definer、`set search_path = public, extensions`、revoke from public 後 grant execute to anon/authenticated）、5 支內部 helper（`_rp_*`，anon 不可執行）、`comments` after insert 通知 trigger。

失敗時的備援：在 SQL Editor 依序貼上 0001 → 0002 → 0003 執行。
推完到 Storage 頁確認有 `report-photos` 且為 Private（0001 用 `insert into storage.buckets` 建；若失敗就手動建同名 private bucket）。

## 3. 讓 PostgREST 重新載入 schema
SQL Editor 執行：
```sql
NOTIFY pgrst, 'reload schema';
```
驗證：`curl -s "$URL/rest/v1/rpc/rp_whoami" -H "apikey: $ANON" -H "Authorization: Bearer $ANON" -H "Content-Type: application/json" -d '{"p_token":"x"}'` 應回 HTTP 400、`"message":"invalid token"`（若回 404 `PGRST202` 表示 schema cache 還沒更新）。

## 4. 建立讀者
先 dry-run 看請求，再實建：
```bash
python3 tools/readers.py add --name 林踐宇 --role author --dry-run
python3 tools/readers.py add --name 林踐宇 --role author
python3 tools/readers.py add --name 張院長 --role reader
python3 tools/readers.py list
```
- 每次 `add` 印出一條 `…/index.html#k=<token>`，**明文 token 只出現這一次**，DB 只存 `sha256` 小寫 hex。遺失 → `revoke` 後重建。
- 讀者需要期別授權（author 自動看全部）：先完成第 5 步發佈，再 `python3 tools/readers.py grant --name 張院長 --period 260928-1002`（或 `add` 時帶 `--periods`）。
- 撤銷：`python3 tools/readers.py revoke --name 張院長`（同名多位時會拒絕操作）。

## 5. 發佈 260928-1002
（publish.py 由 publish 路提供，參數以 CONTRACTS §6.4 為準）
```bash
python3 tools/publish.py <260928-1002 期間資料夾（含 _src/content.json）> --dry-run
python3 tools/publish.py <260928-1002 期間資料夾>
python3 tools/readers.py grant --name 張院長 --period 260928-1002
```
確認：`reports` 有一列 `period='260928-1002'`、`status_anchors` 非空、照片已在 `report-photos/260928-1002/`。

## 6. 填前端設定
`web/js/config.js`：
```js
export const CONFIG = { SUPABASE_URL: "https://<project-ref>.supabase.co", SUPABASE_ANON_KEY: "<anon key>" };
```
**只能放 anon key**；service_role key 絕不可出現在 `web/`（lint 測試會擋）。

## 7. 存取控制測試（≧ 8 條，必須全過才可把連結給院長）

### 7.1 SQL 版（一次跑 18 條）
SQL Editor 貼上 `supabase/tests/access.sql` 整份執行。它在單一交易內建測試夾具、最後 `rollback`，不留資料。Messages 應依序出現 `TEST 1 OK` … `TEST 18 OK`；任一條失敗會中止並顯示 `TEST n FAILED …` 或 `expected "…" but got "…"`。

### 7.2 HTTP 版（實際走 PostgREST＋anon key，與前端相同路徑）
先準備：`R1=<張院長的 token>`、`AU=<林踐宇的 token>`、`RID=<260928-1002 的 report id>`（`select id from reports where period='260928-1002'`）。
共用函式：
```bash
rpc() { curl -s -w "\nHTTP %{http_code}\n" "$URL/rest/v1/rpc/$1" \
  -H "apikey: $ANON" -H "Authorization: Bearer $ANON" -H "Content-Type: application/json" -d "$2"; }
```
PostgREST 會把 `raise exception` 轉成 HTTP 400、body `{"code":"P0001","message":"<字串>"}`；前端以 `message` 比對（CONTRACTS §5.3）。

| # | 情境 | 指令 | 預期 |
|---|---|---|---|
| 1 | 無效 token | `rpc rp_whoami '{"p_token":"nope"}'` | 400 `invalid token` |
| 2 | 撤銷 token | `python3 tools/readers.py add --name 測試撤銷 --role reader` 取得 token T → `revoke --name 測試撤銷` → `rpc rp_whoami "{\"p_token\":\"$T\"}"` | 撤銷前 200、撤銷後 400 `invalid token` |
| 3 | 讀者讀未授權期別 | 發佈第二期（例 260921-27）但不 grant → `rpc rp_get_report "{\"p_token\":\"$R1\",\"p_period\":\"260921-27\"}"` | 400 `forbidden` |
| 4 | 讀者改他人留言 | `rpc rp_add_comment "{\"p_token\":\"$AU\",\"p_report_id\":\"$RID\",\"p_anchor\":\"s1/blk/test\",\"p_body\":\"作者留言\",\"p_parent_id\":null}"` 取 id=C → `rpc rp_edit_comment "{\"p_token\":\"$R1\",\"p_comment_id\":\"$C\",\"p_body\":\"x\"}"` | 400 `forbidden` |
| 5 | anon 直接 select 表 | `curl -s -w "\nHTTP %{http_code}\n" "$URL/rest/v1/comments?select=*" -H "apikey: $ANON" -H "Authorization: Bearer $ANON"`（readers、reports 各再試一次） | 401/403 `42501 permission denied`（若權限沒 revoke 成功則為 200 `[]`，也算擋住但請回報） |
| 6 | 狀態寫到不可指示錨點 | `rpc rp_set_status "{\"p_token\":\"$R1\",\"p_report_id\":\"$RID\",\"p_anchor\":\"s1/blk/test\",\"p_status\":\"同意\"}"` | 400 `anchor not statusable` |
| 7 | body 超長 | `B=$(python3 -c 'print("字"*2001)')` → `rpc rp_add_comment "{\"p_token\":\"$R1\",\"p_report_id\":\"$RID\",\"p_anchor\":\"s1/blk/test\",\"p_body\":\"$B\",\"p_parent_id\":null}"` | 400 `body too long` |
| 8 | author 讀全部 | `rpc rp_list_reports "{\"p_token\":\"$AU\"}"` | 200，含所有已發佈期別（含未 grant 給任何人的 260921-27），每期 `readers` 為陣列 |
| 9 | author 設狀態被拒 | `rpc rp_set_status` 以 `$AU` 對 `status_anchors` 裡任一錨點 | 400 `forbidden` |
| 10 | anon 呼叫內部 helper | `rpc _rp_auth "{\"p_token\":\"$AU\"}"` | 401/403 `42501` 或 404（不得 200） |

第 4、7 步產生的測試留言，跑完以 service_role 刪除：`delete from comments where anchor = 's1/blk/test';`。第 2 步的「測試撤銷」讀者保持 revoked 即可。

## 8. 已知限制（v1）
- `rp_list_comments(p_since)` 增量輪詢收不到「狀態被清除（設 null）」——該列已刪除；前端需定期全量重抓（例如每 N 次輪詢一次 `p_since=null`）或於本人操作後直接更新畫面。
- 刪除留言會更新 `edited_at`，增量輪詢可收到 `deleted=true`。
- `server_time` 取交易開始時間 `now()`；極端並發下可能漏抓與輪詢同時提交的留言，下一次全量重抓會補回。
- notifications 只寫不外送（`sent_at` 永遠 null），Email/LINE 為 v2。

---

## 9. 前端上線（integrate 段）

### 9.1 填設定
`web/js/config.js` 填入 URL 與 **anon key**（第 6 步）。填了之後網站就會改走 Supabase：
- 示範模式（`demo-*` token、`web/demo/`）自動停用。
- 用 `demo-*` 開會顯示「連結無效」，這是正常的。
- `web/demo/sample.json` 是公開假資料，**請保留**：lint 測試會比對它和 `tests/fixtures/sample.json` 是否逐位元相同。

### 9.2 GitHub Pages 只發佈 `web/`
Pages 的「從分支部署」只支援 repo 根目錄或 `/docs`，**不能直接選 `web/`**。請改用 GitHub Actions 部署（Settings → Pages → Source 選 GitHub Actions），新增 `.github/workflows/pages.yml`：
```yaml
name: pages
on: { push: { branches: [main] }, workflow_dispatch: {} }
permissions: { contents: read, pages: write, id-token: write }
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: { name: github-pages }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/upload-pages-artifact@v3
        with: { path: web }
      - uses: actions/deploy-pages@v4
```
push 之前一定要先跑 `bash tools/check_leak.sh`，必須是 exit 0；`node --test tests/` 也要全綠（含 lint）。

### 9.3 上線後的人工驗收（真 Supabase，E2E 目前只跑過 mock）
用兩個瀏覽器（或一般視窗＋無痕視窗）分別開作者連結和讀者連結：
1. 讀者在表格列留言。
2. 作者在 20 秒內看到 💬 計數變化；回到首頁看到「未讀」。
3. 作者回覆後，讀者首頁出現「新回覆」。
4. 讀者在決議列按「同意」，作者端看到「張院長：同意」。
5. 重新整理後，以上內容都還在。
6. 用手機開讀者連結：不能整頁左右滑，表格可以單獨橫捲，留言抽屜從底部出現。
7. 把讀者連結 revoke 後重新整理，應顯示「連結無效或已停用」。

### 9.4 前端行為備忘
- token 讀到後存 `localStorage["lwr.token"]`，網址列會改成 `#r=<期別>`，避免截圖外洩。私密視窗存不進去時只放在記憶體，重新整理後要重開專屬連結。
- 輪詢每 20 秒一次；分頁回到前景時會立刻抓一次。每 6 次輪詢做一次全量重抓（補上被清除的狀態，見 §8）。
- 讀者開報告頁會呼叫 `rp_mark_read`。首次載入、以及之後收到他人新留言時，會呼叫 `rp_mark_seen`，讓首頁的未讀數歸零。
- 「未對應留言」區會列出 `orphaned=true` 的留言，以及錨點已不在頁面上的留言。

## 實機紀錄（2026-10-09）
- 專案 `landseed-work-report`（ref `qrbbdsswglmnbbedezlf`），區域 **Northeast Asia (Seoul) ap-northeast-2**；Session pooler 主機 `aws-0-ap-northeast-2.pooler.supabase.com`（`aws-1-…` 會回 tenant not found）。
- 不用 `supabase login/link`（避免 CLI 切帳號影響其他專案）：`supabase db push --db-url "$(python3 tools/dburl.py)"`。三支 migration 一次推成功。
- 多段 SQL（含 `do $$`）用 `private/.venv/bin/python tools/run_sql.py <檔>`（pg8000，simple query）；`supabase db query` 不支援多指令。
- `supabase/tests/access.sql` 18 條實機全過（TEST 13 原本是測試寫法錯：同一個 if 內無關聯 `exists` 會被當 InitPlan 先算，已改成先呼叫再檢查）。跑完各表 0 列、`report-photos` 為 private。
- anon 直接打 REST `readers` → 42501 permission denied（符合設計）。
