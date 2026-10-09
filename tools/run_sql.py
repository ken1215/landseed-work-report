"""以 simple query protocol 執行整份 SQL 檔（可含多個 do $$ 區塊），印出 NOTICE。
用法：private/.venv/bin/python tools/run_sql.py supabase/tests/access.sql
連線資訊取自 tools/dburl.py（private/.env.local）。
"""
import os
import subprocess
import sys
from urllib.parse import unquote, urlparse

import pg8000.native

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
url = urlparse(subprocess.check_output([sys.executable, os.path.join(ROOT, "tools", "dburl.py")], text=True))
con = pg8000.native.Connection(user=unquote(url.username), password=unquote(url.password),
                               host=url.hostname, port=url.port or 5432, database=url.path.lstrip("/"),
                               ssl_context=True)
sql = open(sys.argv[1], encoding="utf-8").read()
try:
    con.run(sql)
    status = 0
except pg8000.native.DatabaseError as e:
    print("SQL ERROR:", e.args[0] if e.args else e)
    status = 1
for n in con.notices:
    print("NOTICE:", (n.get(b"M") or n.get("M") or b"").decode() if isinstance(n.get(b"M"), bytes) else n)
con.close()
sys.exit(status)
