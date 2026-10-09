#!/usr/bin/env python3
"""讀者管理（service_role 直連 PostgREST，本機用）。

  python3 tools/readers.py add    --name 張院長 --role reader [--periods 260928-1002,260921-27]
  python3 tools/readers.py revoke --name 張院長
  python3 tools/readers.py grant  --name 張院長 --period 260928-1002
  python3 tools/readers.py list

共用旗標：--dry-run（不連網，只印將送出的請求）、--env（預設 private/.env.local）、--base-url。
.env.local 需 SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY；PAGES_BASE_URL（可選，個人連結的網站根）。
DB 只存 token 的 sha256 小寫 hex；明文 token 只在 add 當下印一次，遺失只能撤銷後重建。
帳號未開前正式路徑未實跑（只有 --dry-run 與假 urlopen 的單元測試）。
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV = os.path.join(ROOT, "private", ".env.local")
PLACEHOLDER_URL = "https://<project>.supabase.co"
PLACEHOLDER_BASE = "https://<pages-host>/"


def make_token():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_link(base, token):
    base = base.strip()
    if not base.endswith("index.html"):
        base = base.rstrip("/") + "/index.html"
    return base + "#k=" + token


def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k.strip()] = v
    return env


class CliError(Exception):
    pass


class Client(object):
    def __init__(self, url, key, dry_run=False, out=None):
        self.url = url.rstrip("/")
        self.key = key
        self.dry_run = dry_run
        self.out = out or sys.stdout

    def request(self, method, path, body=None, prefer=None, dry_result=None):
        full = self.url + "/rest/v1/" + path
        if self.dry_run:
            line = "[dry-run] %s %s" % (method, full)
            if body is not None:
                line += " " + json.dumps(body, ensure_ascii=False)
            print(line, file=self.out)
            return dry_result
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(full, data=data, method=method)
        req.add_header("apikey", self.key)
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("Prefer", prefer or "return=representation")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise CliError("HTTP %s %s %s：%s" % (e.code, method, path, detail))
        except urllib.error.URLError as e:
            raise CliError("連線失敗 %s：%s" % (full, e.reason))
        return json.loads(raw.decode("utf-8")) if raw else None


def q(value):
    return urllib.parse.quote(value, safe="")


def find_reader(cli, name):
    rows = cli.request("GET", "readers?select=id,name,role,active&name=eq." + q(name),
                       dry_result=[{"id": "<reader-id>", "name": name}])
    if not rows:
        raise CliError("找不到讀者：" + name)
    if len(rows) > 1:
        raise CliError("同名讀者 %d 位，拒絕操作（請先在 DB 改名區分）：%s" % (len(rows), name))
    return rows[0]


def find_report(cli, period):
    rows = cli.request("GET", "reports?select=id,period&period=eq." + q(period),
                       dry_result=[{"id": "<report-id:%s>" % period, "period": period}])
    if not rows:
        raise CliError("找不到期別（請先 publish）：" + period)
    return rows[0]


def grant_report(cli, reader_id, rep):
    cli.request("POST", "report_access?on_conflict=report_id,reader_id",
                [{"report_id": rep["id"], "reader_id": reader_id}],
                prefer="resolution=ignore-duplicates,return=minimal")
    print("已授權 %s" % rep["period"])


def grant(cli, reader_id, period):
    grant_report(cli, reader_id, find_report(cli, period))


def cmd_add(cli, args, base):
    # 期別先驗完才建讀者，避免留下拿不到連結的讀者列
    reps = [find_report(cli, p) for p in [x.strip() for x in (args.periods or "").split(",") if x.strip()]]
    token = make_token()
    body = {"name": args.name, "role": args.role, "token_sha256": token_hash(token)}
    rows = cli.request("POST", "readers", body,
                       dry_result=[{"id": "<reader-id>", "name": args.name, "role": args.role}])
    reader = rows[0] if isinstance(rows, list) else rows
    failed = None
    for rep in reps:
        try:
            grant_report(cli, reader["id"], rep)
        except CliError as e:
            failed = "讀者已建立（id=%s），但授權 %s 失敗：%s；連結仍有效，請稍後用 grant 補授權" % (
                reader["id"], rep["period"], e)
            break
    print("讀者：%s（%s）id=%s" % (args.name, args.role, reader["id"]))
    print("token_sha256=%s" % body["token_sha256"])
    note = "（dry-run，未寫入 DB，此連結無效）" if cli.dry_run else "（只顯示這一次，請直接轉交本人）"
    print("個人連結%s：" % note)
    print(build_link(base, token))
    if failed:
        raise CliError(failed)
    return 0


def cmd_revoke(cli, args, base):
    r = find_reader(cli, args.name)
    cli.request("PATCH", "readers?id=eq." + q(r["id"]), {"active": False},
                prefer="return=minimal")
    print("已撤銷：%s（id=%s）" % (args.name, r["id"]))
    return 0


def cmd_grant(cli, args, base):
    r = find_reader(cli, args.name)
    grant(cli, r["id"], args.period)
    return 0


def cmd_list(cli, args, base):
    rows = cli.request("GET", "readers?select=id,name,role,active,created_at&order=created_at",
                       dry_result=[])
    for r in rows or []:
        print("%s\t%s\t%s\t%s" % (r["name"], r["role"], "active" if r["active"] else "revoked", r["id"]))
    return 0


def parse_args(argv):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="不連網，只印將送出的請求")
    common.add_argument("--env", default=DEFAULT_ENV, help="環境檔（預設 private/.env.local）")
    common.add_argument("--base-url", default=None, help="網站根，覆寫 PAGES_BASE_URL")

    ap = argparse.ArgumentParser(description="林踐宇工作報告：讀者管理")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    a = sub.add_parser("add", parents=[common])
    a.add_argument("--name", required=True)
    a.add_argument("--role", required=True, choices=["author", "reader"])
    a.add_argument("--periods", default="", help="逗號分隔的期別，建立後一併授權")
    r = sub.add_parser("revoke", parents=[common])
    r.add_argument("--name", required=True)
    g = sub.add_parser("grant", parents=[common])
    g.add_argument("--name", required=True)
    g.add_argument("--period", required=True)
    sub.add_parser("list", parents=[common])
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    env = load_env(args.env)
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    base = args.base_url or env.get("PAGES_BASE_URL") or PLACEHOLDER_BASE
    if not args.dry_run and (not url or not key):
        print("缺 SUPABASE_URL／SUPABASE_SERVICE_ROLE_KEY（%s）；帳號未開請用 --dry-run" % args.env,
              file=sys.stderr)
        return 2
    cli = Client(url or PLACEHOLDER_URL, key or "<service-role-key>", dry_run=args.dry_run)
    handlers = {"add": cmd_add, "revoke": cmd_revoke, "grant": cmd_grant, "list": cmd_list}
    try:
        return handlers[args.cmd](cli, args, base)
    except CliError as e:
        print("錯誤：%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
