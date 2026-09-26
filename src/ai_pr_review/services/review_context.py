"""审查上下文构建器（docs/dual-model-roles-plan.md §9 · Review-Aware Chat）。

把一次**已落库**的审查渲染成分层纯文本，供 `_chat` 注入 system prompt：

| 层 | 内容 | 预算裁剪顺序 |
|---|---|---|
| L1 | 运行摘要：PR/作者/summary/统计/模型/成本/证据校验计数 | 永不裁剪 |
| L2 | findings 清单：severity / 文件:行 / 置信度 / 证据状态 / 标题 | 最后（只留 critical/high）|
| L3 | 重点 finding 全文：problem / suggestion / 代码片段 / 证据疑点 | 中间（逐个减条目）|
| L4 | 被过滤 finding 的门槛与计数（`filtered_findings`）| 最先丢弃 |

设计约束：

- **确定性**：只读 `ResultStore`，不调模型、不联网。同一个 run 渲染出的文本逐字一致，
  所以格式可以冻结在测试里；`/explain` 的确定性、零成本属性在这里同样成立。
- **诚实**：缺失的信息整行省略，绝不补 0（没有 `filtered_findings` 就没有 L4 段）。
- **不抛异常**：run 不存在、store 读失败一律返回 `None`，由调用方降级为普通聊天
  （§9.2 C：构建失败不得中断对话）。
- **L1 永不裁剪**：否则模型会失去"在说哪一次审查"（§9.D）。
- **预算只衡量分层内容**：发生裁剪时会在末尾附一行裁剪提示（元信息），因此最终文本
  可能比预算多出这一行的长度；`ReviewContext.tokens` 是含提示的实测估算。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from ai_pr_review.services.post_processor import SEVERITY_ORDER

# 4 字符 ≈ 1 token（§9.D 的预算口径）。
CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 8000
# L3（逐条全文：problem / suggestion / 代码片段）覆盖几条 finding。
#
# 2026-09-26 从 3 提到 20：实测用户问「看看 pr31」时，12 条 finding 里只有前 3 条
# 有全文，模型对第 4-12 条只能说"只有标题级信息，需查看源码"——用户追问任意一条
# （如"第 6 条为什么判 medium"）都无法回答。上下文预算早已动态化（chat_context_budget
# 可配），且 `_budget_plans` 本就支持「按预算逐条增减 L3」，这个硬上限是过度保守。
# 保留 20 作为**性能兜底**（findings 极端多时不渲染上百个块），常规审查（≤20 条）
# 全部可得全文；预算不足时仍按原有链条逐条降级。
L3_MAX_FINDINGS = 20
# L3 的裁剪以「条」为单位，但单条自身过长同样会吃光预算，所以段落本身也要有界。
L1_SUMMARY_LIMIT = 2000
L3_PARAGRAPH_LIMIT = 1000
L3_SNIPPET_LIMIT = 1200
L3_TITLE_LIMIT = 200
TRUNCATION_MARK = "…［已截断］"

# 注入 system prompt 的诚实约束（§9.2 C）：上下文之外的问题必须承认"需要查看源码"，
# 不许凭空补全。文案冻结在这里，`_chat` 只负责拼接。
CONTEXT_RULES = (
    "规则：\n"
    "1. 只依据上面的审查上下文回答，不要引入上下文之外的信息；\n"
    "2. 引用 finding 时必须给出「文件:行」与严重度；\n"
    '3. 上下文未包含的内容（例如未展示的完整源码）必须明确说明"需要查看源码"，不得臆测。'
)

# 裁剪提示里给用户指路用的确定性命令（零成本、离线可用的 `/explain`）。
TRIM_HINT_COMMAND = "/explain"


class RunReader(Protocol):
    """`ResultStore` 中构建上下文需要的只读接口（结构化子类型，便于测试替身）。"""

    def get_run_summary(self, run_id: str) -> dict | None: ...

    def get_result(self, run_id: str) -> Any | None: ...

    def get_run_metadata(self, run_id: str) -> dict: ...


@dataclass(frozen=True)
class ReviewContext:
    """一次渲染的结果：注入文本 + token 估算 + 实际发生的裁剪。"""

    text: str
    tokens: int
    budget: int
    trimmed: tuple[str, ...] = ()

    @property
    def was_trimmed(self) -> bool:
        return bool(self.trimmed)


def estimate_tokens(text: str) -> int:
    """4 字符 ≈ 1 token 的粗估（与注入预算同一口径，供 `/context` 展示）。"""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def build_review_context(
    store: RunReader,
    run_id: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> str | None:
    """渲染注入用的审查上下文；run 不存在或读取失败返回 `None`。"""
    context = build_review_context_meta(store, run_id, token_budget=token_budget)
    return None if context is None else context.text


def build_review_context_meta(
    store: RunReader,
    run_id: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> ReviewContext | None:
    """同一次渲染的带元数据版本（`/context` 显示 token 估算与裁剪情况）。"""
    key = _text(run_id)
    if not key:
        return None
    try:
        run = store.get_run_summary(key)
        if not run:
            return None
        result = store.get_result(key)
        metadata = store.get_run_metadata(key)
    except Exception:
        # 读库失败不是聊天的致命错误：调用方据此降级为普通聊天。
        return None
    if result is None:
        return None
    if not isinstance(metadata, dict):
        metadata = {}
    findings = _sorted_findings(_field(result, "findings") or [])
    summary = _text(_field(result, "summary"))

    l1 = _render_l1(key, run, summary, findings, metadata)
    l2_all = _render_l2(findings, critical_high_only=False)
    # 真的一条都没记录时复用 L2 全量文案：这时"没有记录任何 Finding"才是实话，
    # 而"预算受限"会把一次空审查说成一次被裁剪的审查。
    l2_focus = (
        _render_l2(
            [finding for finding in findings if _severity(finding) in {"critical", "high"}],
            critical_high_only=True,
        )
        if findings
        else l2_all
    )
    l3_blocks = [
        _render_l3_block(index, finding)
        for index, finding in enumerate(findings[:L3_MAX_FINDINGS], start=1)
    ]
    l4 = _render_l4(metadata)
    budget = _normalize_budget(token_budget)

    text = ""
    trimmed: tuple[str, ...] = ()
    note = ""
    for sections, dropped in _budget_plans(l1, l2_all, l2_focus, l3_blocks, l4):
        candidate = _compose(sections)
        note = _trim_note(dropped, budget, key) if dropped else ""
        # 从最完整的一档开始，取第一个装得下的；全都装不下时保留最后一档
        # （即 L1 + 仅 critical/high 的 L2）而不是输出空上下文。
        # 预算只衡量分层内容：底部的裁剪提示是元信息（约 30 token），不参与取舍，
        # 否则它会先挤掉 L4 之外的一层，让"L4 先消失"的裁剪顺序失真。
        text, trimmed = candidate, dropped
        if estimate_tokens(candidate) <= budget:
            break
    if note:
        text = f"{text}\n\n{note}"
    return ReviewContext(text=text, tokens=estimate_tokens(text), budget=budget, trimmed=trimmed)


def wrap_review_context(run_id: str, context: str) -> str:
    """把上下文包进注入片段（§9.2 C）：上下文块 + 诚实约束。"""
    return (
        "你正在协助分析一次 PR 审查结果。以下是本次会话绑定的审查上下文：\n"
        f'<review_context run_id="{run_id}">\n{context}\n</review_context>\n'
        f"{CONTEXT_RULES}"
    )


def _budget_plans(
    l1: str,
    l2_all: str,
    l2_focus: str,
    l3_blocks: list[str],
    l4: str,
) -> list[tuple[list[str], tuple[str, ...]]]:
    """按「L4 → L3（减条目）→ L2（只留 high/critical）」生成候选渲染，从完整到最简。

    L1 永不进入候选序列的"被裁剪"一侧：它在每一档里都原样存在。
    """
    plans: list[tuple[list[str], tuple[str, ...]]] = []
    total = len(l3_blocks)
    dropped_prefix: tuple[str, ...] = ()
    if l4:
        # L4 只在最完整的一档出现 —— 预算不够时它是第一个消失的。
        plans.append(([l1, l2_all, _l3_section(l3_blocks), l4], ()))
        dropped_prefix = ("L4",)
    # 第二档起：L4 已丢，L3 从「全留」逐条减到 0，最后才动 L2。
    for count in range(total, -1, -1):
        dropped = dropped_prefix + (("L3",) if count < total else ())
        plans.append(([l1, l2_all, _l3_section(l3_blocks[:count])], dropped))
    plans.append(([l1, l2_focus], dropped_prefix + ("L3", "L2")))
    return plans


def _compose(sections: list[str]) -> str:
    return "\n\n".join(section for section in sections if section)


def _trim_note(trimmed: tuple[str, ...], budget: int, run_id: str) -> str:
    layers = "、".join(trimmed)
    return (
        f"（注：本上下文超出 {budget} token 预算，已按 L4 → L3 → L2 顺序裁剪 {layers}；"
        f"完整内容可用 {TRIM_HINT_COMMAND} {run_id} 查看。）"
    )


def _normalize_budget(token_budget: Any) -> int:
    """非数值预算退回默认值；0/负数按 1 处理（越小越省，保留 L1 的语义不变）。"""
    try:
        value = int(token_budget)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_BUDGET
    return max(1, value)


# ---------------------------------------------------------------------------
# 分层渲染
# ---------------------------------------------------------------------------


def _render_l1(
    run_id: str,
    run: dict[str, Any],
    summary: str,
    findings: list[Any],
    metadata: dict[str, Any],
) -> str:
    """L1 运行摘要：永不裁剪，且缺什么就少哪一行。"""
    lines = ["[L1 运行摘要]", f"Run: {run_id}"]
    pr_label = describe_run(run, metadata)
    if pr_label:
        lines.append(f"PR: {pr_label}")
    author = _text(metadata.get("pr_author"))
    if author:
        lines.append(f"作者: {author}")
    url = _text(run.get("pr_url"))
    if url:
        lines.append(f"URL: {url}")
    created = _text(run.get("created_at"))
    if created:
        lines.append(f"时间: {created}")
    model = _text(run.get("model"))
    if model:
        lines.append(f"模型: {model}")
    measured: list[str] = []
    duration = _as_float(run.get("duration_seconds"))
    if duration is not None:
        measured.append(f"耗时 {duration:.1f}s")
    cost = _as_float(run.get("total_cost"))
    if cost is not None:
        measured.append(f"成本 ${cost:.4f}")
    if measured:
        lines.append(" · ".join(measured))
    counts = _severity_counts(findings)
    counts_line = f"统计: 共 {len(findings)} 条 · " + " · ".join(
        f"{severity} {counts[severity]}" for severity in SEVERITY_ORDER
    )
    files = _files_line(run)
    if files:
        counts_line += f" · {files}"
    lines.append(counts_line)
    validation = _validation_line(metadata)
    if validation:
        lines.append(validation)
    if summary:
        lines.append(f"摘要: {_clip(summary, L1_SUMMARY_LIMIT)}")
    return "\n".join(lines)


def _render_l2(findings: list[Any], *, critical_high_only: bool) -> str:
    """L2 findings 清单：编号与 L3 的 `#N` 对齐，「第 N 条」在两处指向同一条。"""
    header = "[L2 FINDINGS 清单]"
    if not findings:
        if critical_high_only:
            # 不能写成"该 Run 没有记录任何 Finding"：预算裁剪掉的条数是真实存在的，
            # 那句会让模型以为这次审查什么都没发现。
            return (
                f"{header}\n（预算受限：该 Run 没有 critical/high 的 Finding；"
                f"完整清单可用 {TRIM_HINT_COMMAND} 查看）"
            )
        return f"{header}\n（该 Run 没有记录任何 Finding）"
    qualifier = "（预算受限，仅保留 critical/high）" if critical_high_only else "（按严重度排序）"
    lines = [f"{header} 共 {len(findings)} 条{qualifier}"]
    for index, finding in enumerate(findings, start=1):
        lines.append(f"{index}. {_finding_line(finding)}")
    return "\n".join(lines)


def _render_l3_block(index: int, finding: Any) -> str:
    lines = [
        f"#{index} [{_severity(finding)}] {_clip(_text(_field(finding, 'title')), L3_TITLE_LIMIT)}",
        f"   位置: {_location(finding)}",
    ]
    meta: list[str] = []
    confidence = _confidence_text(finding)
    if confidence:
        meta.append(f"置信度 {confidence}")
    meta.append(f"证据: {_evidence_status(finding)}")
    lines.append("   " + " · ".join(meta))
    problem = _clip(_text(_field(finding, "problem")), L3_PARAGRAPH_LIMIT)
    if problem:
        lines.append(f"   原因: {problem}")
    suggestion = _clip(_text(_field(finding, "suggestion")), L3_PARAGRAPH_LIMIT)
    if suggestion:
        lines.append(f"   建议: {suggestion}")
    snippet = _clip(_text(_field(finding, "code_snippet")), L3_SNIPPET_LIMIT)
    if snippet:
        lines.append("   代码:")
        lines.extend(f"     {line}" for line in snippet.splitlines())
    issues = _text_list(_field(finding, "evidence_issues"))
    if issues:
        lines.append(f"   疑点: {'; '.join(issues)}")
    return "\n".join(lines)


def _l3_section(blocks: list[str]) -> str:
    if not blocks:
        return ""
    return "\n".join([f"[L3 重点 FINDING 全文] 前 {len(blocks)} 条（按严重度排序）", *blocks])


def _render_l4(metadata: dict[str, Any]) -> str:
    """L4 被过滤计数：没有记录过 `filtered_findings` 就整段省略（不臆造 0）。"""
    stats = metadata.get("filtered_findings")
    if not isinstance(stats, dict) or not stats:
        return ""
    # 与 GitHub 评论、报告 `run.filtered`、历史详情的披露共用同一份归一化逻辑，
    # 四处不得对同一次 run 给出不同的门槛/计数。
    from ai_pr_review.cli import report_filtered_section

    section = report_filtered_section(stats)
    parts: list[str] = []
    threshold = section.get("threshold")
    if threshold is not None:
        parts.append(f"门槛 {float(threshold):.2f}")
    below = section.get("below_threshold")
    if below is not None:
        parts.append(f"低于门槛 {int(below)} 条")
    duplicates = section.get("duplicates")
    if duplicates is not None:
        parts.append(f"去重 {int(duplicates)} 条")
    if not parts:
        return ""
    return "[L4 被过滤 FINDING] " + " · ".join(parts)


# ---------------------------------------------------------------------------
# 字段读取与格式化
# ---------------------------------------------------------------------------


def _field(source: Any, name: str, default: Any = None) -> Any:
    """兼容 pydantic `Finding` 与 dict（测试替身）的字段读取。"""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            items.append(text)
    return items


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + TRUNCATION_MARK


def _severity(finding: Any) -> str:
    severity = _text(_field(finding, "severity")).lower()
    return severity if severity in SEVERITY_ORDER else "info"


def _severity_counts(findings: list[Any]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in findings:
        counts[_severity(finding)] += 1
    return counts


def _sorted_findings(findings: Any) -> list[Any]:
    """与 `PostProcessor.sort_by_severity` 同一套排序键（严重度 → 置信度 → 位置）。"""
    if not isinstance(findings, (list, tuple)):
        return []
    return sorted(findings, key=_sort_key)


def _sort_key(finding: Any) -> tuple[int, float, str, int, int, str]:
    return (
        SEVERITY_ORDER[_severity(finding)],
        -(_as_float(_field(finding, "confidence")) or 0.0),
        _text(_field(finding, "file")),
        _as_int(_field(finding, "line_start")) or 0,
        _as_int(_field(finding, "line_end")) or 0,
        _text(_field(finding, "title")),
    )


def _location(finding: Any) -> str:
    filename = _text(_field(finding, "file")) or "?"
    start = _as_int(_field(finding, "line_start"))
    end = _as_int(_field(finding, "line_end"))
    if start is None:
        return filename
    if end is None or end == start:
        return f"{filename}:{start}"
    return f"{filename}:{start}-{end}"


def _confidence_text(finding: Any) -> str:
    confidence = _as_float(_field(finding, "confidence"))
    if confidence is None:
        return ""
    return f"{round(confidence * 100)}%"


def _evidence_status(finding: Any) -> str:
    # 与 `_explain_run` 一致：没有记录校验状态时按 unverified 呈现，而不是留空。
    return _text(_field(finding, "evidence_status")) or "unverified"


def _finding_line(finding: Any) -> str:
    head = f"[{_severity(finding)}] {_location(finding)}"
    segments: list[str] = []
    confidence = _confidence_text(finding)
    if confidence:
        segments.append(f"置信度 {confidence}")
    segments.append(f"证据 {_evidence_status(finding)}")
    title = _clip(_text(_field(finding, "title")), L3_TITLE_LIMIT)
    if title:
        segments.append(title)
    return " · ".join([head, *segments])


def describe_run(run: dict[str, Any], metadata: dict[str, Any]) -> str:
    """一行 PR 标识（`owner/repo #31 · 标题`）；缺哪部分就少哪部分，全缺则空串。

    L1 与 `/context` 共用同一份命名逻辑，两处不能对同一次 run 给出不同说法。
    """
    owner = _text(run.get("repo_owner"))
    name = _text(run.get("repo_name"))
    repo = f"{owner}/{name}" if owner and name else (owner or name)
    parts: list[str] = []
    if repo:
        parts.append(repo)
    number = _as_int(run.get("pr_number"))
    if number is not None:
        parts.append(f"#{number}")
    title = _text(metadata.get("pr_title"))
    head = " ".join(parts)
    return f"{head} · {title}" if head and title else (head or title)


def _files_line(run: dict[str, Any]) -> str:
    included = _as_int(run.get("included_files"))
    excluded = _as_int(run.get("excluded_files"))
    total = _as_int(run.get("total_files"))
    if included is None and excluded is None:
        return ""
    parts: list[str] = []
    if included is not None:
        parts.append(f"审查 {included}")
    if excluded is not None:
        parts.append(f"跳过 {excluded}")
    text = "文件: " + " · ".join(parts)
    if total is not None:
        text += f"（共 {total}）"
    return text


def _validation_line(metadata: dict[str, Any]) -> str:
    summary = metadata.get("validation_summary")
    if not isinstance(summary, dict):
        return ""
    parts = [
        f"{status} {count}"
        for status in ("valid", "needs_review", "invalid")
        if (count := _as_int(summary.get(status))) is not None
    ]
    if not parts:
        return ""
    return "证据校验: " + " · ".join(parts)
