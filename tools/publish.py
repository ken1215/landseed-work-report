"""期間資料夾 / content.json → 驗證 → 正規化 → 錨點 → 照片上傳 → upsert reports → 錨點遷移。

python3 tools/publish.py <content.json 或期間資料夾> [--mock] [--dry-run] [--vectors]
                         [--skip-photos] [--prev FILE] [--period ID]

正式模式（無 --mock/--dry-run/--vectors）走 Supabase REST，帳號未開，**未實測**。
"""
import argparse
import datetime
import difflib
import json
import mimetypes
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import anchors  # noqa: E402

BUCKET = "report-photos"
SIGN_EXPIRES = 315360000  # 10 年
MIGRATE_RATIO = 0.6
DEFAULT_ENV = os.path.join(ROOT, "private", ".env.local")
DEFAULT_MOCK_DIR = os.path.join(ROOT, "private", "mock")
BAR_COLORS = ("blue", "navy", "green", "grey", "red")


class PublishError(Exception):
    pass


# ---------- 輸入 ----------

def resolve_input(path):
    """回傳 (content.json 路徑, 照片相對路徑的基準資料夾清單)。"""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        for cand in (os.path.join(path, "_src", "content.json"), os.path.join(path, "content.json")):
            if os.path.isfile(cand):
                return cand, _bases(cand)
        raise PublishError("資料夾內找不到 _src/content.json：%s" % path)
    if not os.path.isfile(path):
        raise PublishError("找不到檔案：%s" % path)
    return path, _bases(path)


def _bases(content_path):
    d = os.path.dirname(content_path)
    out = [d]
    if os.path.basename(d) == "_src":
        out.append(os.path.dirname(d))
    return out


def derive_period(content_path):
    """content.json → 所在資料夾名（_src 則再上一層）；其他檔名 → 檔名 stem。"""
    d = os.path.dirname(os.path.abspath(content_path))
    if os.path.basename(content_path) == "content.json":
        if os.path.basename(d) == "_src":
            d = os.path.dirname(d)
        return os.path.basename(d)
    return os.path.splitext(os.path.basename(content_path))[0]


def find_photo(p, base_dirs):
    if os.path.isabs(p):
        return p if os.path.isfile(p) else None
    for b in base_dirs:
        cand = os.path.join(b, p)
        if os.path.isfile(cand):
            return cand
    return None


# ---------- 驗證（CONTRACTS §6.1 拒收條件） ----------

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(raw, base_dirs, check_photos=True):
    errs = []
    if not isinstance(raw, dict):
        return ["頂層不是物件"]
    for k in ("title", "period", "from"):
        if not isinstance(raw.get(k), str) or not raw.get(k).strip():
            errs.append("缺少或非字串：%s" % k)
    blocks = raw.get("blocks")
    if not isinstance(blocks, list):
        return errs + ["blocks 必須是陣列"]
    for bi, b in enumerate(blocks):
        t = anchors.block_type(b)
        if t is None:
            keys = sorted(b.keys()) if isinstance(b, dict) else type(b).__name__
            errs.append("未知區塊 bi=%d keys=%s" % (bi, keys))
            continue
        v = b[t]
        if t == "stats":
            if not isinstance(v, list) or not 2 <= len(v) <= 4:
                errs.append("stats bi=%d 需 2～4 張，目前 %s" % (bi, len(v) if isinstance(v, list) else "?"))
            elif any(not isinstance(it, dict) or not isinstance(it.get("v"), str) for it in v):
                errs.append("stats bi=%d 的 v 必須是字串" % bi)
        elif t == "bars":
            if not isinstance(v, list):
                errs.append("bars bi=%d 不是陣列" % bi)
                continue
            for k, r in enumerate(v):
                if not isinstance(r, list) or len(r) < 3:
                    errs.append("bars bi=%d 第 %d 列少於 3 個元素" % (bi, k))
                elif not _is_num(r[2]):
                    errs.append("bars bi=%d 第 %d 列 pct 不是數字" % (bi, k))
                elif len(r) > 3 and r[3] not in BAR_COLORS:
                    print("[publish] 警告：bars bi=%d 第 %d 列顏色 %r 不在 %s" % (bi, k, r[3], BAR_COLORS),
                          file=sys.stderr)
    if errs:
        return errs
    try:
        content = anchors.normalize_content(raw)
        anchors.build_anchors(content)
    except (ValueError, TypeError) as e:
        return [str(e)]
    if check_photos:
        for it in iter_photo_items(content):
            if find_photo(it["path"], base_dirs) is None:
                errs.append("照片檔不存在：%s" % it["path"])
    return errs


