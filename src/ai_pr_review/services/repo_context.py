"""仓库相关文件预取（L1-a）：纯逻辑 + 依赖注入。

本模块刻意不接触真实 GitHub API、不读配置、不 import PyGithub /
``ai_pr_review.config``：文件读取与缓存全部通过构造注入，便于单测与后续在
L1-b 接入 `PRFetcher` / 磁盘缓存。

策略（对单个变更文件）：
1. 同名测试文件（多候选路径，依次尝试取首个命中）
2. Python 相对导入目标（`from .X import` / `from ..X.Y import`）
3. 同目录 ``__init__.py``

收集结果按优先级排序、去重，受 ``max_files`` 与 ``budget_tokens`` 约束；
超长文件截断到「符号定义附近」片段。

文件末尾另有一组**纯渲染**函数（``render_pr_file_list`` / ``render_repo_tree``），
供聊天侧注入"本次 PR 变更文件清单"与"仓库目录树"（见
docs/claude-repo-structure-context.md）：同样不碰网络，路径由调用方取好传进来。
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

SOURCE_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})
TEST_MAX_LINES = 120
IMPORT_INIT_MAX_LINES = 80
_CHARS_PER_TOKEN = 4
_SNIPPET_RADIUS = 20

# 单行相对导入：from .X.Y import a, b / from . import x
_FROM_RELATIVE = re.compile(
    r"^from\s+(?P<dots>\.+)(?P<module>[A-Za-z_][\w.]*)?\s+import\s+(?P<names>.+)$"
)
_DEF_OR_CLASS = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+")


@dataclass(slots=True)
class RelatedFile:
    """一个已收集的相关仓库文件。"""

    path: str
    reason: str  # "test" | "import" | "init"
    content: str
    truncated: bool
    from_cache: bool


@runtime_checkable
class RepoCache(Protocol):
    """相关文件内容缓存（按稳定 key）。"""

    def get(self, key: str) -> str | None: ...

    def put(self, key: str, content: str) -> None: ...


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("/")


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def _test_candidates(file_path: str) -> list[str]:
    """同名测试文件的候选路径（依次尝试，取首个命中）。"""
    parent = _dirname(file_path)
    name = _basename(file_path)
    if "." not in name:
        return []
    stem = name.rsplit(".", 1)[0]
    ext = "." + name.rsplit(".", 1)[-1]
    test_name = f"test_{stem}{ext}"
    return [
        _join(parent, test_name),
        _join("tests", test_name),
        _join("tests", parent, test_name),
        _join("test", test_name),
    ]


def _relative_import_targets(file_path: str, source: str) -> list[str]:
    """解析 Python 相对导入，折算为仓库根相对的模块路径（不含扩展名）。"""
    parent = _dirname(file_path)
    base_parts = [p for p in parent.split("/") if p and p != "."]
    targets: list[str] = []
    seen: set[str] = set()

    for raw_line in source.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        match = _FROM_RELATIVE.match(line.strip())
        if match is None:
            continue
        level = len(match.group("dots"))
        module = (match.group("module") or "").strip()
        names_raw = match.group("names")

        up = level - 1
        if up > len(base_parts):
            continue
        parts = base_parts[: len(base_parts) - up] if up else list(base_parts)

        if module:
            candidates = ["/".join(parts + module.split(".")) if parts else module.replace(".", "/")]
        else:
            # `from . import a, b`：导入名可能是子模块
            candidates = []
            spec = names_raw.split("#", 1)[0].strip()
            if spec.startswith("(") and spec.endswith(")"):
                spec = spec[1:-1]
            for item in spec.split(","):
                name = item.strip().split(" as ")[0].strip()
                if name and name != "*" and name.isidentifier():
                    candidates.append(_join(*parts, name) if parts else name)

        for target in candidates:
            if target and target not in seen:
                seen.add(target)
                targets.append(target)
    return targets


def _truncate(content: str, max_lines: int) -> tuple[str, bool]:
    """超限时保留 def/class 定义行 ±20 行片段；无定义则取文件头。"""
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content, False
    for index, line in enumerate(lines):
        if _DEF_OR_CLASS.match(line):
            start = max(0, index - _SNIPPET_RADIUS)
            end = min(len(lines), index + _SNIPPET_RADIUS + 1)
            return "\n".join(lines[start:end]), True
    return "\n".join(lines[:max_lines]), True


class RepoContextProvider:
    """按启发式策略预取与变更文件相关的仓库内容。"""

    def __init__(
        self,
        read_file: Callable[[str], str | None],
        cache: RepoCache | None = None,
        max_files: int = 3,
        budget_tokens: int = 4000,
        reasons: frozenset[str] | set[str] | None = None,
    ) -> None:
        self._read_file = read_file
        self._cache = cache
        self.max_files = max_files
        self.budget_tokens = budget_tokens
        # None = 全部策略（既有行为）。传入 {"test"} 时只跑同名测试文件策略，
        # 对应 preferences.repo_context == "tests"。
        self._reasons = frozenset(reasons) if reasons is not None else None

    def collect_for_file(self, file_path: str) -> list[RelatedFile]:
        """返回已去重、按优先级排序、已截断的相关文件。"""
        if self.max_files <= 0:
            return []
        path = _normalize(file_path)
        if _extension(path) not in SOURCE_EXTENSIONS:
            return []

        candidates: list[tuple[str, str]] = []
        memo: dict[str, tuple[str | None, bool]] = {}

        def load(target: str) -> tuple[str | None, bool]:
            if target not in memo:
                memo[target] = self._load(target)
            return memo[target]

        def wanted(reason: str) -> bool:
            return self._reasons is None or reason in self._reasons

        # 1) 同名测试文件：候选依次尝试，首个命中即收
        if wanted("test"):
            for candidate in _test_candidates(path):
                content, _ = load(candidate)
                if content is not None:
                    candidates.append((candidate, "test"))
                    break

        # 2) 相对导入目标
        if wanted("import") and path.endswith(".py"):
            source, _ = load(path)
            if source is not None:
                for target in _relative_import_targets(path, source):
                    resolved = self._resolve_module(target, load)
                    if resolved is not None:
                        candidates.append((resolved, "import"))

        # 3) 同目录 __init__.py
        if wanted("init") and _basename(path) != "__init__.py":
            init_path = _join(_dirname(path), "__init__.py")
            if init_path != path:
                candidates.append((init_path, "init"))

        collected: list[RelatedFile] = []
        seen: set[str] = set()
        for candidate, reason in candidates:
            if candidate in seen or candidate == path:
                continue
            seen.add(candidate)
            content, from_cache = load(candidate)
            if content is None:
                continue
            max_lines = TEST_MAX_LINES if reason == "test" else IMPORT_INIT_MAX_LINES
            body, truncated = _truncate(content, max_lines)
            collected.append(
                RelatedFile(
                    path=candidate,
                    reason=reason,
                    content=body,
                    truncated=truncated,
                    from_cache=from_cache,
                )
            )
            if len(collected) >= self.max_files:
                break

        return self._apply_budget(collected)

    def _load(self, path: str) -> tuple[str | None, bool]:
        """读取单个文件；任何失败返回 ``(None, False)``，不向上抛。"""
        key = path
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached, True
        try:
            content = self._read_file(path)
        except Exception:
            return None, False
        if content is None:
            return None, False
        if self._cache is not None:
            self._cache.put(key, content)
        return content, False

    def _resolve_module(self, module_path: str, load: Callable[[str], tuple[str | None, bool]]) -> str | None:
        """模块路径 → 文件：优先 ``.py``，其次目录下 ``__init__.py``。"""
        for candidate in (f"{module_path}.py", _join(module_path, "__init__.py")):
            content, _ = load(candidate)
            if content is not None:
                return candidate
        return None

    def _apply_budget(self, files: list[RelatedFile]) -> list[RelatedFile]:
        """总字符数超预算时，从优先级最低的条目开始丢弃。"""
        max_chars = self.budget_tokens * _CHARS_PER_TOKEN
        if max_chars <= 0:
            return []
        kept = list(files)

        def total(items: list[RelatedFile]) -> int:
            return sum(len(item.content) for item in items)

        while kept and total(kept) > max_chars and len(kept) > 1:
            kept.pop()
        if not kept:
            return []
        if total(kept) <= max_chars:
            return kept
        # 仅剩 1 条仍超预算：若另有能放进预算的条目，则至少保留一条
        fits = [item for item in files if len(item.content) <= max_chars]
        return [fits[0]] if fits else kept


_UNSAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(value: str) -> str:
    """把 owner/repo/sha 折成单个安全目录名（防路径穿越与 Windows 非法字符）。"""
    cleaned = _UNSAFE_SEGMENT.sub("_", value.strip().replace("\\", "/").strip("/"))
    return cleaned or "_"


def _safe_file_name(path: str) -> str:
    """把仓库相对路径折成安全文件名（保留可读性）。"""
    normalized = _normalize(path).replace("/", "__")
    cleaned = _UNSAFE_SEGMENT.sub("_", normalized)
    return cleaned or "_"


def default_repo_cache_root() -> Path:
    """缓存根目录：Windows 用 ``%LOCALAPPDATA%``，其它平台回退到用户数据目录。"""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ai-pr-review" / "repo_cache"
    return Path.home() / ".local" / "share" / "ai-pr-review" / "repo_cache"


class FileSystemRepoCache:
    """把相关文件内容落盘缓存：``<root>/<owner>__<repo>/<sha>/<safe-path>.txt``。

    只新增、不改动既有 `RepoCache` 协议语义。写入用 tempfile + ``os.replace``
    保证原子性；任何 I/O 失败都吞掉并返回缓存未命中，绝不让缓存问题影响审查。
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        sha: str,
        root: Path | str | None = None,
    ) -> None:
        base = Path(root) if root is not None else default_repo_cache_root()
        self._dir = base / f"{_safe_segment(owner)}__{_safe_segment(repo)}" / _safe_segment(sha)

    @property
    def directory(self) -> Path:
        return self._dir

    def _file_for(self, key: str) -> Path:
        return self._dir / f"{_safe_file_name(key)}.txt"

    def get(self, key: str) -> str | None:
        try:
            return self._file_for(key).read_text(encoding="utf-8")
        except OSError:
            return None

    def put(self, key: str, content: str) -> None:
        target = self._file_for(key)
        tmp_name: str | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp_name, target)
            tmp_name = None
        except OSError:
            pass
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


