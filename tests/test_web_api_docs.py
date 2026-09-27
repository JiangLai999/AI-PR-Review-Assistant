"""接口文档防漂移：docs/API.md 必须覆盖 web_server.py 实际注册的 /api 路由。

原理
----
1. 只解析 ``web_server.py`` 里 ``do_GET`` / ``do_POST`` 两个方法体中的
   ``"/api/..."`` **字符串字面量**（注释中的示例不会被匹配到，无需额外清洗；
   若将来注释里出现带引号的 ``/api/`` 示例，加入 ``EXCLUDED`` 即可）。
2. 把 docs/API.md 里出现的 ``/api/...`` 路径抽出来做集合。
3. 断言服务端每一条字面量都能在文档中找到；缺任何一条即失败。
   前缀路由（如 ``/api/jobs/``）单独校验：文档中必须存在以该前缀开头的具体路径。

这是回归护栏：服务端新增/改名路由而文档未同步时，本文件会红。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "src" / "ai_pr_review" / "web_server.py"
API_DOC = ROOT / "docs" / "API.md"

# 非端点字面量（404 兜底等），允许出现在服务端但不要求文档逐字收录。
EXCLUDED: set[str] = {
    "/api/",
}

# startswith 前缀路由：文档用 ``/api/jobs/{id}`` 这类具体路径表达，
# 校验"文档中存在以此前缀开头的路径"而不是逐字相等。
PREFIX_LITERALS: set[str] = {
    "/api/jobs/",
}

_LITERAL_RE = re.compile(r'"(/api/[^"]*)"')
_DOC_PATH_RE = re.compile(r"(/api/[A-Za-z0-9_\-./{}]*)(?:\?[^`\s)]*)?")
_METHOD_RE = re.compile(
    r"def (?P<name>do_GET|do_POST)\(self\).*?(?=\n    def |\nclass |\Z)",
    re.S,
)


def _server_literals() -> set[str]:
    src = WEB_SERVER.read_text(encoding="utf-8")
    found: set[str] = set()
    for match in _METHOD_RE.finditer(src):
        found.update(_LITERAL_RE.findall(match.group(0)))
    return found


def _doc_paths() -> set[str]:
    text = API_DOC.read_text(encoding="utf-8")
    return set(_DOC_PATH_RE.findall(text))


def _doc_text() -> str:
    return API_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server_paths() -> set[str]:
    assert WEB_SERVER.is_file(), f"缺少服务端源文件：{WEB_SERVER}"
    return _server_literals()


@pytest.fixture(scope="module")
def doc_path_set() -> set[str]:
    assert API_DOC.is_file(), f"缺少接口文档：{API_DOC}"
    return _doc_paths()


def test_web_server_exists() -> None:
    assert WEB_SERVER.is_file()


def test_api_doc_exists() -> None:
    assert API_DOC.is_file()


def test_every_server_route_is_documented(server_paths: set[str]) -> None:
    """服务端每条 /api 字面量都必须出现在 docs/API.md。"""
    doc = _doc_text()
    missing = sorted(
        p for p in server_paths if p not in EXCLUDED and p not in PREFIX_LITERALS and p not in doc
    )
    assert not missing, (
        "docs/API.md 缺少以下 web_server.py 路由（服务端有、文档无）：\n  "
        + "\n  ".join(missing)
    )


def test_prefix_routes_have_documented_children(server_paths: set[str]) -> None:
    """startswith 前缀路由必须在文档里有对应的具体子路径。"""
    doc_paths = _doc_paths()
    missing = []
    for prefix in sorted(PREFIX_LITERALS):
        if prefix not in server_paths:
            continue
        if not any(p.startswith(prefix) and p != prefix for p in doc_paths):
            missing.append(prefix)
    assert not missing, (
        "docs/API.md 未为以下前缀路由给出任何具体子路径：\n  " + "\n  ".join(missing)
    )


def test_documented_concrete_paths_exist_on_server(doc_path_set: set[str]) -> None:
    """文档里写死的具体路径（不含 {param}）不能凭空出现。

    参数化路径（``/api/jobs/{id}`` 等）改由前缀断言覆盖，这里只查具体字面量。
    """
    server = _server_literals()
    # 服务端前缀字面量（以 / 结尾）视为"注册了该子树"。
    prefixes = {p for p in server if p.endswith("/")}
    concrete_doc = sorted(p for p in doc_path_set if "{" not in p and p not in EXCLUDED)
    orphans = []
    for path in concrete_doc:
        if path in server:
            continue
        if any(path.startswith(prefix) for prefix in prefixes):
            continue
        orphans.append(path)
    assert not orphans, (
        "docs/API.md 声称存在但 web_server.py 的 do_GET/do_POST 中找不到的路径：\n  "
        + "\n  ".join(orphans)
    )


def test_expected_endpoint_count() -> None:
    """19 条 API 路由的硬约束：文档总表必须列出 19 行 + 静态资源。

    这是一道**绊线**：新增端点时必须显式改这个数字（Phase 3 加 `/api/chat` 时从 18 → 19），
    避免"悄悄多了一个没写文档的接口"。
    """
    text = API_DOC.read_text(encoding="utf-8")
    table_rows = re.findall(r"^\|\s*\d+\s*\|\s*(?:GET|POST|GET, POST)", text, re.M)
    assert len(table_rows) == 19, f"API.md 端点总表应有 19 条编号行，实际 {len(table_rows)}"
    assert "/static/*" in text or "/static/" in text, "API.md 需描述 /static/* 静态资源"
