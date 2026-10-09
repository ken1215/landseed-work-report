"""從 private/.env.local 組出 Session pooler 連線字串（印到 stdout 供 --db-url 使用，不寫檔）。
用法：supabase db push --db-url "$(python3 tools/dburl.py)"
"""
import os
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOLER = os.environ.get("SUPABASE_POOLER_HOST", "aws-0-ap-northeast-2.pooler.supabase.com")

env = {}
with open(os.path.join(ROOT, "private", ".env.local"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
ref = env["SUPABASE_URL"].split("//", 1)[1].split(".", 1)[0]
pw = env.get("SUPABASE_DB_PASSWORD", "")
if not pw or "<" in pw:
    sys.exit("SUPABASE_DB_PASSWORD 未填")
sys.stdout.write("postgresql://postgres.%s:%s@%s:5432/postgres" % (ref, quote(pw, safe=""), POOLER))
