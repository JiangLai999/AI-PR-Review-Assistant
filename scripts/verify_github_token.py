"""验证 GitHub token 有效性，并检查与审查流程相关的最小权限。

注意：本脚本只打印账号名与权限范围，不打印 token 明文。
token 通过环境变量传入，避免出现在命令行历史里。
"""

import json
import os
import urllib.error
import urllib.request

token = os.environ.get("GH_PROBE_TOKEN", "").strip()
if not token:
    raise SystemExit("缺少 GH_PROBE_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "ai-pr-review-probe",
}


def call(path: str) -> tuple[int, dict, dict]:
    req = urllib.request.Request(f"https://api.github.com{path}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"message": "unparseable"}
        return e.code, body, dict(e.headers)


print("=== /user ===")
status, data, headers = call("/user")
print("HTTP", status)
if status == 200:
    print("  登录名   :", data.get("login"))
    print("  类型     :", data.get("type"))
    print("  scopes   :", headers.get("X-OAuth-Scopes") or "(未返回，细粒度 token 正常)")
    print(
        "  配额余量 :", headers.get("X-RateLimit-Remaining"), "/", headers.get("X-RateLimit-Limit")
    )
else:
    print("  错误     :", str(data.get("message"))[:120])
    raise SystemExit(1)

print("\n=== 读仓库（审查流程必需）===")
status, data, _ = call("/repos/JiangLai999/AI-PR-Review-Assistant")
print("HTTP", status, "|", (data.get("full_name") or data.get("message", ""))[:60])
if status == 200:
    print("  默认分支 :", data.get("default_branch"))
    print("  私有     :", data.get("private"))

print("\n=== 读 PR（审查入口）===")
status, data, _ = call("/repos/JiangLai999/AI-PR-Review-Assistant/pulls/32")
print("HTTP", status)
if status == 200:
    print("  标题     :", str(data.get("title"))[:60])
    print("  状态     :", data.get("state"), "| 变更文件:", data.get("changed_files"))
    print("  merge_commit_sha:", str(data.get("merge_commit_sha"))[:12])
else:
    print("  错误     :", str(data.get("message"))[:120])
