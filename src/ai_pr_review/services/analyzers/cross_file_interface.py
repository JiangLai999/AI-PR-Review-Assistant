"""跨文件接口影响分析。

回答一个具体问题：**这次 PR 改变的接口，是否会破坏其它文件里的调用方？**

与只做 import/文件名模糊匹配的旧实现相比，这里基于符号签名：

1. 索引所有变更文件的函数/类签名。
2. 与 PR base 版本的签名对比，得到具体的接口变更。
3. 找出真正引用了这些符号的其它文件。
4. 只在“接口确实变了 + 确实有外部引用”时报告，降低误报。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.models.review_plan import (
    CrossFileImpact,
    CrossFileReference,
    InterfaceChange,
)
from ai_pr_review.services.analyzers.symbol_index import SymbolDefinition, SymbolIndex
from ai_pr_review.services.context_builder import FileContext

# 这些变更会直接破坏调用方，因此置信度更高。
BREAKING_CHANGES = {
    "parameters_changed",
    "return_type_changed",
    "became_async",
    "stopped_being_async",
    "base_classes_changed",
}

CHANGE_LABELS = {
    "parameters_changed": "参数列表变化",
    "return_type_changed": "返回类型变化",
    "became_async": "变为 async",
    "stopped_being_async": "不再是 async",
    "base_classes_changed": "基类变化",
    "added": "新增定义",
}


@dataclass(slots=True)
class InterfaceImpact:
    """一条可核对的跨文件接口影响。"""

    change: InterfaceChange
    affected_files: list[str] = field(default_factory=list)
    references: list[CrossFileReference] = field(default_factory=list)

    @property
    def is_breaking(self) -> bool:
        return self.change.change in BREAKING_CHANGES and bool(self.references)

    def to_dict(self) -> dict:
        return {
            "symbol": self.change.symbol,
            "kind": self.change.kind,
            "file": self.change.file,
            "line": self.change.line,
            "change": self.change.change,
            "label": CHANGE_LABELS.get(self.change.change, self.change.change),
            "before": self.change.before,
            "after": self.change.after,
            "affected_files": sorted(self.affected_files),
            "references": [
                {"file": reference.referencing_file, "line": reference.line}
                for reference in self.references
            ],
            "is_breaking": self.is_breaking,
        }

    def describe(self) -> str:
        label = CHANGE_LABELS.get(self.change.change, self.change.change)
        targets = ", ".join(sorted(self.affected_files)) or "<no external caller>"
        return (
            f"{self.change.symbol} {label} in {self.change.file}:"
            f"{self.change.line} ({self.change.before} -> {self.change.after}); "
            f"external references: {targets}"
        )


class CrossFileInterfaceAnalyzer:
    """基于符号签名的跨文件影响分析。"""

    def analyze(
        self,
        contexts: list[tuple[FileDiff, FileContext]],
        base_signatures: dict[str, SymbolDefinition] | None = None,
    ) -> list[InterfaceImpact]:
        """返回接口变更及其外部引用。

        `base_signatures` 为 PR base 版本的同名符号签名；缺省时只做
        “符号定义 + 外部引用”的关系分析，不报告签名变化。
        """
        if len(contexts) < 2:
            return []

        index = SymbolIndex(contexts)
        references = index.cross_file_references()
        by_symbol: dict[str, list[CrossFileReference]] = {}
        for reference in references:
            by_symbol.setdefault(reference.symbol, []).append(reference)

        impacts: list[InterfaceImpact] = []
        if base_signatures:
            for change in index.compare_with(base_signatures):
                refs = by_symbol.get(change.symbol, [])
                impacts.append(
                    InterfaceImpact(
                        change=change,
                        affected_files=sorted({ref.referencing_file for ref in refs}),
                        references=refs,
                    )
                )
        return impacts

    @staticmethod
    def build_relationship_map(
        contexts: list[tuple[FileDiff, FileContext]],
    ) -> tuple[list[CrossFileImpact], list[CrossFileReference]]:
        """返回文件级关系图与跨文件引用，供报告与提示词使用。"""
        index = SymbolIndex(contexts)
        references = index.cross_file_references()

        related_by_file: dict[str, set[str]] = {}
        signals_by_file: dict[str, set[str]] = {}
        for reference in references:
            related_by_file.setdefault(reference.file, set()).add(reference.referencing_file)
            signals_by_file.setdefault(reference.file, set()).add(
                f"symbol-referenced:{reference.symbol}"
            )

        impacts: list[CrossFileImpact] = []
        for file_symbols in index.files:
            related = sorted(related_by_file.get(file_symbols.file, set()))
            signals = sorted(signals_by_file.get(file_symbols.file, set()))
            if not related and not signals:
                continue
            impacts.append(
                CrossFileImpact(
                    source_file=file_symbols.file,
                    related_files=related,
                    signals=signals,
                    requires_review=bool(related),
                )
            )
        return impacts, references


__all__ = [
    "BREAKING_CHANGES",
    "CHANGE_LABELS",
    "CrossFileInterfaceAnalyzer",
    "InterfaceImpact",
]
