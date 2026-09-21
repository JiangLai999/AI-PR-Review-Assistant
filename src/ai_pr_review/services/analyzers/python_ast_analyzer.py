"""基于 Python AST 的确定性规则检查。

这些规则补充 `StaticAnalyzer` 的逐行正则检查：正则只能看到单行文本，
而可变默认参数、裸异常捕获、资源泄漏、危险反序列化等问题需要看到语法
结构才能可靠判定。

设计约束：

1. 只对“变更行”报告问题，保证 Finding 能通过证据校验。
2. 不引入第三方依赖，只使用标准库 `ast`。
3. 解析失败时静默返回空结果，由调用方继续使用逐行规则。
"""

from __future__ import annotations

import ast
import hashlib
import re
from typing import Any

from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.prompt_assembler import Finding

# 支持安全反序列化的关键字，出现时不再报告。
SAFE_DESERIALIZATION_LOADERS = ("safe_load", "SafeLoader", "CSafeLoader")

# 危险反序列化入口：(模块, 方法) -> 说明。
RISKY_DESERIALIZERS = {
    ("pickle", "loads"): "pickle",
    ("pickle", "load"): "pickle",
    ("cPickle", "loads"): "pickle",
    ("dill", "loads"): "dill",
    ("marshal", "loads"): "marshal",
    ("shelve", "open"): "shelve",
}

# 资源泄漏检测中视为“已释放”的调用名。
RESOURCE_RELEASE_CALLS = ("close", "release", "dispose")

# open() 的常见包装函数，避免把工具函数里的临时用法全部报出来。
RESOURCE_ACQUIRING_CALLS = ("open", "socket", "urlopen", "Popen", "connect")


class PythonAstAnalyzer:
    """对变更行执行 Python AST 级规则检查。"""

    def analyze(self, file_diff: FileDiff, context: FileContext) -> list[Finding]:
        if context.language != "python":
            return []

        source = getattr(context, "full_content", "") or ""
        if not source.strip():
            return []

        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return []

        changed_lines = self._changed_lines(file_diff.patch or "")
        if not changed_lines:
            return []

        analyzer = _RuleVisitor(file_diff.filename, source, changed_lines)
        analyzer.visit(tree)
        analyzer.report_unclosed_resources()
        return analyzer.findings

    @staticmethod
    def _changed_lines(patch: str) -> set[int]:
        """从 unified diff 中解析新增行的行号。"""
        changed: set[int] = set()
        current = 0
        in_hunk = False
        for raw_line in patch.splitlines():
            match = _HUNK_PATTERN.match(raw_line)
            if match:
                current = int(match.group(1))
                in_hunk = True
                continue
            if not in_hunk or raw_line.startswith("+++"):
                continue
            if raw_line.startswith("+"):
                changed.add(current)
                current += 1
            elif raw_line.startswith("-") or raw_line.startswith("\\"):
                continue
            else:
                current += 1
        return changed


_HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

_MUTABLE_DEFAULT_TYPES = (ast.List, ast.Dict, ast.Set)
_MUTABLE_DEFAULT_CALLS = ("list", "dict", "set", "bytearray", "OrderedDict", "defaultdict")
_MUTABLE_DEFAULT_ATTRS = ("deque",)


