import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import anchors, publish  # noqa: E402

SAMPLE = os.path.join(ROOT, "tests", "fixtures", "sample.json")
PRIVATE = [os.path.join(ROOT, "private", "fixtures", n) for n in ("260928-1002.json", "260921-27.json")]
LEAK = os.path.join(ROOT, "tools", "check_leak.sh")


def good():
    return {
        "title": "t", "period": "p", "to": "x", "from": "y",
        "blocks": [
            {"h1": "一、測試"},
            {"stats": [{"v": "1", "label": "a"}, {"v": "2", "u": "%", "label": "b"}]},
            {"bars": [["a", "1/2", 50, "navy"], ["b", "2/2", 100.0]]},
            {"day": "D1"},
            {"table": {"grid": "day", "rows": [["時間", "項目", "內容"], ["09:00", "巡檢", "x"]]}},
            {"table": {"grid": "decision", "rows": [["事項", "決議", "後續"], ["甲", "同意", "進場"]]}},
            {"bullets": ["追蹤一", "追蹤二"]},
        ],
    }


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = publish.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestValidate(unittest.TestCase):
    def errs(self, raw, check_photos=False, base=None):
        return publish.validate(raw, base_dirs=[base or ROOT], check_photos=check_photos)

    def test_good_passes(self):
        self.assertEqual(self.errs(good()), [])

    def test_missing_required(self):
        for k in ("title", "period", "from"):
            raw = good()
            del raw[k]
            self.assertTrue(any(k in e for e in self.errs(raw)), k)

    def test_unknown_block(self):
        raw = good()
        raw["blocks"].append({"weird": 1})
        self.assertTrue(self.errs(raw))
        raw = good()
        raw["blocks"].append({"cap": "a", "footnote": "b"})
        self.assertTrue(self.errs(raw))

    def test_table_column_mismatch(self):
        raw = good()
        raw["blocks"][4]["table"]["rows"][1] = ["09:00", "巡檢"]
        self.assertTrue(self.errs(raw))

    def test_stats_count(self):
        for n in (1, 5):
            raw = good()
            raw["blocks"][1]["stats"] = [{"v": str(i)} for i in range(n)]
            self.assertTrue(self.errs(raw), n)

    def test_stats_v_not_string(self):
        raw = good()
        raw["blocks"][1]["stats"][0]["v"] = 1
        self.assertTrue(self.errs(raw))

    def test_bars_row_short(self):
        raw = good()
        raw["blocks"][2]["bars"][0] = ["a", "1/2"]
        self.assertTrue(self.errs(raw))

    def test_bars_pct_not_number(self):
        for bad in ("50", None, True):
            raw = good()
            raw["blocks"][2]["bars"][0] = ["a", "1/2", bad]
            self.assertTrue(self.errs(raw), repr(bad))

    def test_top_photos_day_not_found(self):
        raw = good()
        raw["photos"] = {"不存在的日": [["a.jpg", "c"]]}
        self.assertTrue(self.errs(raw))

    def test_photo_file_missing(self):
        raw = good()
        raw["photos"] = {"D1": [["no_such_photo_xyz.jpg", "c"]]}
        self.assertEqual(self.errs(raw, check_photos=False), [])
        self.assertTrue(self.errs(raw, check_photos=True))

    def test_photo_file_present(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "p.jpg"), "wb") as f:
                f.write(b"\xff\xd8\xff")
            raw = good()
            raw["photos"] = {"D1": [["p.jpg", "c"]]}
            self.assertEqual(self.errs(raw, check_photos=True, base=d), [])
        finally:
            shutil.rmtree(d)


class TestPeriod(unittest.TestCase):
    def test_period_rules(self):
        self.assertEqual(publish.derive_period("/a/260928-1002/_src/content.json"), "260928-1002")
        self.assertEqual(publish.derive_period("/a/260928-1002/content.json"), "260928-1002")
        self.assertEqual(publish.derive_period("/a/fixtures/260921-27.json"), "260921-27")
        self.assertEqual(publish.derive_period("/a/x/sample.json"), "sample")


