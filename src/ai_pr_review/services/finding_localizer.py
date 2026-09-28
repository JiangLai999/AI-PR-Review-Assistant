"""Localize deterministic Finding messages without touching code identifiers.

中文文案的唯一真源是 `rule_catalog`：这里只负责按 `rule_id` 取用与回退，
不再维护自己的规则表（`_RULE_ZH` 仅作为历史数据的兼容回退保留）。
"""

from __future__ import annotations

from ai_pr_review.services.analyzers.rule_catalog import rule_for_id
from ai_pr_review.services.prompt_assembler import Finding, finding_has_source

_CATEGORY_ZH = {
    "correctness": "正确性",
    "security": "安全性",
    "resource": "资源管理",
    "error_handling": "错误处理",
    "performance": "性能",
    "concurrency": "并发",
    "architecture": "架构",
}

_RULE_ZH = {
    "Dynamic code execution": (
        "动态代码执行",
        "该变更行执行了动态构造的代码，若输入受用户影响，可能导致任意代码执行。",
        "移除动态执行，或严格约束并校验输入后使用安全替代方案。",
    ),
    "Potential HTML injection": (
        "潜在 HTML 注入",
        "该变更行直接写入 HTML，可能使不受信任的内容变成可执行标记。",
        "优先使用转义文本，或使用可靠的白名单清理 HTML。",
    ),
    "Possible hard-coded secret": (
        "可能的硬编码凭据",
        "代码中疑似直接赋值了凭据类内容。",
        "将敏感值移至密钥管理器或环境变量；如果是真实密钥，请立即轮换。",
    ),
    "Possible SQL injection": (
        "可能的 SQL 注入",
        "SQL 文本通过字符串插值或拼接构造。",
        "使用参数化查询或数据库库提供的绑定参数接口。",
    ),
    "Unsafe YAML deserialization": (
        "不安全的 YAML 反序列化",
        "未使用安全加载器的 yaml.load 可能从不受信任输入构造任意 Python 对象。",
        "使用 yaml.safe_load，或显式传入 yaml.SafeLoader。",
    ),
    "TLS certificate verification disabled": (
        "TLS 证书校验已关闭",
        "关闭证书校验会使请求容易遭受中间人拦截。",
        "移除 verify=False，并使用正确的 CA 证书包。",
    ),
    "HTTP request without timeout": (
        "HTTP 请求未设置超时",
        "未设置明确超时的请求可能在对端卡住时无限阻塞工作线程。",
        "传入明确的 timeout 参数，使请求能够快速失败。",
    ),
    "Mutable default argument": (
        "可变默认参数",
        "函数使用了可变对象作为默认参数，可能在多次调用之间共享状态。",
        "使用 None 作为默认值，并在函数体内创建新对象。",
    ),
    "Bare except swallows every exception": (
        "裸 except 捕获所有异常",
        "裸 except 会吞掉所有异常，包括系统级异常，降低故障可见性。",
        "捕获具体异常类型，并保留必要的异常链。",
    ),
    "Subprocess executed with shell=True": (
        "子进程启用了 shell=True",
        "使用 shell=True 处理不受信任输入可能导致命令注入。",
        "使用参数数组调用子进程，并避免不必要的 shell。",
    ),
    "Resource opened without guaranteed cleanup": (
        "资源打开后未保证释放",
        "资源获取后没有确保在异常和提前返回路径中关闭，可能造成句柄泄漏。",
        "使用 with 代码块打开资源，确保所有退出路径都能释放。",
    ),
}


def localize_deterministic_finding(finding: Finding, language: str) -> Finding:
    """把确定性规则的英文文案换成中文。

    主路径按 `rule_id` 从 `rule_catalog` 取中文（目录覆盖全部规则，含规则自带的
    动态片段）；`rule_id` 为空或目录未登记时回退到旧的按英文标题匹配表。
    模型产出的 finding 不带 `static_rule` 来源，因此不会被本地化。
    """
    if not language.lower().startswith("zh") or not finding_has_source(finding, "static_rule"):
        return finding
    mapped = _localize_by_rule_id(finding) or _localize_by_title(finding.title)
    if mapped is None:
        return finding
    return finding.model_copy(
        update={
            "title": mapped[0],
            "problem": mapped[1],
            "suggestion": mapped[2],
            "category": _CATEGORY_ZH.get(finding.category, finding.category),
        }
    )


def _localize_by_rule_id(finding: Finding) -> tuple[str, str, str] | None:
    definition = rule_for_id(finding.rule_id)
    if definition is None:
        return None
    return definition.localize(finding.title)


def _localize_by_title(title: str) -> tuple[str, str, str] | None:
    """兼容回退：按英文标题查旧表（含 "标题变体（后缀）" 的拼接）。"""
    mapped = _RULE_ZH.get(title)
    if mapped is not None:
        return mapped
    for english, value in _RULE_ZH.items():
        if title.startswith(english):
            suffix = title[len(english) :].strip(" ()")
            return (f"{value[0]}（{suffix}）", value[1], value[2])
    return None