def iter_photo_items(content):
    for b in content["blocks"]:
        if anchors.block_type(b) == "photos":
            for it in b["photos"]:
                yield it


# ---------- 遷移（CONTRACTS §3.9） ----------

def plan_migration(old_entries, new_entries):
    new_set = set(e["anchor"] for e in new_entries)
    old_set = set(e["anchor"] for e in old_entries)
    used = set()
    kept, moved, orphaned = [], [], []
    for o in old_entries:
        if o["anchor"] in new_set:
            kept.append(o["anchor"])
            continue
        best, best_r = None, -1.0
        for n in new_entries:
            if n["sec"] != o["sec"] or n["kind"] != o["kind"]:
                continue
            if n["anchor"] in old_set or n["anchor"] in used:
                continue
            r = difflib.SequenceMatcher(None, o["text"], n["text"]).ratio()
            if r > best_r:  # 嚴格大於 → 同分保留文件順序最前者
                best, best_r = n, r
        if best is not None and best_r >= MIGRATE_RATIO:
            used.add(best["anchor"])
            moved.append({"from": o["anchor"], "to": best["anchor"], "ratio": round(best_r, 4),
                          "to_statusable": bool(best.get("statusable", False))})
        else:
            orphaned.append(o["anchor"])
    return {"kept": kept, "moved": moved, "orphaned": orphaned}


def load_prev(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("anchor_index"), list):
        return data["anchor_index"]
    if isinstance(data, dict) and isinstance(data.get("content"), dict):
        return anchors.build_anchors(anchors.normalize_content(data["content"]))
    raise PublishError("--prev 檔案格式無法辨識（需 anchor_index 陣列或含 content 的報告物件）")


# ---------- 共用 ----------

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def unique_name(name, taken):
    stem, ext = os.path.splitext(name)
    cand, i = name, 1
    while cand in taken:
        i += 1
        cand = "%s-%d%s" % (stem, i, ext)
    taken.add(cand)
    return cand


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.startswith("export "):
                k = k[len("export "):]
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env[k.strip()] = v
    return env


def summary(mode, period, content, entries, migration=None, extra=None):
    counts = {}
    for b in content["blocks"]:
        t = anchors.block_type(b)
        counts[t] = counts.get(t, 0) + 1
    s = {
        "mode": mode, "period": period, "title": content.get("title"),
        "block_count": len(content["blocks"]), "block_types": counts,
        "photo_count": len(list(iter_photo_items(content))),
        "anchor_count": len(entries),
        "anchors": [{"anchor": e["anchor"], "kind": e["kind"], "btype": e["btype"],
                     "statusable": e["statusable"]} for e in entries],
        "status_anchors": anchors.status_anchors(entries),
        "migration": migration,
    }
    if extra:
        s.update(extra)
    return s


# ---------- --mock（CONTRACTS §6.2／§6.3） ----------

def publish_mock(content, entries, period, base_dirs, mock_dir, skip_photos):
    photo_dir = os.path.join(mock_dir, "photos", period)
    rel_base = "../private/mock/photos/%s/" % period
    taken = set()
    copies = []
    for it in iter_photo_items(content):
        name = unique_name(os.path.basename(it["path"]), taken)
        if not skip_photos:
            src = find_photo(it["path"], base_dirs)
            if src is None:
                raise PublishError("照片檔不存在：%s" % it["path"])
            copies.append((src, os.path.join(photo_dir, name)))
        it["url"] = it["path"] = rel_base + name

    report_path = os.path.join(mock_dir, "%s.json" % period)
    version, migration = 1, None
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as f:
            old = json.load(f)
        version = int(old.get("version") or 0) + 1
        try:
            old_entries = anchors.build_anchors(anchors.normalize_content(old["content"]))
            migration = plan_migration(old_entries, entries)  # mock 的留言在瀏覽器，僅供參考
        except (ValueError, TypeError, KeyError):
            migration = None

    os.makedirs(mock_dir, exist_ok=True)
    if copies:
        os.makedirs(photo_dir, exist_ok=True)
        for src, dst in copies:
            shutil.copyfile(src, dst)
    published_at = now_iso()
    report = {"report_id": "m-%s" % period, "period": period, "title": content.get("title"),
              "content": content, "version": version, "published_at": published_at,
              "status_anchors": anchors.status_anchors(entries)}
    _write_json(report_path, report)

    index_path = os.path.join(mock_dir, "index.json")
    reports = []
    if os.path.isfile(index_path):
        with open(index_path, encoding="utf-8") as f:
            reports = [r for r in (json.load(f).get("reports") or []) if r.get("period") != period]
    reports.append({"report_id": report["report_id"], "period": period, "title": report["title"],
                    "published_at": published_at, "version": version, "comment_count": 0})
    reports.sort(key=lambda r: r["period"], reverse=True)
    _write_json(index_path, {"reports": reports})
    return {"version": version, "report_path": report_path, "copied_photos": len(copies)}, migration


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


