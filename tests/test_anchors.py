import copy
import hashlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import anchors  # noqa: E402

SAMPLE = os.path.join(ROOT, "tests", "fixtures", "sample.json")
VECTORS = os.path.join(ROOT, "tests", "anchor_vectors.json")
PRIVATE = [os.path.join(ROOT, "private", "fixtures", n) for n in ("260928-1002.json", "260921-27.json")]

# CONTRACTS §3.7：(anchor, kind, btype, bi, ri, li, statusable)
EXPECTED_44 = [
    ("s1/blk/f3bb269fce", "blk", "kicker", 0, None, None, False),
    ("s1/blk/cfe6ac6f4d", "blk", "h1", 1, None, None, False),
    ("s1/blk/b8da5c2822", "blk", "callout", 2, None, None, False),
    ("s1/blk/2ae3d27bf0", "blk", "stats", 3, None, None, False),
    ("s1/blk/884a3891d1", "blk", "cap", 4, None, None, False),
    ("s1/blk/50a5caa49b", "blk", "bars", 5, None, None, False),
    ("s1/blk/993b636521", "blk", "table", 6, None, None, False),
    ("s1/row/22233ed062", "row", "table", 6, 1, None, False),
    ("s1/row/5045ff3771", "row", "table", 6, 2, None, False),
    ("s1/row/5c65f0409f", "row", "table", 6, 3, None, False),
    ("s2/blk/d29ad4e6bf", "blk", "kicker", 7, None, None, False),
    ("s2/blk/f47a10a6f5", "blk", "h1", 8, None, None, False),
    ("s2/blk/221b395626", "blk", "table", 9, None, None, False),
    ("s2/row/20ba44cd63", "row", "table", 9, 1, None, False),
    ("s2/row/da3d0c7364", "row", "table", 9, 2, None, False),
    ("s3/blk/4020e6f5e5", "blk", "kicker", 10, None, None, False),
    ("s3/blk/efb4e41335", "blk", "h1", 11, None, None, False),
    ("s3/blk/5e160e2629", "blk", "day", 12, None, None, False),
    ("s3/blk/402a8c4d38", "blk", "table", 13, None, None, False),
    ("s3/row/1806afac91", "row", "table", 13, 1, None, False),
    ("s3/row/2cb4a95d37", "row", "table", 13, 2, None, False),
    ("s3/blk/56c49e21dd", "blk", "photos", 14, None, None, False),
    ("s3/blk/f31a726914", "blk", "day", 15, None, None, False),
    ("s3/blk/15f04f71a1", "blk", "table", 16, None, None, False),
    ("s3/row/47b7f70649", "row", "table", 16, 1, None, False),
    ("s3/row/47b7f70649-2", "row", "table", 16, 2, None, False),
    ("s3/row/8ad82fd7a7", "row", "table", 16, 3, None, False),
    ("s3/blk/063728c4b1", "blk", "photos", 17, None, None, False),
    ("s4/blk/b0a942ef66", "blk", "kicker", 18, None, None, False),
    ("s4/blk/a69bc56cda", "blk", "h1", 19, None, None, False),
    ("s4/blk/07a07f3112", "blk", "table", 20, None, None, False),
    ("s4/row/42010f0754", "row", "table", 20, 1, None, True),
    ("s4/row/ce82e02d91", "row", "table", 20, 2, None, True),
    ("s4/blk/f0367e28fc", "blk", "bullets", 21, None, None, False),
    ("s4/li/66accc3c3a", "li", "bullets", 21, None, 0, True),
    ("s4/li/df3b87b7bd", "li", "bullets", 21, None, 1, True),
    ("s4/li/66accc3c3a-2", "li", "bullets", 21, None, 2, True),
    ("s5/blk/5cd345aa56", "blk", "kicker", 22, None, None, False),
    ("s5/blk/7713a09072", "blk", "h1", 23, None, None, False),
    ("s5/blk/daf704c96e", "blk", "stats", 24, None, None, False),
    ("s5/blk/eb0d05bfe0", "blk", "table", 25, None, None, False),
    ("s5/row/4746e777c1", "row", "table", 25, 1, None, False),
    ("s5/row/baa34e642e", "row", "table", 25, 2, None, False),
    ("s5/blk/1fb6098dc5", "blk", "footnote", 26, None, None, False),
]
EXPECTED_STATUS = ["s4/row/42010f0754", "s4/row/ce82e02d91", "s4/li/66accc3c3a",
                   "s4/li/df3b87b7bd", "s4/li/66accc3c3a-2"]

