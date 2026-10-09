// 錨點交叉驗證：JS（web/js/anchors.js）與 Python（tools/anchors.py，經 publish.py --vectors）逐筆相同
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { normalizeContent, buildAnchors } from "../web/js/anchors.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function pyVectors(file, period) {
  const r = spawnSync("python3", [join(root, "tools/publish.py"), file, "--vectors", "--period", period], {
    cwd: root, encoding: "utf8",
  });
  assert.equal(r.status, 0, `publish.py --vectors 失敗：${r.stderr}`);
  return JSON.parse(r.stdout);
}

function jsVectors(file) {
  const { anchors, errors } = buildAnchors(normalizeContent(JSON.parse(readFileSync(file, "utf8"))), { strict: true });
  assert.deepEqual(errors, []);
  return anchors;
}

test("sample.json：JS ＝ Python ＝ tests/anchor_vectors.json", () => {
  const file = join(root, "tests/fixtures/sample.json");
  const js = jsVectors(file);
  const py = pyVectors(file, "sample");
  const stored = JSON.parse(readFileSync(join(root, "tests/anchor_vectors.json"), "utf8"));
  assert.equal(js.length, 44);
  assert.deepEqual(py, js);
  assert.deepEqual(stored, js, "anchor_vectors.json 過期，請以 publish.py --vectors 重產");
});

for (const name of ["260928-1002", "260921-27"]) {
  const file = join(root, "private/fixtures", name + ".json");
  test(`私密 fixture ${name}：JS ＝ Python 逐筆相同`, { skip: existsSync(file) ? false : `${file} 不存在` }, () => {
    const js = jsVectors(file);
    const py = pyVectors(file, name);
    assert.ok(js.length > 0);
    assert.equal(py.length, js.length);
    for (let i = 0; i < js.length; i++) assert.deepEqual(py[i], js[i], `第 ${i} 筆不同（bi=${js[i].bi}）`);
    assert.equal(new Set(js.map((a) => a.anchor)).size, js.length, "錨點不得重複");
  });
}
