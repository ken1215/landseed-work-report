#!/usr/bin/env bash
# 洩漏探針，三道檢查：
#  1. 手動探針：private/leak_probes.txt 每行一個 fixture 專屬字串（# 開頭與空行略過；檔案不存在只警告）。
#  2. 自動探針：從 private/fixtures/*.json 自動挑 5 個 ≧4 字的專有片段（排除公開假資料 sample.json／CONTRACTS.md 已有者）。
#  3. web/ 不得出現 service_role、sb_secret。
# 探針掃 web/ 與 git ls-files -co --exclude-standard，須 0 筆。
# 陽性對照：每個探針在 private/fixtures/ 須 ≧ 1 筆，否則「探針失效」。
# 輸出只印探針編號，不印探針字串本身。exit：0 乾淨／1 命中／2 探針失效。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROBES="${LEAK_PROBES:-$ROOT/private/leak_probes.txt}"
FIXTURES="$ROOT/private/fixtures"
AUTO_N=5
cd "$ROOT" || exit 2

LIST="$(mktemp)"; AUTO="$(mktemp)"
trap 'rm -f "$LIST" "$AUTO"' EXIT
{
  if [ -d web ]; then find web -type f; fi
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -c core.quotepath=off ls-files -co --exclude-standard
  else
    find . -type f -not -path './.git/*' -not -path './private/*' -not -path './node_modules/*' | sed 's#^\./##'
  fi
} | sort -u > "$LIST"
NFILES=$(wc -l < "$LIST" | tr -d ' ')

probes=0; hits=0; dead=0

# $1=探針檔 $2=標籤
scan_probes() {
  local file="$1" label="$2" n=0 probe f
  while IFS= read -r probe || [ -n "$probe" ]; do
    n=$((n + 1))
    probe="${probe%$'\r'}"
    case "$probe" in ''|'#'*) continue ;; esac
    probes=$((probes + 1))
    if ! grep -rqF -- "$probe" "$FIXTURES" 2>/dev/null; then
      echo "[check_leak] 探針失效：${label}第 $n 個在 private/fixtures/ 找不到"
      dead=$((dead + 1))
      continue
    fi
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      if grep -qF -- "$probe" "$f"; then
        echo "[check_leak] 命中：${label}第 $n 個 → $f"
        hits=$((hits + 1))
      fi
    done < "$LIST"
  done < "$file"
}

# 1. 手動探針
if [ -f "$PROBES" ]; then
  scan_probes "$PROBES" "手動探針"
else
  echo "[check_leak] 警告：手動探針檔不存在（${PROBES}），略過此項。"
fi

# 2. 自動探針
if [ -d "$FIXTURES" ] && ls "$FIXTURES"/*.json >/dev/null 2>&1; then
  python3 -I - "$FIXTURES" "$ROOT/tests/fixtures/sample.json" "$ROOT/docs/CONTRACTS.md" "$AUTO_N" > "$AUTO" <<'PY'
import glob, json, os, re, sys
fx_dir, sample, contracts, want = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
baseline = ""
for p in (sample, contracts):
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            baseline += f.read()

def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for v in x:
            for s in strings(v):
                yield s
    elif isinstance(x, dict):
        for k, v in x.items():
            if k in ("outfile", "file", "url", "path"):
                continue
            for s in strings(v):
                yield s

# 地點／設施類字尾最具專屬性
KEYS = set("室梯院診館樓號棟區廳房櫃站")
RUN = re.compile(r"[㐀-鿿A-Za-z0-9]{4,}")
cands = set()
for p in sorted(glob.glob(os.path.join(fx_dir, "*.json"))):
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    for s in strings(data):
        s = s.replace("**", "").replace("!!", "")
        for m in RUN.findall(s):
            for i in range(0, max(1, len(m) - 7)):
                frag = m[i:i + 8] if len(m) > 8 else m
                if frag not in baseline:
                    cands.add(frag)

def score(t):
    return (any(c in KEYS for c in t), any(c.isdigit() for c in t), len(t))

picked = []
for t in sorted(cands, key=lambda t: (tuple(-int(v) for v in score(t)), t)):
    if any(t in p or p in t for p in picked):
        continue
    picked.append(t)
    if len(picked) == want:
        break
sys.stdout.write("".join(p + "\n" for p in picked))
PY
  na=$(grep -c . "$AUTO" | tr -d ' ')
  if [ "$na" -lt "$AUTO_N" ]; then
    echo "[check_leak] 探針失效：自動探針只挑到 $na 個（需要 $AUTO_N 個）"
    dead=$((dead + 1))
  fi
  scan_probes "$AUTO" "自動探針"
else
  echo "[check_leak] 警告：private/fixtures/ 不存在或沒有 json，略過自動探針。"
fi

# 3. 金鑰字樣
keyhits=0
if [ -d web ]; then
  while IFS= read -r f; do
    echo "[check_leak] 命中：web/ 出現金鑰字樣 → $f"
    keyhits=$((keyhits + 1))
  done < <(grep -rIl -e service_role -e sb_secret web 2>/dev/null)
fi
hits=$((hits + keyhits))

# 4. 實際密鑰值（service_role key、DB 密碼）不得出現在任何會進 git 的檔
if [ -f private/.env.local ]; then
  for k in SUPABASE_SERVICE_ROLE_KEY SUPABASE_DB_PASSWORD; do
    v=$(grep "^$k=" private/.env.local | cut -d= -f2-)
    [ ${#v} -ge 8 ] || continue
    while IFS= read -r f; do
      [ -f "$f" ] && grep -qF -- "$v" "$f" && { echo "[check_leak] 命中：$k 的值出現在 $f"; hits=$((hits + 1)); }
    done < "$LIST"
  done
fi

echo "[check_leak] 探針 $probes 個、掃描檔案 $NFILES 個、命中 $hits 筆、失效 $dead 個"
if [ "$dead" -gt 0 ]; then echo "[check_leak] 探針失效"; exit 2; fi
if [ "$hits" -gt 0 ]; then exit 1; fi
if [ "$probes" -eq 0 ]; then echo "[check_leak] 警告：沒有任何有效探針，只做了金鑰字樣檢查"; exit 0; fi
echo "[check_leak] OK：0 筆洩漏"
exit 0