# §3.6 手算範例用的最小內容（取自 CONTRACTS §8.3 的假資料片段，不依賴 sample.json）
MINI = {
    "title": "t", "period": "p", "to": "x", "from": "y",
    "photos": {"10月5日（一）": [
        ["photos/p1.jpg", "3F／候診區：天花板補漆完成"],
        ["photos/p2.jpg", "B1／機房：水泵 **更換** 中"],
        ["photos/p3.jpg", "RF／水塔：!!漏水點!! 已封"],
    ]},
    "blocks": [
        {"kicker": "Section 01 · Highlights"},
        {"h1": "一、本期重點事項", "note": "截至 10 月 7 日", "tight": True},
        {"h1": "二、專案角色與權責"},
        {"kicker": "Section 03 · Schedule"},
        {"h1": "三、行程與工作內容", "note": "10/5～10/7", "tight": True},
        {"day": "10月5日（一）"},
        {"table": {"grid": "day", "rows": [
            ["時間", "工作項目", "工作內容／預期產出"],
            ["09:00", "工地巡檢", "3F 補漆現況確認\n拍照存證"],
            ["14:00", "甲案進度會", "確認 !!落後 2 天!! 的補救方案"],
        ]}},
        {"day": "10月6日（二）"},
        {"table": {"grid": "day", "rows": [
            ["時間", "工作項目", "工作內容／預期產出"],
            ["09:00", "工地巡檢", "B1 機房泵浦更換"],
            ["09:00", "工地巡檢", "RF 水塔漏水點複查"],
        ]}},
        {"h1": "四、關鍵決議"},
        {"bullets": ["追蹤：甲案補漆查驗 10/8。", "追蹤：乙案缺失複驗 10/11。", "追蹤：甲案補漆查驗 10/8。"]},
    ],
}


def by_anchor(entries):
    return {e["anchor"]: e for e in entries}


class TestNormalizeText(unittest.TestCase):
    def test_eight_whitespace_chars_removed(self):
        s = "a b\u0009c\u000ad\u000de\u000cf\u000bg h　i"
        self.assertEqual(anchors.normalize_text(s), "abcdefghi")

    def test_other_unicode_spaces_kept(self):
        self.assertEqual(anchors.normalize_text("a b​c"), "a b​c")

    def test_markers_removed_literally(self):
        self.assertEqual(anchors.normalize_text("**甲**!!乙!! *單* !丙"), "甲乙*單*!丙")
        self.assertEqual(anchors.normalize_text("***x"), "*x")

    def test_no_width_or_case_folding(self):
        self.assertEqual(anchors.normalize_text("ＡＢab"), "ＡＢab")

    def test_non_string_raises(self):
        for bad in (None, 1, 1.5, ["a"], {"a": 1}):
            with self.assertRaises(TypeError):
                anchors.normalize_text(bad)

    def test_sha1hex(self):
        s = "h1|一、本期重點事項"
        self.assertEqual(anchors.sha1hex(s), hashlib.sha1(s.encode("utf-8")).hexdigest())
        self.assertEqual(anchors.sha1hex(s), "cfe6ac6f4d0eca44c553e4357df3b3c001d8cfa6")


