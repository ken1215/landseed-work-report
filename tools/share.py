"""報告分享連結（單向、免登入）：每期一把金鑰，網址 <站>/index.html#s=<key>。

用法：
  python3 tools/share.py link  --period 261003-1009            # 印出連結；尚未建立則建立
  python3 tools/share.py link  --period 261003-1009 --rotate   # 換新金鑰（舊連結立即失效）
  python3 tools/share.py opens --period 261003-1009            # 查開啟紀錄（何時被打開）
金鑰明文只存本機 private/share_links.json（不進 git），資料庫只存 SHA-256。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from readers import (CliError, Client, DEFAULT_ENV, ROOT, find_report, load_env,  # noqa: E402
                     make_token, q, token_hash)

STORE = os.path.join(ROOT, "private", "share_links.json")


def load_store():
    if not os.path.exists(STORE):
        return {}
    with open(STORE, encoding="utf-8") as f:
        return json.load(f)


def save_store(data):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def share_url(base, key):
    base = base.strip()
    if not base.endswith("index.html"):
        base = base.rstrip("/") + "/index.html"
    return base + "#s=" + key


def cmd_link(cli, args, base):
    rep = find_report(cli, args.period)
    store = load_store()
    key = None if args.rotate else store.get(args.period)
    if key:
        rows = cli.request("GET", "reports?select=share_key_sha256&id=eq." + q(rep["id"]),
                           dry_result=[{"share_key_sha256": token_hash(key)}])
        if not rows or rows[0].get("share_key_sha256") != token_hash(key):
            key = None  # 本機記錄與資料庫不符（被換過或從未寫入），重建
    if not key:
        key = make_token()
        cli.request("PATCH", "reports?id=eq." + q(rep["id"]), {"share_key_sha256": token_hash(key)},
                    prefer="return=minimal")
        if not cli.dry_run:
            store[args.period] = key
            save_store(store)
        print("已建立新金鑰" + ("（舊連結已失效）" if args.rotate else ""))
    print("%s 分享連結：" % args.period)
    print(share_url(base, key))


def cmd_opens(cli, args, base):
    rep = find_report(cli, args.period)
    rows = cli.request("GET", "share_opens?select=opened_at&order=opened_at.desc&limit=50&report_id=eq." + q(rep["id"]),
                       dry_result=[]) or []
    print("%s 開啟紀錄（最近 %d 筆，UTC）：" % (args.period, len(rows)))
    for r in rows:
        print("  " + r["opened_at"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="報告分享連結（單向、免登入）")
    ap.add_argument("--env", default=DEFAULT_ENV)
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("link")
    a.add_argument("--period", required=True)
    a.add_argument("--rotate", action="store_true")
    o = sub.add_parser("opens")
    o.add_argument("--period", required=True)
    args = ap.parse_args(argv)
    env = load_env(args.env)
    url, key = env.get("SUPABASE_URL", ""), env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not args.dry_run and (not url or not key):
        sys.exit("private/.env.local 缺 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY")
    cli = Client(url or "https://<project>.supabase.co", key, dry_run=args.dry_run)
    base = env.get("PAGES_BASE_URL") or "https://<pages-host>/"
    try:
        {"link": cmd_link, "opens": cmd_opens}[args.cmd](cli, args, base)
    except CliError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
