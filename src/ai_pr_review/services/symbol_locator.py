"""L2 符号级定位：trees + 按需 contents + 本地 grep。

设计依据见 ``docs/DEV_RECORD.md``：GitHub code search 在实测窗口内恒 0 命中
且只有 10/min 配额，主路径必须是 trees + 逐文件读取 + 本地标识符边界匹配。

本模块刻意不接触 GitHub API、不读配置：文件树与文件内容全部通过构造注入，
便于单测与后续在编排器侧接上 ``PRFetcher``。任何异常一律降级为「已收集到的
结果」，绝不向上抛——远端默认分支可能落后本地，「找不到」必须如实返回空，
不得臆测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ai_pr_review.services.repo_context import SOURCE_EXTENSIONS, RepoCache

# 长行截断上限：snippet 只用于人工核对，不需要整行。
SNIPPET_MAX_CHARS = 200

# 标识符边界匹配：避免命中更长标识符的一部分（与 symbol_index._reference_pattern 同思路）。
_IDENTIFIER_EDGE = r"(?<![A-Za-z0-9_]){symbol}(?![A-Za-z0-9_])"


@dataclass(slots=True)
class SymbolLocation:
    """仓库中一处符号引用位置。"""

    path: str
    line: int
    snippet: str
    source: str = "repo"


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("/")


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _symbol_tokens(symbol: str) -> list[str]:
    """把标识符拆成小写词元：``buildReviewContext`` -> ``[build, review, context]``。"""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", symbol)
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return [token.lower() for token in spaced.split() if token]


def _candidate_sort_key(path: str, symbol: str) -> tuple[int, str]:
    """稳定排序：文件名启发式打分优先，同分按路径字典序。

    打分只用文件名（不含目录）：定义/调用方文件常以符号关键词命名
    （见 recon §2.3(3a) 的 top3 启发式），先读它们能在 ``max_requests``
    预算内更早命中。分数固定、与扫描顺序无关，保证结果可复现。
    """
    stem = path.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem_lower = stem.lower()
    symbol_lower = symbol.lower()
    score = 0
    if symbol_lower in stem_lower:
        score += 2
    for token in _symbol_tokens(symbol):
        if len(token) >= 3 and token in stem_lower:
            score += 1
    return (-score, path)


def _truncated_snippet(line: str) -> str:
    cleaned = line.rstrip("\n\r")
    if len(cleaned) <= SNIPPET_MAX_CHARS:
        return cleaned
    return cleaned[: SNIPPET_MAX_CHARS - 1] + "…"


def _reference_pattern(symbol: str) -> re.Pattern[str]:
    return re.compile(_IDENTIFIER_EDGE.format(symbol=re.escape(symbol)))


class RepoSymbolLocator:
    """在仓库文件树里定位符号引用点。

    纯依赖注入：``read_tree`` 返回全部仓库相对路径，``read_file`` 返回单文件
    全文（读不到返回 ``None``）。``cache`` 复用 ``repo_context.RepoCache`` 协议，
    按路径缓存文件正文；缓存命中不计入 ``read_file`` 次数。
    """

    def __init__(
        self,
        read_tree: Callable[[], list[str]],
        read_file: Callable[[str], str | None],
        cache: RepoCache | None = None,
        max_requests: int = 15,
        max_results_per_symbol: int = 5,
    ) -> None:
        self._read_tree = read_tree
        self._read_file = read_file
        self._cache = cache
        self.max_requests = max(0, max_requests)
        self.max_results_per_symbol = max(0, max_results_per_symbol)

    def locate(self, symbol: str, *, exclude_paths: set[str] | None = None) -> list[SymbolLocation]:
        """返回符号引用点；任何异常降级为已收集结果，绝不向上抛。"""
        name = (symbol or "").strip()
        if not name or self.max_results_per_symbol <= 0 or self.max_requests <= 0:
            return []

        try:
            pattern = _reference_pattern(name)
        except re.error:
            return []

        try:
            excluded = {_normalize(item) for item in (exclude_paths or set())}
        except Exception:
            excluded = set()

        try:
            candidates = self._candidates(name, excluded)
        except Exception:
            return []

        results: list[SymbolLocation] = []
        reads = 0
        for path in candidates:
            if len(results) >= self.max_results_per_symbol:
                break
            if reads >= self.max_requests:
                break

            content, from_cache = self._load(path)
            if content is None:
                continue
            if not from_cache:
                reads += 1

            try:
                hits = self._grep(path, content, pattern)
            except Exception:
                # 单文件正则/解码失败：跳过该文件，继续已收集结果。
                continue
            for location in hits:
                results.append(location)
                if len(results) >= self.max_results_per_symbol:
                    break

        return results

    # ---- 内部 -----------------------------------------------------

    def _candidates(self, symbol: str, excluded: set[str]) -> list[str]:
        try:
            tree = list(self._read_tree() or [])
        except Exception:
            return []
        paths: list[str] = []
        seen: set[str] = set()
        for raw in tree:
            try:
                path = _normalize(str(raw))
            except Exception:
                continue
            if not path or path in seen or path in excluded:
                continue
            if _extension(path) not in SOURCE_EXTENSIONS:
                continue
            seen.add(path)
            paths.append(path)
        paths.sort(key=lambda item: _candidate_sort_key(item, symbol))
        return paths

    def _load(self, path: str) -> tuple[str | None, bool]:
        """读单文件：先缓存；缓存未命中再调 ``read_file`` 并回写缓存。"""
        if self._cache is not None:
            try:
                cached = self._cache.get(path)
            except Exception:
                cached = None
            if cached is not None:
                return cached, True
        try:
            content = self._read_file(path)
        except Exception:
            return None, False
        if content is None:
            return None, False
        if self._cache is not None:
            try:
                self._cache.put(path, content)
            except Exception:
                pass
        return content, False

    def _grep(self, path: str, content: str, pattern: re.Pattern[str]) -> list[SymbolLocation]:
        locations: list[SymbolLocation] = []
        for line_number, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                locations.append(
                    SymbolLocation(
                        path=path,
                        line=line_number,
                        snippet=_truncated_snippet(line),
                        source="repo",
                    )
                )
        return locations


def changed_symbols_from_impacts(impacts: list[object]) -> list[str]:
    """从接口影响列表取出有签名变化的符号名（保持顺序、去重）。

    同时接受两种既有形状：
    - ``InterfaceImpact``（``.change.symbol``，``CrossFileInterfaceAnalyzer`` 产物）
    - ``InterfaceChange``（``.symbol``，``SymbolIndex.compare_with`` 产物）

    复用 ``analyzers/symbol_index.py`` 的签名对比能力，不重复实现。调用方只在
    该列表非空时触发定位。
    """
    names: list[str] = []
    seen: set[str] = set()
    for impact in impacts or []:
        symbol = getattr(impact, "symbol", "")
        if not symbol:
            change = getattr(impact, "change", None)
            symbol = getattr(change, "symbol", "") if change is not None else ""
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        names.append(symbol)
    return names


__all__ = [
    "RepoSymbolLocator",
    "SymbolLocation",
    "changed_symbols_from_impacts",
]