class TestHandExamples(unittest.TestCase):
    """CONTRACTS §3.6：硬斷言，不可 skip。"""

    @classmethod
    def setUpClass(cls):
        content = anchors.normalize_content(MINI)
        cls.entries = anchors.build_anchors(content)
        cls.idx = by_anchor(cls.entries)

    def test_example1_h1(self):
        e = self.idx["s1/blk/cfe6ac6f4d"]
        self.assertEqual((e["kind"], e["btype"], e["bi"]), ("blk", "h1", 1))
        self.assertEqual(e["text"], "一、本期重點事項")

    def test_h1_without_kicker_increments(self):
        h1s = [e for e in self.entries if e["btype"] == "h1"]
        self.assertEqual([e["sec"] for e in h1s], ["s1", "s2", "s3", "s4"])

    def test_example2_day_row(self):
        e = self.idx["s3/row/2cb4a95d37"]
        self.assertEqual((e["kind"], e["btype"], e["ri"], e["li"]), ("row", "table", 2, None))
        self.assertEqual(e["text"], "day|10月5日（一）|14:00|甲案進度會")
        self.assertFalse(e["statusable"])

    def test_example3_duplicate_li(self):
        e1 = self.idx["s4/li/66accc3c3a"]
        e2 = self.idx["s4/li/66accc3c3a-2"]
        self.assertEqual((e1["li"], e2["li"]), (0, 2))
        self.assertTrue(e1["statusable"] and e2["statusable"])

    def test_duplicate_day_rows(self):
        self.assertEqual(self.idx["s3/row/47b7f70649"]["ri"], 1)
        self.assertEqual(self.idx["s3/row/47b7f70649-2"]["ri"], 2)

    def test_inserted_photos_block(self):
        e = self.idx["s3/blk/56c49e21dd"]
        self.assertEqual((e["btype"], e["bi"]), ("photos", 7))

    def test_dedupe_is_per_sec(self):
        c = {"title": "t", "period": "p", "from": "y", "blocks": [
            {"h1": "A"}, {"bullets": ["同"]}, {"h1": "B"}, {"bullets": ["同"]}]}
        lis = [e["anchor"] for e in anchors.build_anchors(anchors.normalize_content(c)) if e["kind"] == "li"]
        h = anchors.sha1hex("li|同")[:10]
        self.assertEqual(lis, ["s1/li/" + h, "s2/li/" + h])


class TestNormalizeContent(unittest.TestCase):
    def test_outfile_dropped_and_photos_inserted(self):
        c = anchors.normalize_content(MINI)
        self.assertEqual(sorted(c.keys()), ["blocks", "from", "period", "title", "to"])
        ins = c["blocks"][7]
        self.assertEqual(ins["day"], "10月5日（一）")
        self.assertEqual(ins["cols"], 3)
        self.assertEqual(ins["photos"][0], {"url": "photos/p1.jpg", "cap": "3F／候診區：天花板補漆完成",
                                            "path": "photos/p1.jpg"})
        self.assertIn("photos", MINI)  # 不改輸入

    def test_idempotent(self):
        once = anchors.normalize_content(MINI)
        twice = anchors.normalize_content(copy.deepcopy(once))
        self.assertEqual(once, twice)
        self.assertEqual(anchors.build_anchors(once), anchors.build_anchors(twice))

    def test_inline_photos(self):
        c = anchors.normalize_content({"title": "t", "period": "p", "from": "y", "blocks": [
            {"photos": [{"file": "a.jpg"}, {"file": "b.jpg", "cap": "B"}], "cols": 2}]})
        self.assertEqual(c["blocks"][0]["photos"], [
            {"url": "a.jpg", "cap": "", "path": "a.jpg"}, {"url": "b.jpg", "cap": "B", "path": "b.jpg"}])
        self.assertEqual(c["blocks"][0]["cols"], 2)

    def test_photos_day_not_found(self):
        raw = {"title": "t", "period": "p", "from": "y", "photos": {"X": [["a.jpg", "c"]]},
               "blocks": [{"day": "Y"}, {"table": {"grid": "agenda", "rows": [["a", "b"]]}}]}
        with self.assertRaisesRegex(ValueError, "photos day label not found: X"):
            anchors.normalize_content(raw)

    def test_no_table_after_day(self):
        raw = {"title": "t", "period": "p", "from": "y", "photos": {"X": [["a.jpg", "c"]]},
               "blocks": [{"table": {"grid": "agenda", "rows": [["a", "b"]]}}, {"day": "X"}]}
        with self.assertRaisesRegex(ValueError, "no table after day: X"):
            anchors.normalize_content(raw)


