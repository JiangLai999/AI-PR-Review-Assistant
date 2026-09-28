"""审查流水线文案的极小双语表（生成时本地化）。

与 A 类「结构化键」的分工：

- **结构化键**（``SaveResult.message_key`` / ``CredentialStatus.detail_key``）
  用于**活接口**：后端只发 key + params，前端按**当前语言**渲染，用户切语言
  立刻生效，不需要重新跑一次审查。
- **生成时本地化**（本模块）用于**写库的文案**：summary / 过滤原因随 run 一起
  落库，后端产出时就按当时 ``preferences.ui_language`` 生成字符串，读历史时
  原样回放。语言在生成时已冻结，事后切语言不会回溯翻译。

刻意不引依赖：只有两张字符串表 + 一个语言判定，任何 i18n 框架都过重。
"""

from __future__ import annotations


def is_english(language: object) -> bool:
    """与前端同口径：以 ``en`` 开头即英文（``en`` / ``en-US`` / ``en_GB``…）。"""
    return str(language or "").strip().lower().startswith("en")


def response_language_instruction(language: object) -> str:
    """「模型该用什么语言回答」这一句 system prompt。

    CLI 的 ``_send_chat_message`` 与 Web 的 `/api/chat` **共用同一份文案**：
    两端的回答语言必须由同一个设置（``preferences.language``）决定，否则同一次
    审查在 CLI 里答中文、在 Web 里答英文，用户会以为模型换了。
    """
    if is_english(language):
        return "Respond in English unless the user explicitly asks for another language."
    return "请默认使用中文回答，除非用户明确要求使用其他语言。"


def review_summary(language: object, findings: int) -> str:
    """审查完成摘要：zh ``审查完成，发现 {n} 个问题`` / en ``Review complete — {n} finding(s).``"""
    if is_english(language):
        return f"Review complete — {findings} finding(s)."
    return f"审查完成，发现 {findings} 个问题"


def filter_included_by_default(language: object) -> str:
    """文件未命中任何过滤规则时的默认纳入说明。"""
    if is_english(language):
        return "File did not match any filter rule; included by default."
    return "文件未命中过滤规则，默认纳入审查。"


# ---------------------------------------------------------------------------
# 审查计划（`services/agent/planner.py` 的确定性计划文案）
#
# 计划**不调模型**，这些句子全是我们自己写的，所以「规划依据」天然可以被双语化 ——
# 不需要提示词工程。`risk_categories` / `strategies` 保持规范 id（前端按 id 查词典渲染
# 成中文或英文），这里只负责**句子**，避免同一套词汇在前后端各存一份而漂移。
# ---------------------------------------------------------------------------


def plan_rationale_scope(language: object) -> str:
    """规划依据第 1 条：审查范围是怎么定下来的。"""
    if is_english(language):
        return "Review scope is derived from the PR metadata and the included file set."
    return "审查范围由 PR 元数据与纳入审查的文件集推导得出。"


def plan_rationale_cross_file(language: object) -> str:
    """规划依据第 2 条：为什么需要跨文件复核。"""
    if is_english(language):
        return "Multiple files or interface-sensitive changes require a cross-file pass."
    return "涉及多个文件或接口敏感改动，需要做一次跨文件复核。"


def plan_default_intent(language: object) -> str:
    """PR 标题与描述都为空时的默认审查意图。"""
    if is_english(language):
        return "Review the pull request for correctness and security risks."
    return "审查该 PR 的正确性与安全风险。"
