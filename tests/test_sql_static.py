"""SQL 靜態自檢（本機無 docker/psql，SQL 未實測；此測試只檢查文字結構）。"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIG = os.path.join(ROOT, "supabase", "migrations")
FILES = ["0001_schema.sql", "0002_rpc.sql", "0003_notifications.sql"]
ACCESS = os.path.join(ROOT, "supabase", "tests", "access.sql")

# CONTRACTS §5.2：名稱與參數名逐字
RPC_PARAMS = {
    "rp_whoami": ["p_token"],
    "rp_list_reports": ["p_token"],
    "rp_get_report": ["p_token", "p_period"],
    "rp_mark_read": ["p_token", "p_report_id"],
    "rp_list_comments": ["p_token", "p_report_id", "p_since"],
    "rp_add_comment": ["p_token", "p_report_id", "p_anchor", "p_body", "p_parent_id"],
    "rp_edit_comment": ["p_token", "p_comment_id", "p_body"],
    "rp_delete_comment": ["p_token", "p_comment_id"],
    "rp_set_status": ["p_token", "p_report_id", "p_anchor", "p_status"],
    "rp_mark_seen": ["p_token", "p_report_id"],
}
# CONTRACTS §5.3
RAISE_STRINGS = {
    "invalid token", "forbidden", "not found", "anchor not statusable",
    "invalid status", "body too long", "body empty", "reply depth",
}
TABLES = {"readers", "reports", "report_access", "comments", "reads",
          "statuses", "seen", "notifications"}


def strip_comments(sql):
    return re.sub(r"--[^\n]*", "", sql)


def load(name):
    with open(os.path.join(MIG, name), encoding="utf-8") as f:
        return f.read()


def all_sql():
    return "\n".join(strip_comments(load(n)) for n in FILES)


FUNC_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+(?:public\.)?(\w+)\s*\((.*?)\)\s*"
    r"(returns\s.*?)\bas\s+\$(\w*)\$(.*?)\$\4\$(.*?);",
    re.I | re.S,
)


def functions(sql):
    out = []
    for m in FUNC_RE.finditer(sql):
        out.append({
            "name": m.group(1).lower(),
            "args": m.group(2),
            "header": m.group(3) + " " + m.group(6),
            "body": m.group(5),
        })
    return out


def param_names(args):
    names = []
    for part in re.split(r",(?![^()]*\))", args):
        part = part.strip()
        if part:
            names.append(part.split()[0].lower())
    return names


class SqlFilesExist(unittest.TestCase):
    def test_files_exist_and_marked_untested(self):
        for n in FILES:
            p = os.path.join(MIG, n)
            self.assertTrue(os.path.exists(p), p)
            self.assertIn("未實測", load(n)[:600], n + " 檔頭需標「未實測」")
        self.assertTrue(os.path.exists(ACCESS))
        with open(ACCESS, encoding="utf-8") as f:
            self.assertIn("未實測", f.read()[:600])


class SqlStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = all_sql()
        cls.funcs = functions(cls.sql)

    def test_tables_exact_and_rls_enabled(self):
        created = set(m.lower() for m in re.findall(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)", self.sql, re.I))
        self.assertEqual(created, TABLES)
        for t in created:
            self.assertRegex(
                self.sql,
                r"(?i)alter\s+table\s+(?:public\.)?%s\s+enable\s+row\s+level\s+security" % t,
                t + " 未 enable RLS")

    def test_no_force_rls(self):
        self.assertNotRegex(self.sql, r"(?i)force\s+row\s+level\s+security")

    def test_no_policies_at_all(self):
        # 沒有 to 子句的 policy 預設套用 PUBLIC，因此一律禁止任何 policy
        self.assertNotRegex(self.sql, r"(?i)create\s+policy")

    def test_rpc_set_exact(self):
        rp = {f["name"] for f in self.funcs if f["name"].startswith("rp_")}
        self.assertEqual(rp, set(RPC_PARAMS))

    def test_rpc_params_and_returns(self):
        for f in self.funcs:
            if not f["name"].startswith("rp_"):
                continue
            self.assertEqual(param_names(f["args"]), RPC_PARAMS[f["name"]], f["name"])
            self.assertRegex(f["header"], r"(?i)^returns\s+jsonb\b", f["name"])

    def test_p_since_default_null(self):
        f = [x for x in self.funcs if x["name"] == "rp_list_comments"][0]
        self.assertRegex(f["args"], r"(?i)p_since\s+timestamptz\s+default\s+null")

    def test_rpc_security_definer_search_path(self):
        for f in self.funcs:
            if f["name"].startswith("rp_"):
                self.assertRegex(f["header"], r"(?i)security\s+definer", f["name"])
        for f in self.funcs:
            if re.search(r"(?i)security\s+definer", f["header"]):
                self.assertRegex(
                    f["header"], r"(?i)set\s+search_path\s*=\s*public\s*,\s*extensions",
                    f["name"] + " 缺 set search_path")

    def test_rpc_grant_to_anon(self):
        for name in RPC_PARAMS:
            self.assertRegex(
                self.sql,
                r"(?is)grant\s+execute\s+on\s+function\s+(?:public\.)?%s\s*\([^;]*?\)\s+to\s+[^;]*\banon\b" % name,
                name + " 未 grant execute to anon")
            self.assertRegex(
                self.sql,
                r"(?is)revoke\s+(?:all|execute)\s+on\s+function\s+(?:public\.)?%s\s*\([^;]*?\)\s+from\s+public" % name,
                name + " 未先 revoke from public")

    def test_helpers_not_executable_by_anon(self):
        for f in self.funcs:
            if f["name"].startswith("rp_"):
                continue
            self.assertRegex(
                self.sql,
                r"(?is)revoke\s+(?:all|execute)\s+on\s+function\s+(?:public\.)?%s\s*\([^;]*?\)\s+from\s+public" % f["name"],
                f["name"] + " 需 revoke from public")
            self.assertNotRegex(
                self.sql,
                r"(?is)grant\s+execute\s+on\s+function\s+(?:public\.)?%s\s*\([^;]*?\)\s+to\s+[^;]*\banon\b" % f["name"],
                f["name"] + " helper 不得給 anon")

    def test_raise_strings_in_contract(self):
        found = re.findall(r"(?i)raise\s+exception\s+'([^']*)'", self.sql)
        self.assertTrue(found)
        for s in found:
            self.assertIn(s, RAISE_STRINGS)
        self.assertEqual(set(found), RAISE_STRINGS, "§5.3 每個字串都應被使用")

    def test_token_hash_check(self):
        self.assertRegex(self.sql, r"(?i)encode\(\s*(?:extensions\.)?digest\(\s*p_token\s*,\s*'sha256'\s*\)\s*,\s*'hex'\s*\)")
        self.assertRegex(self.sql, r"(?i)create\s+extension\s+if\s+not\s+exists\s+pgcrypto")

    def test_reports_columns(self):
        m = re.search(r"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?reports\s*\((.*?)\n\);", self.sql)
        self.assertIsNotNone(m)
        cols = m.group(1)
        self.assertRegex(cols, r"(?i)status_anchors\s+text\[\]\s+not\s+null\s+default\s+'\{\}'")
        self.assertRegex(cols, r"(?i)anchor_index\s+jsonb\s+not\s+null\s+default\s+'\[\]'")
        self.assertRegex(cols, r"(?i)version\s+int(?:eger)?\s+not\s+null\s+default\s+1")
        self.assertRegex(cols, r"(?i)period\s+text\s+not\s+null\s+unique")

    def test_body_check_allows_soft_delete(self):
        self.assertRegex(self.sql, r"(?i)check\s*\(\s*deleted\s+or\s+char_length\(\s*body\s*\)\s+between\s+1\s+and\s+2000\s*\)")

    def test_status_values(self):
        self.assertIn("'同意'", self.sql)
        self.assertIn("'再議'", self.sql)
        self.assertIn("'請補資料'", self.sql)

    def test_notifications_trigger(self):
        sql = strip_comments(load("0003_notifications.sql"))
        self.assertRegex(sql, r"(?is)create\s+trigger\s+\w+\s+after\s+insert\s+on\s+(?:public\.)?comments")

    def test_access_sql_has_8_tests_in_rollback(self):
        with open(ACCESS, encoding="utf-8") as f:
            a = f.read()
        ids = set(re.findall(r"TEST\s+(\d+)\s+OK", a))
        self.assertGreaterEqual(len(ids), 8)
        self.assertRegex(a.strip(), r"(?i)rollback;\s*$")
        self.assertRegex(a, r"(?im)^begin;")


    def test_reply_inherits_parent_anchor(self):
        with open(os.path.join(MIG, "0002_rpc.sql"), encoding="utf-8") as f:
            self.assertIn("p_anchor := par.anchor;", f.read())

    def test_access_sql_uuid_casts(self):
        with open(ACCESS, encoding="utf-8") as f:
            a = f.read()
        # format(... %L ...) 內的字面值會自動轉型；直接當參數傳的 text 不會
        bare = [l for l in a.splitlines()
                if re.search(r"public\.rp_\w+\(", l) and "format(" not in l
                and re.search(r"[a-z]->>'id'\)(?!::uuid)", l)]
        self.assertEqual(bare, [])


if __name__ == "__main__":
    unittest.main()
