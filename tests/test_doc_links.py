"""文档仓库路径防漂移：docs/**/*.md 里的反引号路径引用不得指向不存在的文件。

原理
----
1. 扫 ``docs/**/*.md``，用正则抓出**反引号包裹**、且以仓库顶层目录名开头的路径
   （``src/ tests/ scripts/ web/ frontend/ website/ docs/``）。裸文本里的路径
   （如表格单元格里没加反引号的 ``website/index.html``）不在本守卫范围内。
2. 对每条引用，**要么**该路径真实存在，**要么**它所在的**那一行**带豁免标记。
3. 豁免标记只有四种，语义固定：
   - ``（示例…``  —— 示例占位，本来就不指向真实文件（如 ``src/a.py``）
   - ``（提案…``  —— 提案文档里"计划中但未实现"的文件
   - ``已归档``   —— 引用了已改名/删除且找不到替代的文档
   - ``（建议新增`` —— 明确写成"建议新增"的路径

这是回归护栏：把文件挪了包（``src/x.ts`` → ``frontend/tui/src/x.ts``）、删了文档，
却在别处留下旧路径时，本文件会红。p7-doc-links 就是为它清理的 25 条断链。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"

_PATH_REF_RE = re.compile(r"`((?:src|tests|scripts|web|frontend|website|docs)/[A-Za-z0-9_./-]+)`")

# 豁免标记：必须是"（"紧跟关键词的完整角括号前缀，避免正文里偶然出现同名字样。
EXEMPTION_MARKERS: tuple[str, ...] = (
    "（示例",
    "（提案",
    "已归档",
    "（建议新增",
)

# 绊线：正则一旦失效/文档被搬走，扫到的引用数会塌下来，测试必须红，
# 而不是变成一个永远绿的空壳。
MIN_REFERENCES = 200


def _iter_references() -> list[tuple[str, int, str, str]]:
    """返回 ``(文档相对路径, 行号, 引用路径, 整行原文)`` 列表。"""
    found: list[tuple[str, int, str, str]] = []
    for md in sorted(DOCS_DIR.rglob("*.md")):
        rel_doc = md.relative_to(ROOT).as_posix()
        text = md.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in _PATH_REF_RE.finditer(line):
                found.append((rel_doc, lineno, match.group(1), line))
    return found


def _is_exempt(line: str) -> bool:
    return any(marker in line for marker in EXEMPTION_MARKERS)


@pytest.fixture(scope="module")
def references() -> list[tuple[str, int, str, str]]:
    assert DOCS_DIR.is_dir(), f"缺少文档目录：{DOCS_DIR}"
    assert any(DOCS_DIR.rglob("*.md")), f"{DOCS_DIR} 下没有任何 .md"
    return _iter_references()


def test_docs_dir_is_scanned(references: list[tuple[str, int, str, str]]) -> None:
    """守卫本身要真的扫到了东西，否则下面的断言都是空转。"""
    assert references, "正则没抓到任何路径引用，守卫已失效"


def test_reference_count_is_plausible(
    references: list[tuple[str, int, str, str]],
) -> None:
    """扫到的引用数必须 > 200，防止"正则悄悄失配 → 测试永远绿"。"""
    count = len(references)
    assert count > MIN_REFERENCES, (
        f"docs/**/*.md 只扫到 {count} 条反引号路径引用，"
        f"低于下限 {MIN_REFERENCES}；多半是正则失配或文档被搬走"
    )


def test_every_referenced_path_exists_or_is_exempted(
    references: list[tuple[str, int, str, str]],
) -> None:
    """每条引用要么真实存在、要么被 .gitignore 覆盖、要么该行带豁免标记。

    加 ".gitignore 覆盖" 这一条是因为 CI 与本地差异：`frontend/tui/dist/`、
    `frontend/tui/node_modules`、`web/.shots/` 这些**构建产物/缓存目录**在开发机上
    真实存在，但在干净检出里不存在 —— 引用它们是合法的，不该判红。
    """
    candidates = [
        (doc, lineno, path, line)
        for doc, lineno, path, line in references
        if not (ROOT / path).exists() and not _is_exempt(line)
    ]
    ignored = _gitignored_paths(sorted({path for _, _, path, _ in candidates}))
    broken = [
        f"{doc}:{lineno} → {path}" for doc, lineno, path, _ in candidates if path not in ignored
    ]
    assert not broken, (
        "docs 里有指向不存在文件的路径引用（无豁免标记）：\n  "
        + "\n  ".join(sorted(broken))
        + "\n\n修法：文件只是挪了位置就改成完整路径；示例占位补 `（示例）`；"
        "提案未实现补 `（提案，未实现）`；文档已改名/删除就改指替代或补 `已归档`；"
        "引用的若是构建产物/缓存目录，确认它已被 .gitignore 覆盖即可。"
    )


def _gitignored_paths(paths: list[str]) -> set[str]:
    """批量判断哪些路径被 .gitignore 覆盖（一次 git 调用，避免逐条开销）。"""
    if not paths:
        return set()
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(paths),
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    except OSError:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}