# ── 聊天侧注入：PR 变更清单 / 仓库目录树（docs/claude-repo-structure-context.md）──
#
# 与上面的预取不同，这里只有**纯渲染**：路径从哪来（`PRFetcher` 的变更分页 /
# git tree）、失败怎么降级、什么时候注入，全部由调用方（`backend/jsonl_server.py`）
# 决定。放在本模块是为了跟 `SOURCE_EXTENSIONS` / `FileSystemRepoCache` 一起维护
# "仓库内容怎么给模型看"的口径，也便于在 tests/test_repo_context.py 里不碰网络
# 直接钉住格式。

# 变更清单**每一轮**都会随 system prompt 注入，必须小：单次最多列出这么多路径，
# 其余折叠成一行计数（绝不静默丢弃）。
PR_FILE_LIST_LIMIT = 50
# 目录树的深度与行数上限；超出的部分一律折叠成计数。
REPO_TREE_MAX_DEPTH = 3
REPO_TREE_MAX_ENTRIES = 200
# 单个目录最多列出多少个子项（目录+文件合计）。只有全局行数上限是不够的：实测本仓库
# 的 `.agent-bus/locks/`（深度 2、几十个文件）会吃光整棵树的行数预算，`src/` 一个
# 字都进不了注入——一棵只看得见产物目录的树等于没给。超出的子项折叠成一行计数。
REPO_TREE_MAX_CHILDREN_PER_DIR = 25
# 目录树里不进注入的噪声目录 / 文件（对"仓库结构"没有信息量，只会吃 token）。
TREE_NOISE_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".cache", ".eggs",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv",
        ".next", ".nuxt", ".svelte-kit", "__pycache__", "build", "coverage",
        "dist", "env", "htmlcov", "node_modules", "out", "site-packages",
        "target", "venv", "vendor",
    }
)
TREE_NOISE_FILES = frozenset({".DS_Store", "Thumbs.db"})
TREE_NOISE_SUFFIXES = (".pyc", ".pyo", ".pyd")
# 点目录按噪声处理（`.venv313` / `.idea` / `.pytest_c1` 这类本机产物名字枚举不完），
# 只放行确实描述仓库结构的少数几个；文件不在此列（`.gitignore` 这类配置仍有信息量）。
TREE_KEEP_DOT_DIRS = frozenset({".github", ".devcontainer"})