# ---------- 正式模式：Supabase REST（未實測） ----------

class Supabase(object):
    """service_role 直連 PostgREST／Storage。帳號未開，以下請求格式皆未實測。"""

    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.key = key

    def _req(self, method, path, body=None, headers=None, raw=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key}
        data = raw
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise PublishError("%s %s → HTTP %d：%s" % (method, path.split("?")[0], e.code,
                                                       e.read().decode("utf-8", "replace")[:500]))
        return json.loads(txt) if txt.strip() else None

    def rest(self, method, table, query="", body=None, prefer=None):
        headers = {"Prefer": prefer} if prefer else None
        return self._req(method, "/rest/v1/%s%s" % (table, ("?" + query) if query else ""), body, headers)

    def upload(self, obj_path, local):
        ctype = mimetypes.guess_type(local)[0] or "application/octet-stream"
        with open(local, "rb") as f:
            raw = f.read()
        self._req("POST", "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(obj_path)),
                  raw=raw, headers={"Content-Type": ctype, "x-upsert": "true"})

    def sign(self, obj_path):
        r = self._req("POST", "/storage/v1/object/sign/%s/%s" % (BUCKET, urllib.parse.quote(obj_path)),
                      body={"expiresIn": SIGN_EXPIRES})
        signed = r.get("signedURL") or r.get("signedUrl")
        if not signed:
            raise PublishError("簽章回應缺少 signedURL")
        return signed if signed.startswith("http") else self.url + "/storage/v1" + signed


def _q(v):
    return urllib.parse.quote(str(v), safe="")


def publish_formal(content, entries, period, base_dirs, env_file):
    if not os.path.isfile(env_file):
        raise PublishError("找不到 %s（需 SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY）" % env_file)
    env = load_env(env_file)
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise PublishError("%s 缺 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY" % env_file)
    sb = Supabase(url, key)

    rows = sb.rest("GET", "reports", "select=id,version,anchor_index&period=eq.%s" % _q(period))
    old = rows[0] if rows else None

    taken = set()
    for it in iter_photo_items(content):
        local = find_photo(it["path"], base_dirs)
        if local is None:
            raise PublishError("照片檔不存在：%s" % it["path"])
        obj = "%s/%s" % (period, unique_name(os.path.basename(it["path"]), taken))
        sb.upload(obj, local)
        it["path"] = obj
        it["url"] = sb.sign(obj)

    version = int(old["version"]) + 1 if old else 1
    payload = {"period": period, "title": content.get("title"), "content": content,
               "status_anchors": anchors.status_anchors(entries),
               "version": version, "published_at": now_iso()}
    if not old:
        payload["anchor_index"] = entries
    res = sb.rest("POST", "reports", "on_conflict=period", payload,
                  prefer="resolution=merge-duplicates,return=representation")
    report_id = res[0]["id"]

    migration = None
    if old:
        # anchor_index 最後才寫：遷移中途失敗時 DB 仍留舊版索引，重跑會重算同一份對應（遷移本身冪等）
        migration = plan_migration(old.get("anchor_index") or [], entries)
        apply_migration(sb, report_id, migration)
        sb.rest("PATCH", "reports", "id=eq.%s" % _q(report_id), {"anchor_index": entries},
                prefer="return=minimal")
    return {"version": version, "report_id": report_id}, migration