class TestMigration(unittest.TestCase):
    def entries(self, bullets):
        c = {"title": "t", "period": "p", "from": "y",
             "blocks": [{"h1": "四、關鍵決議"}, {"bullets": bullets}]}
        return anchors.build_anchors(anchors.normalize_content(c))

    def li(self, es):
        return [e["anchor"] for e in es if e["kind"] == "li"]

    def test_one_char_change_moves(self):
        old = self.entries(["追蹤：甲案補漆查驗 10/8。", "追蹤：乙案缺失複驗 10/11。"])
        new = self.entries(["追蹤：甲案補漆查驗 10/9。", "追蹤：乙案缺失複驗 10/11。"])
        plan = publish.plan_migration(old, new)
        moved = {m["from"]: m for m in plan["moved"]}
        self.assertIn(self.li(old)[0], moved)
        self.assertEqual(moved[self.li(old)[0]]["to"], self.li(new)[0])
        self.assertGreaterEqual(moved[self.li(old)[0]]["ratio"], 0.6)
        self.assertIn(self.li(old)[1], plan["kept"])
        self.assertEqual(plan["orphaned"], [])

    def test_totally_different_orphaned(self):
        old = self.entries(["追蹤：甲案補漆查驗 10/8。"])
        new = self.entries(["XYZ abc 123 完全無關的新文字"])
        plan = publish.plan_migration(old, new)
        # bullets 的 blk 錨點（全文雜湊）也會變，只看 li
        self.assertEqual([m for m in plan["moved"] if "/li/" in m["from"]], [])
        self.assertEqual([a for a in plan["orphaned"] if "/li/" in a], [self.li(old)[0]])

    def test_one_to_one(self):
        old = self.entries(["追蹤：甲案補漆查驗 10/8。", "追蹤：甲案補漆查驗 10/7。"])
        new = self.entries(["追蹤：甲案補漆查驗 10/9。"])
        plan = publish.plan_migration(old, new)
        li_moved = [m for m in plan["moved"] if "/li/" in m["from"]]
        self.assertEqual(len(li_moved), 1)
        self.assertEqual(li_moved[0]["from"], self.li(old)[0])
        self.assertEqual([a for a in plan["orphaned"] if "/li/" in a], [self.li(old)[1]])

    def test_same_sec_and_kind_only(self):
        c_old = {"title": "t", "period": "p", "from": "y",
                 "blocks": [{"h1": "A"}, {"bullets": ["追蹤：甲案補漆查驗 10/8。"]}]}
        c_new = {"title": "t", "period": "p", "from": "y",
                 "blocks": [{"h1": "A"}, {"h1": "B"}, {"bullets": ["追蹤：甲案補漆查驗 10/9。"]}]}
        old = anchors.build_anchors(anchors.normalize_content(c_old))
        new = anchors.build_anchors(anchors.normalize_content(c_new))
        plan = publish.plan_migration(old, new)
        self.assertNotIn(self.li(old)[0], [m["from"] for m in plan["moved"]])
        self.assertIn(self.li(old)[0], plan["orphaned"])

    def test_tie_takes_document_order(self):
        old = self.entries(["abcdefghij"])
        new = self.entries(["abcdefghiX", "abcdefghiY"])
        plan = publish.plan_migration(old, new)
        li_moved = [m for m in plan["moved"] if "/li/" in m["from"]]
        self.assertEqual(li_moved[0]["to"], self.li(new)[0])


    def test_status_dropped_when_target_not_statusable(self):
        def tbl(grid):
            c = {"title": "t", "period": "p", "from": "y", "blocks": [
                {"h1": "四、關鍵決議"},
                {"table": {"grid": grid, "rows": [["a", "b", "c"], ["甲案人力補強", "同意增派 2 名木工", "10/8 進場"]]}}]}
            return anchors.build_anchors(anchors.normalize_content(c))
        old, new = tbl("decision"), tbl("topic")
        plan = publish.plan_migration(old, new)
        rows = [m for m in plan["moved"] if "/row/" in m["from"]]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["to_statusable"])

        calls = []

        class FakeSB(object):
            def rest(self, method, table, query="", body=None, prefer=None):
                calls.append((method, table, query, body))
                return []
        publish.apply_migration(FakeSB(), "rid", {"moved": rows, "orphaned": []})
        st = [c for c in calls if c[1] == "statuses"]
        self.assertTrue(any(c[0] == "DELETE" for c in st), calls)
        self.assertFalse(any(c[0] == "PATCH" for c in st), "不可指示的目的錨點不得搬入狀態")
        self.assertTrue(any(c[0] == "PATCH" and c[1] == "comments" for c in calls), "留言仍要搬")


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, raw, name="content.json"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        return p

    def listing(self):
        out = []
        for d, _, fs in os.walk(self.tmp):
            out += [os.path.join(d, f) for f in fs]
        return sorted(out)

    def test_dry_run_no_network_no_files(self):
        p = self.write(good())
        before = self.listing()
        with mock.patch("urllib.request.urlopen") as uo:
            code, out, err = run_main([p, "--dry-run", "--period", "260101-03"])
        self.assertEqual(code, 0, err)
        self.assertEqual(uo.call_count, 0)
        self.assertEqual(self.listing(), before)
        summary = json.loads(out)
        self.assertEqual(summary["period"], "260101-03")
        self.assertEqual(summary["mode"], "dry-run")
        self.assertEqual(summary["anchor_count"], len(summary["anchors"]))
        self.assertTrue(summary["status_anchors"])

    def test_dry_run_rejects_invalid(self):
        raw = good()
        raw["blocks"].append({"weird": 1})
        p = self.write(raw)
        with mock.patch("urllib.request.urlopen") as uo:
            code, out, err = run_main([p, "--dry-run"])
        self.assertNotEqual(code, 0)
        self.assertEqual(uo.call_count, 0)
        self.assertEqual(out, "")

    def test_dry_run_photo_missing_rejected_unless_skip(self):
        raw = good()
        raw["photos"] = {"D1": [["nope.jpg", "c"]]}
        p = self.write(raw)
        code, _, _ = run_main([p, "--dry-run"])
        self.assertNotEqual(code, 0)
        code, _, err = run_main([p, "--dry-run", "--skip-photos"])
        self.assertEqual(code, 0, err)

    def test_dry_run_prev_migration(self):
        old_raw = good()
        new_raw = good()
        new_raw["blocks"][6]["bullets"][0] = "追蹤一改"
        old_entries = anchors.build_anchors(anchors.normalize_content(old_raw))
        prev = self.write({"anchor_index": old_entries}, "prev.json")
        p = self.write(new_raw)
        with mock.patch("urllib.request.urlopen") as uo:
            code, out, err = run_main([p, "--dry-run", "--prev", prev])
        self.assertEqual(code, 0, err)
        self.assertEqual(uo.call_count, 0)
        mig = json.loads(out)["migration"]
        # 改一個 bullet → li 與 bullets blk 各遷移一筆
        self.assertEqual(sorted(m["from"].split("/")[1] for m in mig["moved"]), ["blk", "li"])
        self.assertEqual(mig["orphaned"], [])

    def test_folder_argument(self):
        os.makedirs(os.path.join(self.tmp, "260202-04", "_src"))
        p = os.path.join(self.tmp, "260202-04", "_src", "content.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(good(), f, ensure_ascii=False)
        code, out, err = run_main([os.path.join(self.tmp, "260202-04"), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["period"], "260202-04")

    def test_dry_run_sample(self):
        if not os.path.exists(SAMPLE):
            print("\n[skip] tests/fixtures/sample.json 不存在（render 路產出）")
            self.skipTest("tests/fixtures/sample.json 不存在")
        with mock.patch("urllib.request.urlopen") as uo:
            code, out, err = run_main([SAMPLE, "--dry-run", "--skip-photos"])
        self.assertEqual(code, 0, err)
        self.assertEqual(uo.call_count, 0)
        s = json.loads(out)
        self.assertEqual(s["anchor_count"], 44)
        self.assertEqual(len(s["status_anchors"]), 5)
        # sample 的照片檔不存在 → 不加 --skip-photos 必須拒收
        code, _, _ = run_main([SAMPLE, "--dry-run"])
        self.assertNotEqual(code, 0)

    def test_dry_run_private_fixtures(self):
        present = [p for p in PRIVATE if os.path.exists(p)]
        if not present:
            self.skipTest("私密 fixture 不存在")
        for p in present:
            with mock.patch("urllib.request.urlopen") as uo:
                code, out, err = run_main([p, "--dry-run"])
            self.assertEqual(code, 0, "私密 fixture %s dry-run 失敗" % os.path.basename(p))
            self.assertEqual(uo.call_count, 0)
            self.assertGreater(json.loads(out)["anchor_count"], 0)


class TestVectors(unittest.TestCase):
    def test_vectors_stdout_is_pure_json(self):
        if not os.path.exists(SAMPLE):
            print("\n[skip] tests/fixtures/sample.json 不存在（render 路產出）")
            self.skipTest("tests/fixtures/sample.json 不存在")
        code, out, err = run_main([SAMPLE, "--vectors"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(len(data), 44)
        with open(SAMPLE, encoding="utf-8") as f:
            self.assertEqual(data, anchors.build_anchors(anchors.normalize_content(json.load(f))))


class TestMock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mockdir = os.path.join(self.tmp, "mock")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_mock_writes_report_index_and_photos(self):
        src = os.path.join(self.tmp, "260303-05", "_src")
        os.makedirs(os.path.join(src, "img"))
        for n in ("a.jpg", "b.jpg"):
            with open(os.path.join(src, "img", n), "wb") as f:
                f.write(b"\xff\xd8\xff" + n.encode())
        os.makedirs(os.path.join(src, "img2"))
        with open(os.path.join(src, "img2", "a.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xffdup")
        raw = good()
        raw["photos"] = {"D1": [["img/a.jpg", "A"], ["img/b.jpg", "B"]]}
        raw["blocks"].append({"photos": [{"file": "img2/a.jpg", "cap": "C"}], "cols": 2})
        p = os.path.join(src, "content.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        with mock.patch("urllib.request.urlopen") as uo:
            code, out, err = run_main([p, "--mock", "--mock-dir", self.mockdir])
        self.assertEqual(code, 0, err)
        self.assertEqual(uo.call_count, 0)
        with open(os.path.join(self.mockdir, "260303-05.json"), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["report_id"], "m-260303-05")
        self.assertEqual(rep["version"], 1)
        self.assertEqual(rep["status_anchors"], anchors.status_anchors(
            anchors.build_anchors(anchors.normalize_content(raw))))
        urls = [it["url"] for b in rep["content"]["blocks"] if "photos" in b for it in b["photos"]]
        self.assertEqual(urls, ["../private/mock/photos/260303-05/a.jpg",
                                "../private/mock/photos/260303-05/b.jpg",
                                "../private/mock/photos/260303-05/a-2.jpg"])
        for b in rep["content"]["blocks"]:
            for it in b.get("photos", []):
                self.assertEqual(it["path"], it["url"])
        self.assertTrue(os.path.isfile(os.path.join(self.mockdir, "photos", "260303-05", "a-2.jpg")))
        with open(os.path.join(self.mockdir, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        self.assertEqual([r["period"] for r in idx["reports"]], ["260303-05"])

        # 重發佈：version +1、index 合併並依 period 降冪
        code, _, err = run_main([p, "--mock", "--mock-dir", self.mockdir])
        self.assertEqual(code, 0, err)
        other = copy.deepcopy(good())
        p2 = os.path.join(self.tmp, "260101-02.json")
        with open(p2, "w", encoding="utf-8") as f:
            json.dump(other, f, ensure_ascii=False)
        code, _, err = run_main([p2, "--mock", "--mock-dir", self.mockdir])
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.mockdir, "260303-05.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], 2)
        with open(os.path.join(self.mockdir, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        self.assertEqual([r["period"] for r in idx["reports"]], ["260303-05", "260101-02"])
        self.assertEqual(idx["reports"][0]["version"], 2)

    def test_mock_skip_photos_rewrites_without_copy(self):
        if not os.path.exists(SAMPLE):
            print("\n[skip] tests/fixtures/sample.json 不存在（render 路產出）")
            self.skipTest("tests/fixtures/sample.json 不存在")
        code, _, err = run_main([SAMPLE, "--mock", "--skip-photos", "--mock-dir", self.mockdir])
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.mockdir, "sample.json"), encoding="utf-8") as f:
            rep = json.load(f)
        urls = [it["url"] for b in rep["content"]["blocks"] if "photos" in b for it in b["photos"]]
        self.assertEqual(urls[0], "../private/mock/photos/sample/p1.jpg")
        self.assertEqual(len(urls), 5)
        self.assertFalse(os.path.exists(os.path.join(self.mockdir, "photos", "sample", "p1.jpg")))


class TestEnv(unittest.TestCase):
    def test_load_env(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, ".env.local")
            with open(p, "w", encoding="utf-8") as f:
                f.write('# c\nSUPABASE_URL="https://x.supabase.co/"\nSUPABASE_SERVICE_ROLE_KEY=abc\n\n')
            env = publish.load_env(p)
            self.assertEqual(env["SUPABASE_URL"], "https://x.supabase.co/")
            self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "abc")
        finally:
            shutil.rmtree(d)

    def test_formal_without_env_fails_without_network(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "x.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(good(), f, ensure_ascii=False)
            with mock.patch("urllib.request.urlopen") as uo:
                code, _, err = run_main([p, "--env-file", os.path.join(d, "missing.env")])
            self.assertNotEqual(code, 0)
            self.assertEqual(uo.call_count, 0)
        finally:
            shutil.rmtree(d)


class FakeDB(object):
    """記憶體版 PostgREST：只支援 publish_formal／apply_migration 用到的 eq 過濾。fail_at 指定第 N 次寫入時拋錯。"""

    def __init__(self):
        self.tables = {"reports": [], "comments": [], "statuses": []}
        self.writes = 0
        self.fail_at = None

    def __call__(self, url, key):
        return self

    @staticmethod
    def _filters(query):
        out = {}
        for part in (query or "").split("&"):
            if "=eq." in part:
                k, v = part.split("=eq.", 1)
                out[k] = urllib.parse.unquote(v)
        return out

    def _match(self, table, query):
        f = self._filters(query)
        return [r for r in self.tables[table] if all(str(r.get(k)) == v for k, v in f.items())]

    def rest(self, method, table, query="", body=None, prefer=None):
        if method != "GET":
            self.writes += 1
            if self.fail_at is not None and self.writes == self.fail_at:
                raise publish.PublishError("模擬網路中斷")
        if method == "GET":
            return copy.deepcopy(self._match(table, query))
        if method == "POST":
            rows = self.tables[table]
            hit = [r for r in rows if r["period"] == body["period"]]
            if hit:
                hit[0].update(copy.deepcopy(body))
                row = hit[0]
            else:
                row = dict({"id": "rep-1", "anchor_index": []}, **copy.deepcopy(body))
                rows.append(row)
            return [copy.deepcopy(row)]
        if method == "PATCH":
            for r in self._match(table, query):
                r.update(copy.deepcopy(body))
            return None
        if method == "DELETE":
            gone = self._match(table, query)
            self.tables[table] = [r for r in self.tables[table] if r not in gone]
            return None
        raise AssertionError(method)

    def upload(self, obj_path, local):
        raise AssertionError("不應上傳")

    def sign(self, obj_path):
        raise AssertionError("不應簽章")


class TestFormalAtomicity(unittest.TestCase):
    """遷移中途失敗後重跑，舊留言／狀態仍須搬到新錨點（anchor_index 不得先被覆寫）。"""

    def content(self, bullets):
        return anchors.normalize_content({"title": "t", "period": "p", "from": "y",
                                          "blocks": [{"h1": "四、關鍵決議"}, {"bullets": bullets}]})

    def li(self, entries):
        return [e["anchor"] for e in entries if e["kind"] == "li"][0]

    def run_formal(self, db, content):
        d = tempfile.mkdtemp()
        try:
            env = os.path.join(d, ".env.local")
            with open(env, "w", encoding="utf-8") as f:
                f.write("SUPABASE_URL=https://x.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=k\n")
            entries = anchors.build_anchors(content)
            with mock.patch.object(publish, "Supabase", db):
                return publish.publish_formal(content, entries, "p", [d], env), entries
        finally:
            shutil.rmtree(d)

    def test_rerun_after_midway_failure_still_migrates(self):
        db = FakeDB()
        c1 = self.content(["追蹤：甲案補漆查驗 10/8。", "追蹤：乙案缺失複驗 10/11。"])
        (_, _), e1 = self.run_formal(db, c1)
        a_old = self.li(e1)
        db.tables["comments"].append({"id": "c1", "report_id": "rep-1", "anchor": a_old, "orphaned": False})
        db.tables["statuses"].append({"report_id": "rep-1", "anchor": a_old, "reader_id": "r-1",
                                      "status": "同意", "updated_at": "2026-10-01T00:00:00+00:00"})

        c2 = self.content(["追蹤：甲案補漆查驗 10/9。", "追蹤：乙案缺失複驗 10/11。"])
        db.writes, db.fail_at = 0, 2  # 第 1 次寫入＝upsert reports 成功，第 2 次（遷移第一步）失敗
        with self.assertRaises(publish.PublishError):
            self.run_formal(db, c2)
        self.assertEqual(db.tables["reports"][0]["anchor_index"], e1, "遷移未完成前不得覆寫 anchor_index")
        self.assertEqual(db.tables["comments"][0]["anchor"], a_old)

        db.writes, db.fail_at = 0, None
        (_, migration), e2 = self.run_formal(db, c2)
        a_new = self.li(e2)
        self.assertIn({"from": a_old, "to": a_new}, [{"from": m["from"], "to": m["to"]} for m in migration["moved"]])
        self.assertEqual(db.tables["comments"][0]["anchor"], a_new)
        self.assertFalse(db.tables["comments"][0]["orphaned"])
        self.assertEqual([s["anchor"] for s in db.tables["statuses"]], [a_new])
        self.assertEqual(db.tables["reports"][0]["anchor_index"], e2)

    def test_anchor_index_written_after_all_migration_writes(self):
        db = FakeDB()
        (_, _), e1 = self.run_formal(db, self.content(["追蹤：甲案補漆查驗 10/8。"]))
        db.tables["comments"].append({"id": "c1", "report_id": "rep-1", "anchor": self.li(e1), "orphaned": False})
        log = []
        orig = db.rest

        def spy(method, table, query="", body=None, prefer=None):
            if method != "GET":
                log.append((method, table, sorted((body or {}).keys()) if isinstance(body, dict) else None))
            return orig(method, table, query, body, prefer)
        db.rest = spy
        self.run_formal(db, self.content(["追蹤：甲案補漆查驗 10/9。"]))
        idx = [i for i, x in enumerate(log) if x[2] and "anchor_index" in x[2]]
        self.assertEqual(idx, [len(log) - 1], "anchor_index 只能在最後一筆寫入：%r" % log)
        self.assertTrue(any(x[1] == "comments" for x in log))


class TestLeakScript(unittest.TestCase):
    def run_leak(self, probes_path):
        env = dict(os.environ, LEAK_PROBES=probes_path)
        return subprocess.run(["bash", LEAK], cwd=ROOT, env=env, capture_output=True, text=True)

    def test_missing_probe_file_exit0(self):
        r = self.run_leak(os.path.join(tempfile.gettempdir(), "no_such_probe_file_lwr.txt"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_dead_probe_exit2(self):
        if not os.path.isdir(os.path.join(ROOT, "private", "fixtures")):
            self.skipTest("private/fixtures 不存在")
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "probes.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("ZZ_never_in_fixture_9f8e7d\n")
            r = self.run_leak(p)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