def _clean_repo_path(path: str) -> str:
    """规范化仓库相对路径；带控制字符（换行、制表……）的路径返回 ``""``。

    路径会逐行进提示词，一个带换行的文件名就等于往提示词里插了一行——宁可漏掉
    这种病态路径，也不让它改变注入段的结构。
    """
    cleaned = _normalize(str(path))
    if not cleaned:
        return ""
    if any(character < " " or character == "\x7f" for character in cleaned):
        return ""
    return cleaned


def render_pr_file_list(
    paths: list[str] | None,
    *,
    limit: int = PR_FILE_LIST_LIMIT,
    skipped: int | None = None,
    unavailable: str = "",
) -> str:
    """渲染「本次 PR 变更文件」注入段（B）。

    ``paths`` 为 ``None`` 表示清单没读到（``unavailable`` 只放原因短语，调用方
    传异常类名——绝不把网络细节或凭据带进提示词）；``skipped`` 是本次审查按规则
    跳过的文件数（run 记录里的数字，未知/为 0 就不写这一句）；``limit`` 之外的
    路径折叠成一行计数。
    """
    header = "## 本次 PR 变更文件"
    if paths is None:
        return f"{header}\n（未能读取变更文件清单：{unavailable or '未知原因'}）"
    listed = [cleaned for cleaned in map(_clean_repo_path, paths) if cleaned]
    summary = f"（共 {len(listed)} 个"
    if skipped:
        summary += f"，另有 {skipped} 个被本次审查跳过"
    summary += "）"
    lines = [f"{header}{summary}"]
    shown = listed[: max(0, limit)]
    lines.extend(f"- {path}" for path in shown)
    hidden = len(listed) - len(shown)
    if hidden > 0:
        lines.append(f"…（另有 {hidden} 个未列出，仅列出前 {len(shown)} 个）")
    lines.append("规则：只依据上面的路径回答「改了哪些文件」；上面没列出的路径不得臆测。")
    return "\n".join(lines)


