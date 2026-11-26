"""推版並確認 Pages 部署成功；失敗時自動改用全新 run 重新部署。

用法（在 repo 任何位置）：
    python tools/push_deploy.py              # 外洩檢查 → push main → 等部署 → 失敗自動重新部署
    python tools/push_deploy.py --no-push    # 不 push，只檢查目前 HEAD 的部署，失敗就重新部署
    python tools/push_deploy.py --redeploy   # 不 push，直接觸發一次全新部署

為什麼不用 `gh run rerun`：對同一個 run 重跑會累積同名的 github-pages 打包檔，
deploy-pages 看到兩份就拒絕部署（Multiple artifacts named "github-pages"），
所以失敗一律改用 workflow_dispatch 開新的 run。
"""
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = "pages.yml"
WAIT_SEC = 240      # 單次部署最長等待
MAX_REDEPLOY = 2    # 失敗後最多重新部署幾次
FIELDS = "databaseId,status,conclusion,event,url"


def run(cmd, check=True):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        sys.exit(f"指令失敗：{' '.join(cmd)}\n{p.stdout}{p.stderr}")
    return p.stdout.strip()


def runs_for(sha):
    out = run(["gh", "run", "list", "--workflow", WORKFLOW, "--commit", sha, "--json", FIELDS, "-L", "20"])
    return json.loads(out or "[]")


def wait_run(sha, seen):
    """等一個不在 seen 裡的 run 跑完，回傳該 run；逾時回傳 None。"""
    deadline = time.time() + WAIT_SEC
    while time.time() < deadline:
        new = [r for r in runs_for(sha) if r["databaseId"] not in seen]
        if new:
            r = max(new, key=lambda x: x["databaseId"])
            if r["status"] == "completed":
                return r
        time.sleep(8)
    return None


def main():
    args = set(sys.argv[1:])
    unknown = args - {"--no-push", "--redeploy"}
    if unknown:
        sys.exit(f"不認得的參數：{' '.join(sorted(unknown))}")

    sha = run(["git", "rev-parse", "HEAD"])
    seen = set()
    result = None

    if "--redeploy" in args:
        seen = {r["databaseId"] for r in runs_for(sha)}
    elif "--no-push" in args:
        done = [r for r in runs_for(sha) if r["status"] == "completed"]
        if done:
            result = max(done, key=lambda x: x["databaseId"])
        seen = {r["databaseId"] for r in runs_for(sha)}
        if result is None:
            result = wait_run(sha, set())
    else:
        if os.path.isfile(os.path.join(ROOT, "tools", "check_leak.sh")):
            run(["bash", "tools/check_leak.sh"])
        seen = {r["databaseId"] for r in runs_for(sha)}
        run(["git", "push", "origin", "main"])
        print(f"已 push {sha[:7]}，等待部署…")
        result = wait_run(sha, seen)

    for attempt in range(MAX_REDEPLOY + 1):
        if result and result["conclusion"] == "success":
            print(f"部署成功：{result['url']}")
            return
        if attempt == MAX_REDEPLOY:
            break
        why = result["conclusion"] if result else "尚未部署或等待逾時"
        print(f"部署未成功（{why}），改用全新 run 重新部署（第 {attempt + 1} 次）…")
        seen |= {r["databaseId"] for r in runs_for(sha)}
        run(["gh", "workflow", "run", WORKFLOW, "--ref", "main"])
        result = wait_run(sha, seen)

    sys.exit(f"重新部署 {MAX_REDEPLOY} 次仍未成功，請看：{result['url'] if result else 'gh run list'}")


if __name__ == "__main__":
    main()
