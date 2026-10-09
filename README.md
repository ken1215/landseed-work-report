# 林踐宇個人工作報告：雙向 HTML 版

把每週用 `landseed-two-day-report` 產出的 `content.json` 發佈成線上報告。院長等讀者用自己的專屬連結開啟，可以：
- 逐區塊、逐表格列、逐條列留言
- 標記「已閱」
- 對決議列與追蹤條列標示「同意／再議／請補資料」

作者回覆後，讀者首頁會出現「新回覆」徽章。

- 網站：`web/`（GitHub Pages 只發佈這個資料夾，零建置、零相依）
- 資料：Supabase（報告內容、照片、留言、已閱、狀態）
- 規格：`docs/PLAN.md`（決策）、`docs/CONTRACTS.md`（介面契約）
- 上線步驟：`docs/HANDOFF.md`

> **目前狀態**：Supabase 帳號還沒開，網站只能用示範模式（mock）跑。所有 SQL 都還沒在資料庫上實測過。

---

## 每週操作三步驟（上線後）

1. **照舊產 docx**：用 `landseed-two-day-report` 產出當期報告。期間資料夾裡的 `_src/content.json` 就是網頁版的內容正本。
2. **發佈**：先試算一次，確認錨點與照片沒問題，再正式發佈：
   ```bash
   python3 tools/publish.py "<期間資料夾>" --dry-run
   python3 tools/publish.py "<期間資料夾>"
   ```
   同一期改版後重新發佈即可。舊留言會自動對應到新位置；對不上的會集中在頁尾的「未對應留言」區。
3. **授權給讀者**：新的一期要授權給讀者才看得到（作者自動看得到全部）：
   ```bash
   python3 tools/readers.py grant --name 張院長 --period <期別，例 260928-1002>
   ```
   讀者的專屬連結永久不變，不必每週重發。只要通知對方「新一期已上線」即可。

讀者管理：`python3 tools/readers.py add --name … --role reader`（印出專屬連結，只會顯示這一次）、`revoke --name …`（停用連結）、`list`。

---

## 分享連結（目前使用：單向、免登入）

2026-10-09 起網站為**單向模式**（`web/js/ui.js` 的 `TWO_WAY=false`：只閱讀、不留言），對外一律用「報告分享連結」：
每期一把隨機金鑰，網址 `…/index.html#s=<金鑰>`，點開直接看該期，看不到其他期別，不需登入。

```bash
python3 tools/share.py link  --period 261003-1009            # 印出（或首次建立）該期分享連結
python3 tools/share.py link  --period 261003-1009 --rotate   # 連結外流時換新金鑰，舊連結立即失效
python3 tools/share.py opens --period 261003-1009            # 查開啟紀錄（UTC），供「有沒有打開」查證
```
- 金鑰明文只存本機 `private/share_links.json`，資料庫只存 SHA-256。
- 每週流程：`publish.py <週資料夾>` → `share.py link --period <期別>` → 把連結傳給院長。
- 原本的個人專屬連結（`#k=`）與 `readers.py` 仍保留，恢復雙向時使用。

## 本機 demo（不需要 Supabase）

```bash
cd ~/Projects/landseed-work-report
python3 -m http.server 8787 --directory web
```
瀏覽器開 <http://localhost:8787/index.html#k=demo-reader-1>。

- `web/js/config.js` 留空時會自動進入**示範模式**。內容取自 `web/demo/sample.json`（假資料，可公開）。
- 頁面上方的示範列可以切換身分：作者（`demo-author`）、讀者張院長（`demo-reader-1`）、讀者乙（`demo-reader-2`）。
- 留言只存在這台電腦瀏覽器的 localStorage 裡。按「清除示範留言」即可重來。
- 試一輪的流程：
  1. 以讀者身分在表格列按 💬 留言。
  2. 切到作者身分回覆。
  3. 切回讀者，首頁會出現「新回覆」徽章。
  4. 進報告頁，在決議列按「同意」。
- 真實期別不會出現在示範模式裡。**本機預覽真實期別**（資料只在本機 `private/`，不會發佈）：
  ```bash
  python3 tools/publish.py "<期間資料夾>" --mock          # 產出 private/mock/<期別>.json
  python3 -m http.server 8799 --bind 127.0.0.1           # 在專案根目錄起（不是 web/）
  ```
  開 <http://127.0.0.1:8799/web/index.html?local=1#k=demo-reader-1>（`?local=1` 改讀 private/mock）。

## 測試

```bash
node --test tests/                                   # render / anchors / api-mock / lint / JS↔Python 錨點交叉驗證
python3 -m unittest discover -s tests -p "test_*.py" # publish / anchors / readers / SQL 靜態檢查
bash tools/check_leak.sh                             # 私密字串洩漏探針＋金鑰字樣
node tests/e2e/e2e.mjs                               # 瀏覽器 E2E（需先 npm i；截圖存 private/shots/）
```
E2E 用到 puppeteer，只裝在本機的 devDependencies（`npm i`），網站本身不依賴它。

## 上線前要做的事

照 **`docs/HANDOFF.md`** 逐步做。大致流程：
1. 開 Supabase 專案，推 migration。
2. 跑存取控制測試。
3. 建立讀者、發佈第一期。
4. 在 `config.js` 填入 anon key。
5. 開 GitHub Pages。

**私密資料不得進 git**：`private/` 已在 `.gitignore`。每次 push 前請跑 `bash tools/check_leak.sh`，必須是 exit 0。
