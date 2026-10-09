// Node 25 的 `node --test tests/` 會把目錄當成進入點模組執行；本檔讓它載入同層所有 *.test.js。
// 不遞迴（tests/e2e/ 需起伺服器與瀏覽器，獨立執行）。
import { readdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
for (const f of readdirSync(here).filter((n) => n.endsWith(".test.js")).sort()) {
  await import(pathToFileURL(`${here}/${f}`).href);
}