def _is_noise_dir(name: str) -> bool:
    if name in TREE_NOISE_DIRS or name.endswith(".egg-info"):
        return True
    return name.startswith(".") and name not in TREE_KEEP_DOT_DIRS


def _is_noise_file(name: str) -> bool:
    return name in TREE_NOISE_FILES or name.lower().endswith(TREE_NOISE_SUFFIXES)


def _tree_index(paths: list[str]) -> dict[str, dict]:
    """把扁平路径列表折成嵌套字典（叶子是空 dict）；噪声与非法路径在这里剔除。"""
    root: dict[str, dict] = {}
    for raw in paths:
        path = _clean_repo_path(raw)
        if not path:
            continue
        parts = [part for part in path.split("/") if part and part != "."]
        if not parts or _is_noise_file(parts[-1]):
            continue
        if any(_is_noise_dir(part) for part in parts[:-1]):
            continue
        node = root
        for part in parts:
            node = node.setdefault(part, {})
    return root


def _count_tree_entries(node: dict[str, dict]) -> int:
    return sum(1 + _count_tree_entries(child) for child in node.values())


def _tree_lines(
    node: dict[str, dict],
    depth: int,
    max_depth: int,
    prefix: str,
    budget: int,
    max_children: int,
) -> list[str]:
    """在 ``budget`` 行以内渲染 ``node`` 的子项（深度受限）。

    同一层目录在前、文件在后；子项超过 ``max_children`` 的部分折叠成一行计数。
    行数按**兄弟均分**（``剩余预算 // 剩余子项``）：否则深度优先会把预算全喂给
    第一个大目录，后面的 `src/`、`tests/` 一个字都进不了注入——实测本仓库的
    `.agent-bus/` 正是这样吃光整棵树的。均分后每个兄弟至少露一次面，用不完的
    份额自然回流给后面的兄弟。
    """
    if budget <= 0:
        return []
    directories = sorted((name, child) for name, child in node.items() if child)
    files = sorted(name for name, child in node.items() if not child)
    children: list[tuple[str, dict | None]] = [*directories, *((name, None) for name in files)]
    shown = children[: max(0, max_children)]
    hidden = len(children) - len(shown)
    lines: list[str] = []
    for index, (name, child) in enumerate(shown):
        remaining = budget - len(lines)
        if remaining <= 0:
            hidden += len(shown) - index
            break
        if child is None:
            lines.append(f"{prefix}{name}")
            continue
        if depth >= max_depth:
            lines.append(f"{prefix}{name}/ …（{_count_tree_entries(child)} 项未展开）")
            continue
        share = max(1, remaining // (len(shown) - index))
        lines.append(f"{prefix}{name}/")
        lines.extend(
            _tree_lines(child, depth + 1, max_depth, prefix + "  ", share - 1, max_children)
        )
    if hidden > 0:
        lines.append(f"{prefix}…（另有 {hidden} 项未列出）")
    return lines


def render_repo_tree(
    paths: list[str] | None,
    *,
    sha: str = "",
    max_depth: int = REPO_TREE_MAX_DEPTH,
    max_entries: int = REPO_TREE_MAX_ENTRIES,
    max_children: int = REPO_TREE_MAX_CHILDREN_PER_DIR,
    unavailable: str = "",
) -> str:
    """渲染「仓库目录树」注入段（C）。

    ``paths`` 为 ``None`` 表示树没读到（与"读到了但为空"的 ``[]`` 分开）。行数预算
    在兄弟之间均分（见 `_tree_lines`），三种折叠都给数字，模型因此知道"还有内容"，
    不会把"没列出来"当成"不存在"：

    - 到达 ``max_depth`` 的目录：`name/ …（N 项未展开）`；
    - 同层子项超过 ``max_children``、或预算耗尽：`…（另有 N 项未列出）`；
    - 总行数仍超过 ``max_entries``（硬兜底）：末尾 `…（另有 N 行未列出）`。
    """
    header = "## 仓库目录树"
    if paths is None:
        return f"{header}\n（未能读取仓库目录树：{unavailable or '未知原因'}）"
    scope = f"head 提交 {sha[:8]}" if sha else "head 提交"
    lines = [
        f"{header}（{scope} · 深度 ≤{max_depth} · 最多 {max_entries} 行）",
        "（已排除 .git / node_modules / __pycache__ 等噪声与点目录；.github 等少数几个保留）",
    ]
    index = _tree_index(paths)
    if not index:
        lines.append("（该提交下没有可列出的文件）")
        return "\n".join(lines)
    body = _tree_lines(index, 1, max_depth, "", max_entries, max_children)
    shown = body[: max(0, max_entries)]
    lines.extend(shown)
    hidden = len(body) - len(shown)
    if hidden > 0:
        lines.append(f"…（另有 {hidden} 行未列出）")
    lines.append("规则：只依据上面的目录树回答结构问题；未展开/未列出的部分不得臆测。")
    return "\n".join(lines)