class _RuleVisitor(ast.NodeVisitor):
    """收集 AST 规则命中结果。"""

    def __init__(self, filename: str, source: str, changed_lines: set[int]) -> None:
        self._filename = filename
        self._source = source
        self._changed_lines = changed_lines
        self.findings: list[Finding] = []
        self._acquired: dict[str, ast.Call] = {}
        self._released: set[str] = set()

    # ---- 访问入口 -------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._check_function(node)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self._check_bare_except(node)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        self._check_lost_traceback(node)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        if isinstance(node.exc, ast.Call) and _call_name(node.exc) == "ValueError":
            self._check_unsafe_int_parse(node)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        self._check_is_literal(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self._check_risky_deserialization(node)
        self._check_subprocess_shell(node)
        self._check_tls_verification(node)
        self._check_request_without_timeout(node)
        self._check_weak_hash(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self._record_acquired_resource(node.value, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self._record_acquired_resource(node.value, [node.target])
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        self._record_released_resource(node.items)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self._record_released_resource(node.items)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in RESOURCE_RELEASE_CALLS and isinstance(node.value, ast.Name):
            self._released.add(node.value.id)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        # 把资源交还给调用方即视为所有权转移，不再报告泄漏。
        if isinstance(node.value, ast.Name):
            self._released.add(node.value.id)
        self.generic_visit(node)

    # ---- 规则实现 -------------------------------------------------

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.lineno not in self._changed_lines:
            return

        arguments = node.args
        mutable_by_line: dict[int, list[str]] = {}

        positional = [*arguments.posonlyargs, *arguments.args]
        offset = len(positional) - len(arguments.defaults)
        for index, positional_default in enumerate(arguments.defaults):
            if not self._is_mutable_default(positional_default):
                continue
            argument = positional[offset + index]
            mutable_by_line.setdefault(argument.lineno, []).append(argument.arg)

        for keyword_argument, keyword_default in zip(
            [*arguments.kwonlyargs], arguments.kw_defaults, strict=False
        ):
            if keyword_default is None or not self._is_mutable_default(keyword_default):
                continue
            mutable_by_line.setdefault(keyword_argument.lineno, []).append(keyword_argument.arg)

        for line, names in mutable_by_line.items():
            listed = ", ".join(f"`{name}`" for name in names)
            self._add(
                line=line,
                title="Mutable default argument",
                problem=(
                    f"Parameter {listed} uses a mutable default value created once at "
                    "function definition time, so mutations persist across calls."
                ),
                suggestion=(
                    "Use `None` as the default and build the container inside the function "
                    "body, for example `if value is None: value = []`."
                ),
                category="correctness",
                severity="medium",
                confidence=0.9,
                rule="mutable_default_argument",
            )

    def _is_mutable_default(self, node: ast.expr) -> bool:
        if isinstance(node, _MUTABLE_DEFAULT_TYPES):
            return True
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _MUTABLE_DEFAULT_CALLS:
                return True
            if name in _MUTABLE_DEFAULT_ATTRS:
                return True
        return False

    def _check_bare_except(self, node: ast.Try) -> None:
        for handler in node.handlers:
            if handler.type is not None:
                continue
            if handler.lineno not in self._changed_lines:
                continue
            self._add(
                line=handler.lineno,
                title="Bare except swallows every exception",
                problem=(
                    "A bare `except:` also catches `KeyboardInterrupt`, `SystemExit` and "
                    "genuine programming errors, which hides failures and can leave state "
                    "inconsistent."
                ),
                suggestion=(
                    "Catch the specific exception types you can handle, or re-raise after "
                    "logging (`except Exception: ... raise`)."
                ),
                category="error_handling",
                severity="medium",
                confidence=0.92,
                rule="bare_except",
            )

    def _check_lost_traceback(self, node: ast.ExceptHandler) -> None:
        """`raise X` 会丢失原始 traceback，`raise X from e` 则保留。"""
        if node.lineno not in self._changed_lines:
            return
        for child in ast.walk(node):
            if not isinstance(child, ast.Raise) or child.cause is not None:
                continue
            if child.lineno not in self._changed_lines:
                continue
            self._add(
                line=child.lineno,
                title="Exception re-raised without original traceback",
                problem=(
                    "Raising a new exception inside an `except` block without `from` "
                    "discards the original cause, making the real failure hard to diagnose."
                ),
                suggestion=(
                    "Chain the exceptions explicitly, for example `raise ConfigError(...) "
                    "from exc`."
                ),
                category="error_handling",
                severity="medium",
                confidence=0.75,
                rule="raise_without_from",
            )
            return

    def _check_unsafe_int_parse(self, node: ast.Raise) -> None:
        """`raise ValueError(...)` 常出现在输入转换失败处，提示统一处理。"""
        if node.lineno not in self._changed_lines:
            return
        self._add(
            line=node.lineno,
            title="Input conversion failure raised without context",
            problem=(
                "A raw `ValueError` is raised for a conversion failure, so callers cannot "
                "tell which input was invalid."
            ),
            suggestion=(
                "Raise a domain-specific error that includes the offending value and the "
                "expected format."
            ),
            category="error_handling",
            severity="low",
            confidence=0.5,
            rule="uncontextualised_value_error",
        )

    def _check_weak_hash(self, node: ast.Call) -> None:
        if node.lineno not in self._changed_lines:
            return
        name = _call_name(node)
        weak = {"md5", "sha1"}
        if name.split(".")[-1] not in weak:
            return
        self._add(
            line=node.lineno,
            title=f"Weak hash algorithm ({name.split('.')[-1]})",
            problem=(
                f"`{name}` is cryptographically broken and unsuitable for password "
                "hashing or integrity checks against attackers."
            ),
            suggestion=(
                "Use `hashlib.sha256` for integrity, or a dedicated password hash such as "
                "`bcrypt`, `scrypt` or `argon2`."
            ),
            category="security",
            severity="medium",
            confidence=0.85,
            rule="weak_hash_algorithm",
        )

    def _check_is_literal(self, node: ast.Compare) -> None:
        if node.lineno not in self._changed_lines:
            return
        operands = [node.left, *node.comparators]
        for index, operator in enumerate(node.ops):
            if not isinstance(operator, (ast.Is, ast.IsNot)):
                continue
            neighbour = operands[index + 1]
            if not isinstance(neighbour, ast.Constant):
                continue
            if isinstance(neighbour.value, (str, bytes)) and not neighbour.value:
                continue
            if neighbour.value is None:
                continue
            self._add(
                line=node.lineno,
                title="Identity comparison against a literal",
                problem=(
                    "`is` compares object identity, not value. Comparing against a literal "
                    "relies on interpreter interning and can silently change behaviour."
                ),
                suggestion="Use `==`/`!=` for value comparison; keep `is` for `None`.",
                category="correctness",
                severity="medium",
                confidence=0.9,
                rule="is_literal_comparison",
            )
            return

    def _check_risky_deserialization(self, node: ast.Call) -> None:
        if node.lineno not in self._changed_lines:
            return
        owner = _attribute_owner(node)
        if owner is None:
            return
        module, attribute = owner
        library = RISKY_DESERIALIZERS.get((module, attribute))
        if library is None:
            return
        self._add(
            line=node.lineno,
            title=f"Unsafe deserialization via {library}",
            problem=(
                f"`{module}.{attribute}` reconstructs arbitrary objects from untrusted "
                "bytes and can lead to remote code execution."
            ),
            suggestion=(
                "Use a data-only format such as JSON, or restrict loading to trusted, "
                "integrity-checked payloads."
            ),
            category="security",
            severity="critical",
            confidence=0.9,
            rule="unsafe_deserialization",
        )

    def _check_subprocess_shell(self, node: ast.Call) -> None:
        if node.lineno not in self._changed_lines:
            return
        name = _call_name(node).split(".")[-1]
        if name not in {"run", "call", "check_call", "check_output", "Popen"}:
            return
        if not any(
            keyword.arg == "shell" and _is_truthy_constant(keyword.value)
            for keyword in node.keywords
        ):
            return
        self._add(
            line=node.lineno,
            title="Subprocess executed with shell=True",
            problem=(
                "`shell=True` passes the command through the system shell, so interpolated "
                "input becomes a command-injection vector."
            ),
            suggestion=(
                "Pass an argument list without `shell=True`, or use `shlex.quote` on every "
                "untrusted fragment."
            ),
            category="security",
            severity="high",
            confidence=0.85,
            rule="subprocess_shell_true",
        )

    def _check_tls_verification(self, node: ast.Call) -> None:
        if node.lineno not in self._changed_lines:
            return
        if not any(
            keyword.arg == "verify" and _is_falsey_constant(keyword.value)
            for keyword in node.keywords
        ):
            return
        self._add(
            line=node.lineno,
            title="TLS certificate verification disabled",
            problem=(
                "Disabling certificate verification makes the request vulnerable to "
                "man-in-the-middle interception."
            ),
            suggestion="Remove `verify=False` and trust a proper CA bundle instead.",
            category="security",
            severity="high",
            confidence=0.9,
            rule="tls_verification_disabled",
        )

    def _check_request_without_timeout(self, node: ast.Call) -> None:
        if node.lineno not in self._changed_lines:
            return
        name = _call_name(node)
        if name.split(".")[-1] not in {"get", "post", "put", "patch", "delete", "request", "head"}:
            return
        if not any(part in name for part in ("requests", "httpx", "session", "client")):
            return
        if any(keyword.arg == "timeout" for keyword in node.keywords):
            return
        self._add(
            line=node.lineno,
            title="HTTP request without timeout",
            problem=(
                "A request without an explicit timeout can block the worker indefinitely "
                "when the peer stalls."
            ),
            suggestion="Pass an explicit `timeout=` value so the call fails fast.",
            category="resource",
            severity="medium",
            confidence=0.7,
            rule="http_request_without_timeout",
        )

    def _record_acquired_resource(self, value: ast.expr | None, targets: list[ast.expr]) -> None:
        if not isinstance(value, ast.Call):
            return
        name = _call_name(value).split(".")[-1]
        if name not in RESOURCE_ACQUIRING_CALLS:
            return
        if value.lineno not in self._changed_lines:
            return
        for target in targets:
            if isinstance(target, ast.Name):
                self._acquired[target.id] = value

    def _record_released_resource(self, items: list[ast.withitem]) -> None:
        for item in items:
            if isinstance(item.optional_vars, ast.Name):
                self._released.add(item.optional_vars.id)

    def report_unclosed_resources(self) -> None:
        """在所有节点访问结束后报告未释放的资源。"""
        for name, call in self._acquired.items():
            if name in self._released:
                continue
            self._add(
                line=call.lineno,
                title="Resource opened without guaranteed cleanup",
                problem=(
                    f"`{name}` is assigned from a resource-acquiring call but the code path "
                    "never closes it, so the handle leaks on exceptions and early returns."
                ),
                suggestion=(
                    "Open the resource in a `with` block so it is released on every exit " "path."
                ),
                category="resource",
                severity="medium",
                confidence=0.75,
                rule="unclosed_resource",
            )

    # ---- 输出 -----------------------------------------------------

    def _add(
        self,
        *,
        line: int,
        title: str,
        problem: str,
        suggestion: str,
        category: str,
        severity: str,
        confidence: float,
        rule: str,
    ) -> None:
        snippet = self._line_text(line)
        raw_id = f"{self._filename}:{line}:{rule}"
        self.findings.append(
            Finding(
                finding_id=hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12],
                severity=severity,
                category=category,
                file=self._filename,
                line_start=line,
                line_end=line,
                title=title,
                problem=problem,
                suggestion=suggestion,
                confidence=confidence,
                code_snippet=snippet,
                sources=["static_rule"],
            )
        )

    def _line_text(self, line: int) -> str:
        lines = self._source.splitlines()
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()
        return ""


def _call_name(node: ast.Call) -> str:
    """还原调用表达式的点分名称，例如 `requests.get`。"""
    parts: list[str] = []
    current: Any = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _attribute_owner(node: ast.Call) -> tuple[str, str] | None:
    """返回 `(模块名, 方法名)`，仅当调用形如 `module.method(...)`。"""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    return None


def _is_truthy_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _is_falsey_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not bool(node.value)


def analyze_python_ast(file_diff: FileDiff, context: FileContext) -> list[Finding]:
    """便捷入口：分析单个文件并返回全部 AST 规则命中。"""
    analyzer = PythonAstAnalyzer()
    findings = analyzer.analyze(file_diff, context)
    return findings


__all__ = ["PythonAstAnalyzer", "analyze_python_ast"]
