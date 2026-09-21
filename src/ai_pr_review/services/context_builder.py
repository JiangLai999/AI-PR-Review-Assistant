"""Context Builder 模块。

负责为单个变更文件构建可供后续 AI 审查使用的上下文：

1. Layer 1: diff + 变更行前后固定窗口。
2. Layer 2: imports / functions / classes 等 AST 风格上下文。
3. 三级解析 fallback: tree-sitter -> regex -> diff-only。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from ai_pr_review.config import ContextBuilderConfig

SUPPORTED_LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# tree-sitter 语法包按需导入，未安装时自动退化为正则提取。
TREE_SITTER_GRAMMAR_MODULES = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
}

_TREE_SITTER_LANGUAGE_CACHE: dict[str, object | None] = {}


def _load_tree_sitter_language(language: str):
    """加载并缓存 tree-sitter 语法；不可用时返回 None。"""
    if language in _TREE_SITTER_LANGUAGE_CACHE:
        return _TREE_SITTER_LANGUAGE_CACHE[language]

    resolved: object | None = None
    module_name = TREE_SITTER_GRAMMAR_MODULES.get(language)
    if module_name is not None:
        try:
            import importlib

            from tree_sitter import Language

            grammar_module = importlib.import_module(module_name)
            capsule = (
                grammar_module.language_typescript()
                if language == "typescript"
                else grammar_module.language()
            )
            resolved = Language(capsule)
        except Exception:
            resolved = None

    _TREE_SITTER_LANGUAGE_CACHE[language] = resolved
    return resolved


class FunctionInfo(BaseModel):
    """函数信息。"""

    name: str
    start_line: int
    end_line: int
    parameters: list[str] = Field(default_factory=list)
    return_type: str | None = None
    is_async: bool = False


class ClassInfo(BaseModel):
    """类信息。"""

    name: str
    start_line: int
    end_line: int
    methods: list[str] = Field(default_factory=list)
    parent_classes: list[str] = Field(default_factory=list)


class ASTContext(BaseModel):
    """AST 提取结果。"""

    imports: list[str] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    parse_mode: str = "fallback"


class FileContext(BaseModel):
    """单个文件的完整上下文。"""

    file_path: str
    language: str
    diff: str
    diff_with_context: str
    imports: list[str] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    parse_mode: str
    full_content: str = ""


class ContextBuilder:
    """为变更文件生成结构化上下文。"""

    def __init__(self, config: ContextBuilderConfig | None = None):
        self._config = config or ContextBuilderConfig()

    def build_context(self, file_path: str, diff: str, full_content: str) -> FileContext:
        """构建文件上下文。"""
        language = self.detect_language(file_path)
        ast_context = self.extract_ast_context(file_path, full_content, language)
        diff_with_context = self.extract_diff_context(diff, full_content)

        return FileContext(
            file_path=file_path,
            language=language,
            diff=diff,
            diff_with_context=diff_with_context,
            imports=ast_context.imports,
            functions=ast_context.functions,
            classes=ast_context.classes,
            parse_mode=ast_context.parse_mode,
            full_content=full_content,
        )

    def extract_ast_context(
        self,
        file_path: str,
        content: str,
        language: str | None = None,
    ) -> ASTContext:
        """提取 AST 风格上下文，按三级 fallback 退化。"""
        resolved_language = language or self.detect_language(file_path)

        if self._config.enable_tree_sitter:
            try:
                return self._tree_sitter_extract(content, resolved_language)
            except Exception:
                pass

        try:
            return self._regex_extract(content, resolved_language)
        except Exception:
            return ASTContext(parse_mode="fallback")

    def detect_language(self, file_path: str) -> str:
        """根据扩展名识别语言。"""
        suffix = PurePosixPath(file_path).suffix.lower()
        return SUPPORTED_LANGUAGE_EXTENSIONS.get(suffix, "text")

    def extract_diff_context(self, diff: str, full_content: str) -> str:
        """从 unified diff 中抽取变更行及其前后窗口。"""
        if not diff:
            return ""

        file_lines = full_content.splitlines()
        changed_line_numbers = self._extract_changed_line_numbers(diff)
        if not changed_line_numbers:
            return diff

        windows = self._merge_line_windows(changed_line_numbers, len(file_lines))
        rendered_sections: list[str] = []
        for start_line, end_line in windows:
            rendered_sections.append(f"@@ context {start_line}:{end_line} @@")
            for line_number in range(start_line, end_line + 1):
                line_content = (
                    file_lines[line_number - 1] if line_number - 1 < len(file_lines) else ""
                )
                prefix = ">" if line_number in changed_line_numbers else " "
                rendered_sections.append(f"{prefix}{line_number:>4}: {line_content}")

        return "\n".join(rendered_sections)

    def _tree_sitter_extract(self, content: str, language: str) -> ASTContext:
        """使用 tree-sitter 语法树提取结构化上下文。

        语法包未安装或语言不受支持时抛错，交由 regex fallback 接管。
        """
        if language == "text":
            return ASTContext(parse_mode="fallback")

        grammar = _load_tree_sitter_language(language)
        if grammar is None:
            raise RuntimeError(f"tree-sitter grammar is unavailable for language: {language}")

        from tree_sitter import Parser

        payload = content.encode("utf-8")
        tree = Parser(grammar).parse(payload)

        imports: list[str] = []
        functions: list[FunctionInfo] = []
        classes: list[ClassInfo] = []

        if language == "python":
            self._collect_python_tree(tree.root_node, payload, imports, functions, classes)
        else:
            self._collect_ecmascript_tree(tree.root_node, payload, imports, functions, classes)

        return ASTContext(
            imports=imports[: self._config.max_ast_items],
            functions=functions[: self._config.max_ast_items],
            classes=classes[: self._config.max_ast_items],
            parse_mode="tree-sitter",
        )

    def _collect_python_tree(
        self,
        root: object,
        payload: bytes,
        imports: list[str],
        functions: list[FunctionInfo],
        classes: list[ClassInfo],
    ) -> None:
        """遍历 Python 语法树，按声明层级收集符号。"""
        for node in root.named_children:
            node_type = node.type
            if node_type in {"import_statement", "import_from_statement"}:
                imports.append(self._node_text(payload, node).strip())

        for node in root.named_children:
            if node.type != "class_definition":
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            superclasses = node.child_by_field_name("superclasses")
            parents = [
                self._node_text(payload, child).strip()
                for child in (superclasses.named_children if superclasses else [])
                if self._node_text(payload, child).strip()
            ]
            body = node.child_by_field_name("body")
            methods: list[str] = []
            for child in body.named_children if body else []:
                if child.type != "function_definition":
                    continue
                method_name = child.child_by_field_name("name")
                if method_name is None:
                    continue
                methods.append(self._node_text(payload, method_name))
                function = self._python_function(payload, child)
                if function is not None:
                    functions.append(function)
            classes.append(
                ClassInfo(
                    name=self._node_text(payload, name_node),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    methods=methods,
                    parent_classes=parents,
                )
            )

        for node in root.named_children:
            if node.type != "function_definition":
                continue
            function = self._python_function(payload, node)
            if function is not None:
                functions.append(function)

    def _python_function(self, payload: bytes, node: object) -> FunctionInfo | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        parameters_node = node.child_by_field_name("parameters")
        return_type_node = node.child_by_field_name("return_type")
        return FunctionInfo(
            name=self._node_text(payload, name_node),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parameters=self._python_parameters(payload, parameters_node),
            return_type=self._clean_return_type(
                self._node_text(payload, return_type_node) if return_type_node else None
            ),
            is_async=self._has_child_token(node, "async"),
        )

    def _python_parameters(self, payload: bytes, parameters_node: object) -> list[str]:
        if parameters_node is None:
            return []
        parameters: list[str] = []
        for child in parameters_node.named_children:
            if child.type in {"identifier", "typed_parameter", "typed_default_parameter"}:
                parameters.append(self._node_text(payload, child).strip())
            elif child.type == "default_parameter":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    parameters.append(self._node_text(payload, name_node).strip())
        return parameters

    def _collect_ecmascript_tree(
        self,
        root: object,
        payload: bytes,
        imports: list[str],
        functions: list[FunctionInfo],
        classes: list[ClassInfo],
    ) -> None:
        """遍历 JavaScript/TypeScript 语法树，按声明层级收集符号。"""
        for node in root.named_children:
            node = self._unwrap_export_statement(node)
            if node.type in {"import_statement", "lexical_declaration", "variable_declaration"}:
                text = self._node_text(payload, node).strip()
                if node.type == "import_statement" or "require(" in text:
                    imports.append(text)
            if node.type == "class_declaration":
                self._ecmascript_class(payload, node, functions, classes)

        for node in root.named_children:
            node = self._unwrap_export_statement(node)
            if node.type == "function_declaration":
                function = self._ecmascript_function(payload, node, node)
                if function is not None:
                    functions.append(function)
            elif node.type in {"lexical_declaration", "variable_declaration"}:
                for declarator in node.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    value_node = declarator.child_by_field_name("value")
                    if value_node is None or value_node.type != "arrow_function":
                        continue
                    function = self._ecmascript_function(payload, declarator, value_node)
                    if function is not None:
                        functions.append(function)

    def _ecmascript_class(
        self,
        payload: bytes,
        node: object,
        functions: list[FunctionInfo],
        classes: list[ClassInfo],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        parents: list[str] = []
        for child in node.named_children:
            if child.type == "class_heritage":
                text = self._node_text(payload, child)
                heritage = re.sub(r"^\s*extends\s+", "", text).strip()
                if heritage:
                    parents.extend(self._split_csv(heritage))

        body = node.child_by_field_name("body")
        if body is None:
            body = next(
                (child for child in node.named_children if child.type == "class_body"), None
            )
        methods: list[str] = []
        for child in body.named_children if body else []:
            if child.type != "method_definition":
                continue
            method_name = child.child_by_field_name("name")
            if method_name is None:
                continue
            methods.append(self._node_text(payload, method_name))
            function = self._ecmascript_function(payload, child, child)
            if function is not None:
                functions.append(function)

        classes.append(
            ClassInfo(
                name=self._node_text(payload, name_node),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                methods=methods,
                parent_classes=parents,
            )
        )

    def _ecmascript_function(
        self, payload: bytes, name_source: object, signature_source: object
    ) -> FunctionInfo | None:
        name = self._ecmascript_name(payload, name_source)
        if not name:
            return None
        parameters_node = signature_source.child_by_field_name("parameters")
        return_type_node = signature_source.child_by_field_name("return_type")

        parameters: list[str] = []
        for child in parameters_node.named_children if parameters_node else []:
            text = self._node_text(payload, child).strip()
            if text:
                parameters.append(text)

        return FunctionInfo(
            name=name,
            start_line=name_source.start_point[0] + 1,
            end_line=name_source.end_point[0] + 1,
            parameters=parameters,
            return_type=self._clean_return_type(
                self._node_text(payload, return_type_node) if return_type_node else None
            ),
            is_async=self._has_child_token(signature_source, "async"),
        )

    def _ecmascript_name(self, payload: bytes, node: object) -> str:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return self._node_text(payload, name_node)
        return ""

    @staticmethod
    def _unwrap_export_statement(node: object) -> object:
        """展开 `export ...` 包装节点，取出内部声明。"""
        while node.type == "export_statement":
            inner = next(
                (
                    child
                    for child in node.named_children
                    if child.type
                    in {
                        "class_declaration",
                        "function_declaration",
                        "lexical_declaration",
                        "variable_declaration",
                        "interface_declaration",
                        "type_alias_declaration",
                    }
                ),
                None,
            )
            if inner is None:
                break
            node = inner
        return node

    @staticmethod
    def _node_text(payload: bytes, node: object) -> str:
        return payload[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _has_child_token(node: object, token: str) -> bool:
        return any(child.type == token for child in node.children)

    def _regex_extract(self, content: str, language: str) -> ASTContext:
        """使用正则从源码中提取结构化上下文。"""
        if language == "python":
            return self._regex_extract_python(content)
        if language in {"javascript", "typescript"}:
            return self._regex_extract_javascript_family(content, language)
        return ASTContext(parse_mode="fallback")

    def _regex_extract_python(self, content: str) -> ASTContext:
        lines = content.splitlines()
        imports: list[str] = []
        functions: list[FunctionInfo] = []
        classes: list[ClassInfo] = []

        import_pattern = re.compile(r"^\s*(?:from\s+[\w\.]+\s+import\s+.+|import\s+.+)$")
        function_pattern = re.compile(
            r"^(?P<indent>\s*)(?P<async>async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*(?:->\s*(?P<return>[^:]+))?:"
        )
        class_pattern = re.compile(
            r"^(?P<indent>\s*)class\s+(?P<name>[A-Za-z_]\w*)\s*(?:\((?P<parents>[^)]*)\))?:"
        )

        line_number = 1
        while line_number <= len(lines):
            line = lines[line_number - 1]

            if import_pattern.match(line):
                imports.append(line.strip())

            class_match = class_pattern.match(line)
            if class_match:
                indent = len(class_match.group("indent"))
                end_line = self._find_python_block_end(lines, line_number, indent)
                methods = self._collect_python_class_methods(
                    lines, line_number + 1, end_line, indent
                )
                parents = self._split_csv(class_match.group("parents") or "")
                classes.append(
                    ClassInfo(
                        name=class_match.group("name"),
                        start_line=line_number,
                        end_line=end_line,
                        methods=methods,
                        parent_classes=parents,
                    )
                )

            function_match = function_pattern.match(line)
            if function_match:
                indent = len(function_match.group("indent"))
                functions.append(
                    FunctionInfo(
                        name=function_match.group("name"),
                        start_line=line_number,
                        end_line=self._find_python_block_end(lines, line_number, indent),
                        parameters=self._split_csv(function_match.group("params") or ""),
                        return_type=(function_match.group("return") or None),
                        is_async=bool(function_match.group("async")),
                    )
                )

            line_number += 1

        return ASTContext(
            imports=imports[: self._config.max_ast_items],
            functions=functions[: self._config.max_ast_items],
            classes=classes[: self._config.max_ast_items],
            parse_mode="regex",
        )

    def _regex_extract_javascript_family(self, content: str, language: str) -> ASTContext:
        lines = content.splitlines()
        imports: list[str] = []
        functions: list[FunctionInfo] = []
        classes: list[ClassInfo] = []

        import_pattern = re.compile(
            r"^\s*(?:import\s+.+\s+from\s+['\"].+['\"];?|const\s+.+\s*=\s*require\(.+\);?)\s*$"
        )
        function_patterns = [
            re.compile(
                r"^(?P<indent>\s*)(?P<async>async\s+)?function\s+(?P<name>[A-Za-z_$]\w*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<return>[^\{]+))?\s*\{"
            ),
            re.compile(
                r"^(?P<indent>\s*)(?:export\s+)?(?P<async>async\s+)?const\s+(?P<name>[A-Za-z_$]\w*)\s*=\s*(?:async\s+)?\((?P<params>[^)]*)\)\s*(?::\s*(?P<return>[^=]+))?\s*=>\s*\{"
            ),
            re.compile(
                r"^(?P<indent>\s*)(?:export\s+)?(?P<async>async\s+)?(?P<name>[A-Za-z_$]\w*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<return>[^\{]+))?\s*\{"
            ),
        ]
        class_pattern = re.compile(
            r"^(?P<indent>\s*)(?:export\s+)?class\s+(?P<name>[A-Za-z_$]\w*)(?:\s+extends\s+(?P<parents>[A-Za-z_$][\w.$]*))?\s*\{"
        )
        method_pattern = re.compile(
            r"^\s*(?:async\s+)?(?P<name>[A-Za-z_$]\w*)\s*\((?P<params>[^)]*)\)\s*(?::\s*[^\{]+)?\s*\{"
        )

        line_number = 1
        while line_number <= len(lines):
            line = lines[line_number - 1]

            if import_pattern.match(line):
                imports.append(line.strip())

            class_match = class_pattern.match(line)
            if class_match:
                end_line = self._find_brace_block_end(lines, line_number)
                methods = self._collect_brace_class_methods(
                    lines,
                    line_number + 1,
                    end_line,
                    method_pattern,
                )
                parents = self._split_csv(class_match.group("parents") or "")
                classes.append(
                    ClassInfo(
                        name=class_match.group("name"),
                        start_line=line_number,
                        end_line=end_line,
                        methods=methods,
                        parent_classes=parents,
                    )
                )

            for pattern in function_patterns:
                function_match = pattern.match(line)
                if function_match:
                    is_async = bool(function_match.groupdict().get("async")) or "= async" in line
                    functions.append(
                        FunctionInfo(
                            name=function_match.group("name"),
                            start_line=line_number,
                            end_line=self._find_brace_block_end(lines, line_number),
                            parameters=self._split_csv(function_match.group("params") or ""),
                            return_type=self._clean_return_type(
                                function_match.groupdict().get("return")
                            ),
                            is_async=is_async,
                        )
                    )
                    break

            line_number += 1

        return ASTContext(
            imports=imports[: self._config.max_ast_items],
            functions=functions[: self._config.max_ast_items],
            classes=classes[: self._config.max_ast_items],
            parse_mode="regex",
        )

    def _extract_changed_line_numbers(self, diff: str) -> set[int]:
        """解析 unified diff，得到新文件中的变更行号。"""
        changed_line_numbers: set[int] = set()
        current_new_line = 0
        in_hunk = False

        for raw_line in diff.splitlines():
            if raw_line.startswith("@@"):
                match = re.match(
                    r"@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", raw_line
                )
                if not match:
                    continue
                current_new_line = int(match.group("start"))
                in_hunk = True
                continue

            if not in_hunk:
                continue

            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                changed_line_numbers.add(current_new_line)
                current_new_line += 1
                continue

            if raw_line.startswith("-") and not raw_line.startswith("---"):
                changed_line_numbers.add(max(current_new_line, 1))
                continue

            if raw_line.startswith(" "):
                current_new_line += 1
                continue

            if raw_line.startswith("\\"):
                continue

        return changed_line_numbers

    def _merge_line_windows(
        self, changed_lines: set[int], total_lines: int
    ) -> list[tuple[int, int]]:
        """为变更行生成前后窗口，并合并重叠区间。"""
        if not changed_lines or total_lines <= 0:
            return []

        windows = []
        for changed_line in sorted(changed_lines):
            start = max(1, changed_line - self._config.context_lines)
            end = min(total_lines, changed_line + self._config.context_lines)
            windows.append((start, end))

        merged: list[tuple[int, int]] = []
        for start, end in windows:
            if not merged or start > merged[-1][1] + 1:
                merged.append((start, end))
                continue
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))

        return merged

    def _find_python_block_end(self, lines: list[str], start_line: int, indent: int) -> int:
        """根据缩进确定 Python 代码块结束位置。"""
        end_line = start_line
        for index in range(start_line, len(lines)):
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                end_line = index + 1
                continue

            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent <= indent:
                break
            end_line = index + 1

        return end_line

    def _collect_python_class_methods(
        self,
        lines: list[str],
        start_line: int,
        end_line: int,
        class_indent: int,
    ) -> list[str]:
        """收集 Python 类方法名。"""
        method_pattern = re.compile(
            r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\("
        )
        methods: list[str] = []
        for index in range(start_line - 1, end_line):
            match = method_pattern.match(lines[index])
            if not match:
                continue
            indent = len(match.group("indent"))
            if indent > class_indent:
                methods.append(match.group("name"))
        return methods

    def _find_brace_block_end(self, lines: list[str], start_line: int) -> int:
        """根据花括号平衡确定 JS/TS 代码块结束位置。"""
        brace_depth = 0
        started = False

        for index in range(start_line - 1, len(lines)):
            line = self._strip_line_comments(lines[index])
            for char in line:
                if char == "{":
                    brace_depth += 1
                    started = True
                elif char == "}":
                    brace_depth -= 1
                    if started and brace_depth <= 0:
                        return index + 1

        return len(lines)

    def _collect_brace_class_methods(
        self,
        lines: list[str],
        start_line: int,
        end_line: int,
        method_pattern: re.Pattern[str],
    ) -> list[str]:
        """收集 JS/TS 类中的方法名。"""
        methods: list[str] = []
        for index in range(start_line - 1, min(end_line, len(lines))):
            match = method_pattern.match(lines[index])
            if not match:
                continue
            name = match.group("name")
            if name != "constructor":
                methods.append(name)
        return methods

    def _split_csv(self, value: str) -> list[str]:
        """拆分逗号分隔字段。"""
        if not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def _clean_return_type(self, value: str | None) -> str | None:
        """清理返回类型字符串。"""
        if value is None:
            return None
        cleaned = value.strip().lstrip(":").strip()
        return cleaned or None

    def _strip_line_comments(self, line: str) -> str:
        """粗略去除单行注释，减少括号计数误判。"""
        comment_index = line.find("//")
        if comment_index == -1:
            return line
        return line[:comment_index]