def apply_migration(sb, report_id, plan):
    rid = "report_id=eq.%s" % _q(report_id)
    for m in plan["moved"]:
        a_old, a_new = _q(m["from"]), _q(m["to"])
        sb.rest("PATCH", "comments", "%s&anchor=eq.%s" % (rid, a_old), {"anchor": m["to"]})
        if not m.get("to_statusable", False):
            # 新位置不可指示狀態（例如 decision 表改成別的表）→ 舊狀態作廢，不搬過去
            sb.rest("DELETE", "statuses", "%s&anchor=eq.%s" % (rid, a_old))
            continue
        olds = sb.rest("GET", "statuses", "select=reader_id,updated_at&%s&anchor=eq.%s" % (rid, a_old)) or []
        news = sb.rest("GET", "statuses", "select=reader_id,updated_at&%s&anchor=eq.%s" % (rid, a_new)) or []
        new_at = dict((s["reader_id"], s["updated_at"]) for s in news)
        for s in olds:
            who = "reader_id=eq.%s" % _q(s["reader_id"])
            if s["reader_id"] in new_at:
                # 撞 pk：保留 updated_at 較新者（ISO 字串同時區可比；PG 皆回 +00:00）
                if s["updated_at"] > new_at[s["reader_id"]]:
                    sb.rest("DELETE", "statuses", "%s&anchor=eq.%s&%s" % (rid, a_new, who))
                    sb.rest("PATCH", "statuses", "%s&anchor=eq.%s&%s" % (rid, a_old, who), {"anchor": m["to"]})
                else:
                    sb.rest("DELETE", "statuses", "%s&anchor=eq.%s&%s" % (rid, a_old, who))
            else:
                sb.rest("PATCH", "statuses", "%s&anchor=eq.%s&%s" % (rid, a_old, who), {"anchor": m["to"]})
    for a in plan["orphaned"]:
        sb.rest("PATCH", "comments", "%s&anchor=eq.%s" % (rid, _q(a)), {"orphaned": True})
        sb.rest("DELETE", "statuses", "%s&anchor=eq.%s" % (rid, _q(a)))


# ---------- CLI ----------

def parse_args(argv):
    p = argparse.ArgumentParser(description="發佈工作報告 content.json")
    p.add_argument("path", help="content.json 或期間資料夾（含 _src/content.json）")
    p.add_argument("--mock", action="store_true", help="不碰網路，寫 private/mock/")
    p.add_argument("--dry-run", action="store_true", help="驗證＋錨點＋遷移試算，印摘要，不寫檔不連網")
    p.add_argument("--vectors", action="store_true", help="stdout 印 AnchorEntry[] JSON")
    p.add_argument("--skip-photos", action="store_true", help="跳過照片檔存在檢查（測試用）")
    p.add_argument("--prev", help="--dry-run 遷移試算用的舊版 anchor_index 或報告 json")
    p.add_argument("--period", help="期別 ID（預設由路徑推導）")
    p.add_argument("--mock-dir", default=DEFAULT_MOCK_DIR, help=argparse.SUPPRESS)
    p.add_argument("--env-file", default=DEFAULT_ENV, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if sum(bool(x) for x in (args.mock, args.dry_run, args.vectors)) > 1:
        print("[publish] --mock／--dry-run／--vectors 只能擇一", file=sys.stderr)
        return 2
    try:
        content_path, base_dirs = resolve_input(args.path)
        with open(content_path, encoding="utf-8") as f:
            raw = json.load(f)
        period = args.period or derive_period(content_path)
        check_photos = not (args.skip_photos or args.vectors)
        errs = validate(raw, base_dirs, check_photos=check_photos)
        if errs:
            print("[publish] 內容驗證失敗，拒收：", file=sys.stderr)
            for e in errs:
                print("  - " + e, file=sys.stderr)
            return 2
        content = anchors.normalize_content(raw)
        entries = anchors.build_anchors(content)

        if args.vectors:
            sys.stdout.write(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
            return 0
        if args.dry_run:
            migration = plan_migration(load_prev(args.prev), entries) if args.prev else None
            print(json.dumps(summary("dry-run", period, content, entries, migration),
                             ensure_ascii=False, indent=1))
            return 0
        if args.mock:
            extra, migration = publish_mock(content, entries, period, base_dirs, args.mock_dir,
                                            args.skip_photos)
            print(json.dumps(summary("mock", period, content, entries, migration, extra),
                             ensure_ascii=False, indent=1))
            return 0
        extra, migration = publish_formal(content, entries, period, base_dirs, args.env_file)
        print(json.dumps(summary("formal", period, content, entries, migration, extra),
                         ensure_ascii=False, indent=1))
        return 0
    except (PublishError, OSError, ValueError) as e:
        print("[publish] 失敗：%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
