"""跨文件符号索引：提取定义签名并定位跨文件引用。

这是跨文件影响分析的基础设施。它只做确定性、可解释的事情：

1. 从每个变更文件中提取函数/类/方法的**签名指纹**。
2. 在全部文件正文中定位某个符号被引用的位置。
3. 当同一个符号同时出现在“定义侧”和“引用侧”时，产生跨文件关系。

有了签名指纹，就可以在 PR 改变了某个被外部调用的接口时给出具体、
可核对的提示，而不是只做文件名/import 的模糊匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_pr_review.models.review_plan import CrossFileReference, InterfaceChange
from ai_pr_review.services.context_builder import FileContext, FunctionInfo


@dataclass(slots=True)
class SymbolDefinition:
    """一处符号定义。"""

    name: str
    kind: str  # "function" | "class" | "method"
    file: str
    line: int
    parameters: tuple[str, ...] = ()
    return_type: str | None = None
    is_async: bool = False
    base_classes: tuple[str, ...] = ()

    def signature(self) -> str:
        """生成稳定的签名指纹，用于前后对比。"""
        prefix = "async " if self.is_async else ""
        # 类没有参数列表，只比较基类；函数/方法比较参数与返回类型。
        if self.kind == "class":
            bases = f"({', '.join(self.base_classes)})" if self.base_classes else ""
            return f"{prefix}{self.name}{bases}"
        params = ", ".join(self.parameters)
        returns = f" -> {self.return_type}" if self.return_type else ""
        return f"{prefix}{self.name}({params}){returns}"


@dataclass(slots=True)
class FileSymbols:
    """单个文件的符号与引用信息。"""

    file: str
    definitions: list[SymbolDefinition] = field(default_factory=list)
    references: dict[str, list[int]] = field(default_factory=dict)


# 标识符引用匹配：避免匹配到更长标识符的一部分。
def _reference_pattern(symbol: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")


def _strip_comment_lines(source: str) -> list[str]:
    """移除注释行，避免把注释里的名字当成真实引用。"""
    kept: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", "/*")):
            kept.append("")
            continue
        kept.append(line)
    return kept


class SymbolIndex:
    """跨文件符号索引。"""

    def __init__(self, contexts: list[tuple[object, FileContext]]) -> None:
        self._files: list[FileSymbols] = []
        for file_diff, context in contexts:
            self._files.append(self._index_file(str(file_diff.filename), context))

    @property
    def files(self) -> list[FileSymbols]:
        return self._files

    def _index_file(self, filename: str, context: FileContext) -> FileSymbols:
        definitions: list[SymbolDefinition] = []
        seen_methods: set[str] = set()

        for class_info in context.classes:
            definitions.append(
                SymbolDefinition(
                    name=class_info.name,
                    kind="class",
                    file=filename,
                    line=class_info.start_line,
                    base_classes=tuple(class_info.parent_classes),
                )
            )
            for method_name in class_info.methods:
                # 方法签名由函数列表补齐；这里先登记名字以保证class的方法集完整。
                seen_methods.add(method_name)

        for function in context.functions:
            definitions.append(self._to_definition(filename, function, seen_methods))

        references = self._collect_references(context)
        return FileSymbols(file=filename, definitions=definitions, references=references)

    @staticmethod
    def _to_definition(
        filename: str, function: FunctionInfo, method_names: set[str]
    ) -> SymbolDefinition:
        kind = "method" if function.name in method_names else "function"
        return SymbolDefinition(
            name=function.name,
            kind=kind,
            file=filename,
            line=function.start_line,
            parameters=tuple(function.parameters),
            return_type=function.return_type,
            is_async=function.is_async,
        )

    @staticmethod
    def _collect_references(context: FileContext) -> dict[str, list[int]]:
        references: dict[str, list[int]] = {}
        import_lines = {line.strip() for line in context.imports if line.strip()}
        for line_number, line in enumerate(_strip_comment_lines(context.full_content or ""), 1):
            # import 行只是引入符号，并不代表调用点，单独排除以免混淆。
            if line.strip() in import_lines:
                continue
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line):
                references.setdefault(token, []).append(line_number)
        return references

    # ---- 查询 -----------------------------------------------------

    def definitions(self) -> list[SymbolDefinition]:
        return [
            definition for file_symbols in self._files for definition in file_symbols.definitions
        ]

    def cross_file_references(self) -> list[CrossFileReference]:
        """返回引用了其他文件所定义符号的位置。"""
        results: list[CrossFileReference] = []
        owners: dict[str, str] = {}
        for file_symbols in self._files:
            for definition in file_symbols.definitions:
                owners.setdefault(definition.name, file_symbols.file)

        for file_symbols in self._files:
            for symbol, owner in owners.items():
                if owner == file_symbols.file:
                    continue
                lines = file_symbols.references.get(symbol)
                if not lines:
                    continue
                for line in lines:
                    results.append(
                        CrossFileReference(
                            symbol=symbol,
                            file=owner,
                            line=line,
                            referencing_file=file_symbols.file,
                        )
                    )
        return results

    def compare_with(self, previous: dict[str, SymbolDefinition]) -> list[InterfaceChange]:
        """把当前定义与上一次（例如 base 版本）对比，找出接口变更。"""
        changes: list[InterfaceChange] = []
        current = {definition.name: definition for definition in self.definitions()}

        for name, definition in current.items():
            before = previous.get(name)
            if before is None:
                continue
            change = _diff_definition(before, definition)
            if change is not None:
                changes.append(change)

        for name, before in previous.items():
            if name in current:
                continue
            changes.append(
                InterfaceChange(
                    symbol=name,
                    kind=before.kind if before.kind != "method" else "method",
                    file=before.file,
                    line=before.line,
                    change="parameters_changed",
                    before=before.signature(),
                    after="<removed>",
                )
            )
        return changes

    def signature_map(self) -> dict[str, SymbolDefinition]:
        return {definition.name: definition for definition in self.definitions()}


def _diff_definition(before: SymbolDefinition, after: SymbolDefinition) -> InterfaceChange | None:
    """比较两个同名定义的接口差异，返回第一条有意义的变更。"""
    base = dict(symbol=after.name, kind=_change_kind(after), file=after.file, line=after.line)

    if before.parameters != after.parameters:
        return InterfaceChange(
            **base,
            change="parameters_changed",
            before=before.signature(),
            after=after.signature(),
        )
    if before.return_type != after.return_type:
        return InterfaceChange(
            **base,
            change="return_type_changed",
            before=before.signature(),
            after=after.signature(),
        )
    if before.is_async != after.is_async:
        return InterfaceChange(
            **base,
            change="became_async" if after.is_async else "stopped_being_async",
            before=before.signature(),
            after=after.signature(),
        )
    if before.base_classes != after.base_classes:
        return InterfaceChange(
            **base,
            change="base_classes_changed",
            before=before.signature(),
            after=after.signature(),
        )
    return None


def _change_kind(definition: SymbolDefinition) -> str:
    if definition.kind in {"function", "class", "method"}:
        return definition.kind
    return "function"


__all__ = ["FileSymbols", "SymbolDefinition", "SymbolIndex"]
