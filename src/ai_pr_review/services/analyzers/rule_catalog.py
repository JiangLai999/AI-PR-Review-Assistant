"""确定性规则目录：规则文案（英文 / 中文）的唯一真源。

改造前每条规则的标题、问题、建议都内联在 `StaticAnalyzer`（逐行正则）与
`PythonAstAnalyzer`（AST）里，中文只在 `finding_localizer._RULE_ZH` 里覆盖了
11 条、且按英文标题匹配，新增规则时没有任何机制提醒补中文（P6 计划 §0 项目④）。

现在两个分析器都改为按规则键从本目录取文案构造 Finding，`finding_localizer`
也按 `rule_id` 从这里取中文，因此：

1. 英文文案与改造前逐字一致（P6 计划 §3.2，既有规则测试与 benchmark 不受影响）；
2. 中文文案必须全量补齐，缺任何一段都会被 `tests/test_rule_catalog.py` 拦下；
3. `_finding(...)` 里出现的规则键必须在本目录中登记，反向覆盖测试会扫描两个
   分析器的源码做断言，新增规则不补目录即测试失败。

动态文案用 `{name}` 形式的占位符表示，由分析器在构造 Finding 时渲染英文，
本地化时再从英文标题反解出占位符值渲染中文（见 `RuleDefinition.localize`）。

目录键通常等于 `rule_id`。唯一的例外是 TLS 证书校验关闭：逐行规则与 AST 规则
各自实现，规则身份/标题/严重级别/置信度相同，但英文问题描述不同；为了逐字保留
两处现状文案，目录用两个键（`tls_verification_disabled` / `tls_verification_disabled.ast`）
共享同一个 `rule_id` 与同一份中文文案。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# 英文标题模板中的 `{name}` 占位符。
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class RuleDefinition:
    """一条确定性规则的完整文案与元数据。"""

    rule_id: str
    title: str
    problem: str
    suggestion: str
    category: str
    severity: str
    confidence: float
    title_zh: str
    problem_zh: str
    suggestion_zh: str

    def build_fields(self, **params: str) -> dict[str, object]:
        """渲染英文文案，供分析器直接构造 `Finding`。"""
        return {
            "rule_id": self.rule_id,
            "title": self.title.format(**params),
            "problem": self.problem.format(**params),
            "suggestion": self.suggestion.format(**params),
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
        }

    def localize(self, english_title: str) -> tuple[str, str, str] | None:
        """按英文标题反解占位符，返回中文 (标题, 问题, 建议)。

        标题与目录模板不一致（例如历史库里的人工改写）时返回 None，
        由调用方回退到旧的按标题匹配表。
        """
        params = _extract_params(self.title, english_title)
        if params is None:
            return None
        return (
            self.title_zh.format(**params),
            self.problem_zh.format(**params),
            self.suggestion_zh.format(**params),
        )


def _extract_params(template: str, rendered: str) -> dict[str, str] | None:
    """从渲染后的英文标题反解模板占位符的值。

    模板没有占位符时，只有与渲染结果完全一致才算匹配（否则说明这条
    finding 不是该规则产出的）。
    """
    matches = list(_PLACEHOLDER.finditer(template))
    if not matches:
        return {} if template == rendered else None

    pattern_parts: list[str] = []
    cursor = 0
    for match in matches:
        pattern_parts.append(re.escape(template[cursor : match.start()]))
        pattern_parts.append(f"(?P<{match.group(1)}>.+?)")
        cursor = match.end()
    pattern_parts.append(re.escape(template[cursor:]))

    matched = re.fullmatch("".join(pattern_parts), rendered)
    if matched is None:
        return None
    return dict(matched.groupdict())


_TLS_LINE_RULE = RuleDefinition(
    rule_id="tls_verification_disabled",
    title="TLS certificate verification disabled",
    problem=(
        "Certificate verification is turned off, so the connection is open to "
        "man-in-the-middle interception."
    ),
    suggestion="Remove `verify=False` and trust a proper CA bundle instead.",
    category="security",
    severity="high",
    confidence=0.9,
    title_zh="TLS 证书校验已关闭",
    problem_zh="关闭证书校验会使请求容易遭受中间人拦截。",
    suggestion_zh="移除 verify=False，并使用正确的 CA 证书包。",
)

_RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        rule_id="dynamic_execution",
        title="Dynamic code execution",
        problem=(
            "The changed line executes dynamically constructed code, which can become "
            "arbitrary code execution when input is influenced by users."
        ),
        suggestion=(
            "Remove dynamic execution or strictly constrain and validate the input before "
            "using a safe alternative."
        ),
        category="security",
        severity="high",
        confidence=0.98,
        title_zh="动态代码执行",
        problem_zh="该变更行执行了动态构造的代码，若输入受用户影响，可能导致任意代码执行。",
        suggestion_zh="移除动态执行，或严格约束并校验输入后使用安全替代方案。",
    ),
    RuleDefinition(
        rule_id="html_injection",
        title="Potential HTML injection",
        problem=(
            "The changed line writes HTML directly and may allow untrusted content to "
            "become executable markup."
        ),
        suggestion=(
            "Prefer escaped text rendering or sanitize untrusted HTML with a "
            "well-maintained allowlist."
        ),
        category="security",
        severity="high",
        confidence=0.94,
        title_zh="潜在 HTML 注入",
        problem_zh="该变更行直接写入 HTML，可能使不受信任的内容变成可执行标记。",
        suggestion_zh="优先使用转义文本，或使用可靠的白名单清理 HTML。",
    ),
    RuleDefinition(
        rule_id="hardcoded_secret",
        title="Possible hard-coded secret",
        problem="A credential-like value appears to be assigned directly in source code.",
        suggestion=(
            "Move the value to a secret manager or environment variable and rotate it if "
            "it was real."
        ),
        category="security",
        severity="critical",
        confidence=0.91,
        title_zh="可能的硬编码凭据",
        problem_zh="代码中疑似直接赋值了凭据类内容。",
        suggestion_zh="将敏感值移至密钥管理器或环境变量；如果是真实密钥，请立即轮换。",
    ),
    RuleDefinition(
        rule_id="sql_interpolation",
        title="Possible SQL injection",
        problem="SQL text appears to be assembled with string interpolation or concatenation.",
        suggestion="Use parameterized queries or the database library's bound-parameter API.",
        category="security",
        severity="high",
        confidence=0.88,
        title_zh="可能的 SQL 注入",
        problem_zh="SQL 文本通过字符串插值或拼接构造。",
        suggestion_zh="使用参数化查询或数据库库提供的绑定参数接口。",
    ),
    RuleDefinition(
        rule_id="unsafe_yaml_load",
        title="Unsafe YAML deserialization",
        problem=(
            "`yaml.load` without a safe loader can construct arbitrary Python objects from "
            "untrusted input."
        ),
        suggestion="Use `yaml.safe_load` or pass `Loader=yaml.SafeLoader` explicitly.",
        category="security",
        severity="critical",
        confidence=0.9,
        title_zh="不安全的 YAML 反序列化",
        problem_zh=("未使用安全加载器的 yaml.load 可能从不受信任输入构造任意 Python 对象。"),
        suggestion_zh="使用 yaml.safe_load，或显式传入 yaml.SafeLoader。",
    ),
    _TLS_LINE_RULE,
    RuleDefinition(
        rule_id="hardcoded_credential_constant",
        title="Possible hard-coded credential constant",
        problem=(
            "A credential-looking constant is assigned a literal secret value in source code."
        ),
        suggestion=(
            "Load the secret from the environment or a secret manager, and rotate it if it "
            "was real."
        ),
        category="security",
        severity="critical",
        confidence=0.85,
        title_zh="可能的硬编码凭据常量",
        problem_zh="源码中为凭据类常量直接赋值了字面量密钥。",
        suggestion_zh="从环境变量或密钥管理器读取该值；如果是真实密钥，请立即轮换。",
    ),
    RuleDefinition(
        rule_id="debug_mode_enabled",
        title="Debug mode may be enabled in production",
        problem=(
            "A debug flag is hard-coded to True, which can expose stack traces and an "
            "interactive debugger."
        ),
        suggestion="Drive the flag from configuration or the environment instead of source.",
        category="security",
        severity="medium",
        confidence=0.7,
        title_zh="生产环境可能启用了调试模式",
        problem_zh="调试开关被硬编码为 True，可能暴露堆栈信息与交互式调试器。",
        suggestion_zh="改为从配置或环境变量读取该开关，而不是写在源码中。",
    ),
    RuleDefinition(
        rule_id="mutable_default_argument",
        title="Mutable default argument",
        problem=(
            "Parameter {listed} uses a mutable default value created once at function "
            "definition time, so mutations persist across calls."
        ),
        suggestion=(
            "Use `None` as the default and build the container inside the function body, "
            "for example `if value is None: value = []`."
        ),
        category="correctness",
        severity="medium",
        confidence=0.9,
        title_zh="可变默认参数",
        # 沿用 finding_localizer 旧表的中文文案：旧表覆盖的规则渲染结果保持不变。
        problem_zh="函数使用了可变对象作为默认参数，可能在多次调用之间共享状态。",
        suggestion_zh="使用 None 作为默认值，并在函数体内创建新对象。",
    ),
    RuleDefinition(
        rule_id="bare_except",
        title="Bare except swallows every exception",
        problem=(
            "A bare `except:` also catches `KeyboardInterrupt`, `SystemExit` and genuine "
            "programming errors, which hides failures and can leave state inconsistent."
        ),
        suggestion=(
            "Catch the specific exception types you can handle, or re-raise after logging "
            "(`except Exception: ... raise`)."
        ),
        category="error_handling",
        severity="medium",
        confidence=0.92,
        title_zh="裸 except 捕获所有异常",
        problem_zh="裸 except 会吞掉所有异常，包括系统级异常，降低故障可见性。",
        suggestion_zh="捕获具体异常类型，并保留必要的异常链。",
    ),
    RuleDefinition(
        rule_id="raise_without_from",
        title="Exception re-raised without original traceback",
        problem=(
            "Raising a new exception inside an `except` block without `from` discards the "
            "original cause, making the real failure hard to diagnose."
        ),
        suggestion=(
            "Chain the exceptions explicitly, for example `raise ConfigError(...) from exc`."
        ),
        category="error_handling",
        severity="medium",
        confidence=0.75,
        title_zh="异常重新抛出时丢失原始回溯",
        problem_zh="在 except 块中抛出新的异常但没有使用 from，原始成因被丢弃，真实故障难以定位。",
        suggestion_zh="显式串联异常，例如 raise ConfigError(...) from exc。",
    ),
    RuleDefinition(
        rule_id="uncontextualised_value_error",
        title="Input conversion failure raised without context",
        problem=(
            "A raw `ValueError` is raised for a conversion failure, so callers cannot tell "
            "which input was invalid."
        ),
        suggestion=(
            "Raise a domain-specific error that includes the offending value and the "
            "expected format."
        ),
        category="error_handling",
        severity="low",
        confidence=0.5,
        title_zh="输入转换失败时缺少上下文",
        problem_zh="转换失败时直接抛出原始 ValueError，调用方无法判断是哪个输入不合法。",
        suggestion_zh="抛出包含问题取值与期望格式的领域专用异常。",
    ),
    RuleDefinition(
        rule_id="weak_hash_algorithm",
        title="Weak hash algorithm ({algorithm})",
        problem=(
            "`{name}` is cryptographically broken and unsuitable for password hashing or "
            "integrity checks against attackers."
        ),
        suggestion=(
            "Use `hashlib.sha256` for integrity, or a dedicated password hash such as "
            "`bcrypt`, `scrypt` or `argon2`."
        ),
        category="security",
        severity="medium",
        confidence=0.85,
        title_zh="弱哈希算法（{algorithm}）",
        problem_zh="该哈希算法在密码学上已被攻破，不适合用于口令哈希或对抗攻击者的完整性校验。",
        suggestion_zh=(
            "完整性校验请使用 hashlib.sha256；口令请使用 bcrypt、scrypt 或 argon2 等专用算法。"
        ),
    ),
    RuleDefinition(
        rule_id="is_literal_comparison",
        title="Identity comparison against a literal",
        problem=(
            "`is` compares object identity, not value. Comparing against a literal relies "
            "on interpreter interning and can silently change behaviour."
        ),
        suggestion="Use `==`/`!=` for value comparison; keep `is` for `None`.",
        category="correctness",
        severity="medium",
        confidence=0.9,
        title_zh="使用 is 与字面量比较",
        problem_zh="is 比较的是对象标识而非值；与字面量比较依赖解释器驻留机制，行为可能悄然改变。",
        suggestion_zh="值比较请使用 ==/!=，is 仅用于 None。",
    ),
    RuleDefinition(
        rule_id="unsafe_deserialization",
        title="Unsafe deserialization via {library}",
        problem=(
            "`{module}.{attribute}` reconstructs arbitrary objects from untrusted bytes and "
            "can lead to remote code execution."
        ),
        suggestion=(
            "Use a data-only format such as JSON, or restrict loading to trusted, "
            "integrity-checked payloads."
        ),
        category="security",
        severity="critical",
        confidence=0.9,
        title_zh="不安全的反序列化（{library}）",
        problem_zh="该反序列化接口会从不受信任的字节流重建任意对象，可能导致远程代码执行。",
        suggestion_zh="改用 JSON 等纯数据格式，或只加载可信且经过完整性校验的载荷。",
    ),
    RuleDefinition(
        rule_id="subprocess_shell_true",
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
        title_zh="子进程启用了 shell=True",
        problem_zh="使用 shell=True 处理不受信任输入可能导致命令注入。",
        suggestion_zh="使用参数数组调用子进程，并避免不必要的 shell。",
    ),
    RuleDefinition(
        rule_id="http_request_without_timeout",
        title="HTTP request without timeout",
        problem=(
            "A request without an explicit timeout can block the worker indefinitely when "
            "the peer stalls."
        ),
        suggestion="Pass an explicit `timeout=` value so the call fails fast.",
        category="resource",
        severity="medium",
        confidence=0.7,
        title_zh="HTTP 请求未设置超时",
        problem_zh="未设置明确超时的请求可能在对端卡住时无限阻塞工作线程。",
        suggestion_zh="传入明确的 timeout 参数，使请求能够快速失败。",
    ),
    RuleDefinition(
        rule_id="unclosed_resource",
        title="Resource opened without guaranteed cleanup",
        problem=(
            "`{name}` is assigned from a resource-acquiring call but the code path never "
            "closes it, so the handle leaks on exceptions and early returns."
        ),
        suggestion="Open the resource in a `with` block so it is released on every exit path.",
        category="resource",
        severity="medium",
        confidence=0.75,
        title_zh="资源打开后未保证释放",
        problem_zh="资源获取后没有确保在异常和提前返回路径中关闭，可能造成句柄泄漏。",
        suggestion_zh="使用 with 代码块打开资源，确保所有退出路径都能释放。",
    ),
)

# AST 分析器对 TLS 这条规则使用了不同的英文问题描述。P6 要求英文输出与现状
# 逐字一致，因此为它单独保留一条记录：rule_id、标题、严重级别、置信度与中文
# 文案都和逐行规则那条共享（用 dataclasses.replace 派生，杜绝中文文案漂移）。
TLS_AST_RULE_KEY = "tls_verification_disabled.ast"

_TLS_AST_RULE = replace(
    _TLS_LINE_RULE,
    problem=(
        "Disabling certificate verification makes the request vulnerable to "
        "man-in-the-middle interception."
    ),
)

# 目录键 -> 规则定义。键通常等于 rule_id，例外见模块文档。
RULE_CATALOG: dict[str, RuleDefinition] = {definition.rule_id: definition for definition in _RULES}
RULE_CATALOG[TLS_AST_RULE_KEY] = _TLS_AST_RULE


def get_rule(key: str) -> RuleDefinition:
    """按目录键取规则定义，键不存在时抛 KeyError。"""
    return RULE_CATALOG[key]


def rule_for_id(rule_id: str) -> RuleDefinition | None:
    """按规则身份取定义（同一 rule_id 的多条记录返回第一条，中文一致）。"""
    if not rule_id:
        return None
    for definition in RULE_CATALOG.values():
        if definition.rule_id == rule_id:
            return definition
    return None


def all_rule_ids() -> set[str]:
    """目录中出现的全部规则身份。"""
    return {definition.rule_id for definition in RULE_CATALOG.values()}


__all__ = [
    "RULE_CATALOG",
    "TLS_AST_RULE_KEY",
    "RuleDefinition",
    "all_rule_ids",
    "get_rule",
    "rule_for_id",
]