class TestStrict(unittest.TestCase):
    def base(self, blocks):
        return {"title": "t", "period": "p", "from": "y", "blocks": blocks}

    def test_unknown_block(self):
        with self.assertRaises(ValueError):
            anchors.build_anchors(self.base([{"weird": "x"}]))

    def test_two_type_keys(self):
        with self.assertRaises(ValueError):
            anchors.build_anchors(self.base([{"cap": "a", "callout": "b"}]))

    def test_column_mismatch(self):
        with self.assertRaises(ValueError):
            anchors.build_anchors(self.base([{"table": {"grid": "day", "rows": [["a", "b"]]}}]))

    def test_unknown_grid(self):
        with self.assertRaises(ValueError):
            anchors.build_anchors(self.base([{"table": {"grid": "nope", "rows": [["a"]]}}]))

    def test_non_string_field(self):
        with self.assertRaises((ValueError, TypeError)):
            anchors.build_anchors(self.base([{"bullets": ["a", 3]}]))
        with self.assertRaises((ValueError, TypeError)):
            anchors.build_anchors(self.base([{"stats": [{"v": 1}, {"v": "2"}]}]))

    def test_day_row_without_day_block(self):
        es = anchors.build_anchors(self.base([{"table": {"grid": "day", "rows": [["h", "h", "h"], ["a", "b", "c"]]}}]))
        row = [e for e in es if e["kind"] == "row"][0]
        self.assertEqual(row["text"], "day||a|b")
        self.assertEqual(row["anchor"], "s0/row/" + anchors.sha1hex("row|day||a|b")[:10])


class TestSample(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(SAMPLE):
            print("\n[skip] tests/fixtures/sample.json 不存在（render 路產出）")
            self.skipTest("tests/fixtures/sample.json 不存在")
        with open(SAMPLE, encoding="utf-8") as f:
            self.content = anchors.normalize_content(json.load(f))
        self.entries = anchors.build_anchors(self.content)

    def test_44_anchors(self):
        got = [(e["anchor"], e["kind"], e["btype"], e["bi"], e["ri"], e["li"], e["statusable"])
               for e in self.entries]
        self.assertEqual(len(got), 44)
        self.assertEqual(got, EXPECTED_44)

    def test_status_anchors(self):
        self.assertEqual(anchors.status_anchors(self.entries), EXPECTED_STATUS)

    def test_source_strings(self):
        idx = by_anchor(self.entries)
        self.assertEqual(idx["s1/blk/2ae3d27bf0"]["text"],
                         "12|項|本期事項|87|%|甲案進度|3||待決事項|1|件|新啟動專案")
        self.assertEqual(idx["s1/row/22233ed062"]["text"], "seq|1|甲案")
        self.assertEqual(idx["s2/blk/221b395626"]["text"],
                         "role|專案|參與角色|權責範圍／本期重點|甲案|PCM|進度管控品質查驗|乙案|PCM|驗收與缺失追蹤")

    def test_vectors_file(self):
        if not os.path.exists(VECTORS):
            print("\n[skip] tests/anchor_vectors.json 不存在")
            self.skipTest("tests/anchor_vectors.json 不存在")
        with open(VECTORS, encoding="utf-8") as f:
            self.assertEqual(json.load(f), self.entries)


class TestPrivateFixtures(unittest.TestCase):
    def test_private_fixtures_anchor_cleanly(self):
        present = [p for p in PRIVATE if os.path.exists(p)]
        if not present:
            self.skipTest("私密 fixture 不存在")
        for p in present:
            with open(p, encoding="utf-8") as f:
                c = anchors.normalize_content(json.load(f))
            es = anchors.build_anchors(c)
            self.assertGreater(len(es), 0, os.path.basename(p))
            self.assertEqual(len(set(e["anchor"] for e in es)), len(es), os.path.basename(p))


if __name__ == "__main__":
    unittest.main()
