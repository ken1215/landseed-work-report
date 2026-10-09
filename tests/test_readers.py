import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "tools", "readers.py")


def load_module():
    spec = importlib.util.spec_from_file_location("lwr_readers", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResp(object):
    def __init__(self, payload, status=200):
        self._data = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Recorder(object):
    """以 path 前綴回應假資料，並記錄每個 Request。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.calls.append({"method": req.get_method(), "url": url,
                           "headers": {k.lower(): v for k, v in req.header_items()},
                           "body": body})
        for (method, frag), payload in self.routes:
            if req.get_method() == method and frag in url:
                return FakeResp(payload)
        return FakeResp([])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = os.path.join(self.tmp.name, ".env.local")
        with open(self.env, "w", encoding="utf-8") as f:
            f.write("# comment\nSUPABASE_URL=\"https://demo.supabase.co\"\n"
                    "SUPABASE_SERVICE_ROLE_KEY='srv-key'\nPAGES_BASE_URL=https://ex.github.io/lwr/\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.m.main(argv + ["--env", self.env])
        return code, out.getvalue()


class Pure(Base):
    def test_token_shape(self):
        t = self.m.make_token()
        self.assertEqual(len(t), 43)
        self.assertRegex(t, r"^[A-Za-z0-9_-]{43}$")
        self.assertNotEqual(t, self.m.make_token())

    def test_token_hash_lower_hex(self):
        h = self.m.token_hash("abc")
        self.assertEqual(h, hashlib.sha256(b"abc").hexdigest())
        self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_build_link(self):
        self.assertEqual(self.m.build_link("https://a.io/x/", "T"), "https://a.io/x/index.html#k=T")
        self.assertEqual(self.m.build_link("https://a.io/x", "T"), "https://a.io/x/index.html#k=T")
        self.assertEqual(self.m.build_link("https://a.io/x/index.html", "T"), "https://a.io/x/index.html#k=T")

    def test_load_env(self):
        env = self.m.load_env(self.env)
        self.assertEqual(env["SUPABASE_URL"], "https://demo.supabase.co")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "srv-key")
        self.assertEqual(self.m.load_env(os.path.join(self.tmp.name, "nope")), {})


class DryRun(Base):
    def test_add_dry_run_no_network(self):
        with mock.patch.object(urllib.request, "urlopen") as uo:
            code, out = self.run_main(["add", "--name", "張院長", "--role", "reader",
                                       "--periods", "260928-1002", "--dry-run"])
        uo.assert_not_called()
        self.assertEqual(code, 0)
        token = re.search(r"#k=([A-Za-z0-9_-]{43})", out).group(1)
        self.assertIn(self.m.token_hash(token), out)
        self.assertIn("POST", out)
        self.assertIn("/rest/v1/readers", out)
        self.assertIn("/rest/v1/report_access", out)
        # 原始 token 只出現在連結那一行，不出現在請求內容
        lines_with_token = [ln for ln in out.splitlines() if token in ln]
        self.assertEqual(len(lines_with_token), 1)
        self.assertIn("#k=", lines_with_token[0])

    def test_dry_run_without_env(self):
        with mock.patch.object(urllib.request, "urlopen") as uo:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.m.main(["list", "--dry-run", "--env", os.path.join(self.tmp.name, "none")])
        uo.assert_not_called()
        self.assertEqual(code, 0)

    def test_revoke_and_grant_dry_run(self):
        with mock.patch.object(urllib.request, "urlopen") as uo:
            c1, o1 = self.run_main(["revoke", "--name", "張院長", "--dry-run"])
            c2, o2 = self.run_main(["grant", "--name", "張院長", "--period", "260928-1002", "--dry-run"])
        uo.assert_not_called()
        self.assertEqual((c1, c2), (0, 0))
        self.assertIn("PATCH", o1)
        self.assertIn("report_access", o2)


class Live(Base):
    def test_add_requests(self):
        rec = Recorder([
            (("POST", "/rest/v1/readers"), [{"id": "u-1", "name": "張院長", "role": "reader"}]),
            (("GET", "/rest/v1/reports"), [{"id": "rep-1", "period": "260928-1002"}]),
            (("POST", "/rest/v1/report_access"), []),
        ])
        with mock.patch.object(urllib.request, "urlopen", rec):
            code, out = self.run_main(["add", "--name", "張院長", "--role", "reader",
                                       "--periods", "260928-1002"])
        self.assertEqual(code, 0)
        token = re.search(r"https://ex\.github\.io/lwr/index\.html#k=([A-Za-z0-9_-]{43})", out).group(1)
        # 期別先驗證（GET reports）才建讀者
        self.assertEqual(rec.calls[0]["method"], "GET")
        self.assertIn("/rest/v1/reports", rec.calls[0]["url"])
        first = rec.calls[1]
        self.assertEqual(first["method"], "POST")
        self.assertEqual(first["url"], "https://demo.supabase.co/rest/v1/readers")
        self.assertEqual(first["headers"]["apikey"], "srv-key")
        self.assertEqual(first["headers"]["authorization"], "Bearer srv-key")
        self.assertEqual(first["body"], {"name": "張院長", "role": "reader",
                                         "token_sha256": self.m.token_hash(token)})
        for c in rec.calls:
            self.assertNotIn(token, json.dumps(c, ensure_ascii=False))
        acc = [c for c in rec.calls if "report_access" in c["url"]][0]
        self.assertEqual(acc["body"], [{"report_id": "rep-1", "reader_id": "u-1"}])
        self.assertIn("resolution=ignore-duplicates", acc["headers"]["prefer"])

    def test_add_unknown_period_creates_no_reader(self):
        rec = Recorder([
            (("POST", "/rest/v1/readers"), [{"id": "u-1", "name": "張院長", "role": "reader"}]),
            (("GET", "/rest/v1/reports"), []),
        ])
        with mock.patch.object(urllib.request, "urlopen", rec):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code, _ = self.run_main(["add", "--name", "張院長", "--role", "reader",
                                         "--periods", "999999-99"])
        self.assertNotEqual(code, 0)
        self.assertIn("999999-99", err.getvalue())
        self.assertFalse([c for c in rec.calls if c["method"] == "POST"], "期別不存在時不得建立讀者")

    def test_add_grant_failure_still_reveals_reader_and_link(self):
        rec = Recorder([
            (("POST", "/rest/v1/readers"), [{"id": "u-9", "name": "乙", "role": "reader"}]),
            (("GET", "/rest/v1/reports"), [{"id": "rep-1", "period": "260928-1002"}]),
        ])

        def router(req, timeout=None):
            if req.get_method() == "POST" and "report_access" in req.full_url:
                rec.calls.append({"method": "POST", "url": req.full_url})
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b"db down"))
            return rec(req, timeout)
        with mock.patch.object(urllib.request, "urlopen", router):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code, out = self.run_main(["add", "--name", "乙", "--role", "reader",
                                           "--periods", "260928-1002"])
        self.assertNotEqual(code, 0)
        token = re.search(r"#k=([A-Za-z0-9_-]{43})", out).group(1)
        post = [c for c in rec.calls if c["url"].endswith("/rest/v1/readers")][0]
        self.assertEqual(post["body"]["token_sha256"], self.m.token_hash(token))
        self.assertIn("u-9", out + err.getvalue())
        self.assertIn("u-9", err.getvalue())

    def test_revoke_patches_single_reader(self):
        rec = Recorder([
            (("GET", "/rest/v1/readers"), [{"id": "u-1", "name": "張院長"}]),
            (("PATCH", "/rest/v1/readers"), [{"id": "u-1", "active": False}]),
        ])
        with mock.patch.object(urllib.request, "urlopen", rec):
            code, _ = self.run_main(["revoke", "--name", "張院長"])
        self.assertEqual(code, 0)
        patch = [c for c in rec.calls if c["method"] == "PATCH"][0]
        self.assertTrue(patch["url"].endswith("/rest/v1/readers?id=eq.u-1"))
        self.assertEqual(patch["body"], {"active": False})

    def test_revoke_ambiguous_name_refuses(self):
        rec = Recorder([(("GET", "/rest/v1/readers"), [{"id": "a", "name": "X"}, {"id": "b", "name": "X"}])])
        with mock.patch.object(urllib.request, "urlopen", rec):
            code, _ = self.run_main(["revoke", "--name", "X"])
        self.assertNotEqual(code, 0)
        self.assertFalse([c for c in rec.calls if c["method"] == "PATCH"])

    def test_missing_env_refuses_without_network(self):
        with mock.patch.object(urllib.request, "urlopen") as uo:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = self.m.main(["list", "--env", os.path.join(self.tmp.name, "none")])
        uo.assert_not_called()
        self.assertNotEqual(code, 0)

    def test_bad_role_rejected(self):
        with mock.patch.object(urllib.request, "urlopen") as uo:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.run_main(["add", "--name", "x", "--role", "admin", "--dry-run"])
        uo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
