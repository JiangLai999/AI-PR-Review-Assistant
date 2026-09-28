"""审查计划文案的双语化回归（用户诉求：规划依据纳入中英文统一约束）。

计划是**确定性代码**生成的（`services/agent/planner.py`，不调模型），所以这些句子
完全由我们控制：句子跟着 `preferences.language` 出中英两版，而
`risk_categories` / `strategies` 保持规范 id —— 前者给「规划依据」用，后两者由前端
按 id 查词典渲染（否则同一套词汇要在前后端各存一份，迟早漂移）。
"""

from __future__ import annotations

import re

import pytest

from ai_pr_review.config import AppConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.agent.planner import ReviewPlanner
from ai_pr_review.services.filter_pipeline import FilterPipeline
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator

_CJK = re.compile(r"[\u4e00-\u9fff]")


def build_pr(
    *files: FileDiff,
    title: str = "Fix authentication API",
    description: str = "Update token handling and API validation.",
) -> PRData:
    return PRData(
        pr_number=1,
        title=title,
        description=description,
        author="tester",
        state="open",
        head_sha="head",
        base_sha="base",
        head_ref="feature",
        base_ref="main",
        files=list(files),
        url="https://github.com/example/repo/pull/1",
        owner="example",
        repo="repo",
    )


def risky_files() -> list[FileDiff]:
    """两个文件 + security/api 词面 → 必然触发分类与跨文件复核。"""
    return [
        FileDiff(
            filename="src/auth_service.py",
            status=FileStatus.MODIFIED,
            additions=2,
            changes=2,
            patch="@@ -1 +1,3 @@\n old\n+new\n+new2",
        ),
        FileDiff(
            filename="src/api_router.py",
            status=FileStatus.MODIFIED,
            additions=1,
            changes=1,
            patch="@@ -1 +1,2 @@\n old\n+new",
        ),
    ]


def build_plan(
    *,
    language: str | None,
    title: str = "Fix authentication API",
    description: str = "Update token handling and API validation.",
):
    pr = build_pr(*risky_files(), title=title, description=description)
    _, filter_result = FilterPipeline().filter_pr_data(pr)
    return ReviewPlanner().build_plan(pr, filter_result, language=language)


def test_rationale_follows_the_language():
    english = build_plan(language="en-US")
    chinese = build_plan(language="zh-CN")

    assert english.rationale and chinese.rationale
    assert all(not _CJK.search(line) for line in english.rationale), english.rationale
    assert all(_CJK.search(line) for line in chinese.rationale), chinese.rationale
    assert english.rationale != chinese.rationale


@pytest.mark.parametrize("language", [None, ""])
def test_rationale_falls_back_to_chinese_without_a_language(language):
    """与 `services/i18n_text.py` 的既有约定一致：拿不到语言回落中文。"""
    plan = build_plan(language=language)

    assert all(_CJK.search(line) for line in plan.rationale), plan.rationale


def test_rationale_never_embeds_canonical_ids():
    """规范 id 不进句子：它们由前端按 id 渲染成中文/英文，写进句子就会两头不一致。"""
    for language in ("zh-CN", "en-US"):
        plan = build_plan(language=language)
        joined = " ".join(plan.rationale)
        for category in plan.risk_categories:
            assert category not in joined, (language, category, joined)
        for strategy in plan.strategies:
            assert strategy not in joined, (language, strategy, joined)


def test_categories_and_strategies_stay_canonical_ids():
    """这两个字段是给前端查词典用的 id，任何语言下都不翻译。"""
    chinese = build_plan(language="zh-CN")

    assert "security" in chinese.risk_categories
    assert "cross_file_impact_review" in chinese.strategies
    assert "risk_category_review" in chinese.strategies
    assert all(not _CJK.search(value) for value in chinese.risk_categories)
    assert all(not _CJK.search(value) for value in chinese.strategies)


def test_default_intent_is_localized_but_real_titles_are_untouched():
    # 标题与描述都为空才会走"默认意图"分支
    english = build_plan(language="en-US", title="", description="")
    chinese = build_plan(language="zh-CN", title="", description="")

    assert not _CJK.search(english.intent)
    assert _CJK.search(chinese.intent)
    assert english.intent != chinese.intent

    # 标题是用户内容：原样透传，绝不翻译（这里是中文标题 + 英文界面）。
    mixed = build_plan(language="en-US", title="修复 token 处理")
    assert mixed.intent.startswith("修复 token 处理")


async def test_orchestrator_plan_only_uses_the_configured_language(monkeypatch):
    """接线验证：`plan_only` 必须把 `preferences.ui_language` 传到 planner。

    用 ui_language 而不是 language，是 `services/i18n_text` 的既有分工：
    前者管"生成时冻结的展示文案"（摘要/过滤原因/计划），后者管模型回答语言。
    这里刻意把两者设成相反值，谁被用错都会红。
    """
    pr = build_pr(*risky_files())
    config = AppConfig.from_env()
    config.preferences.ui_language = "en-US"
    config.preferences.language = "zh-CN"
    # PRFetcher 的构造函数要求有 token；这里只验证"语言是否传到了 planner"，
    # 所以给一个可识别的假 token，不读环境变量、不联网。
    config.github_token = "ghp_test-fake-token"
    config.pr_fetcher.github_token = "ghp_test-fake-token"
    orchestrator = ReviewOrchestrator(config)
    monkeypatch.setattr(orchestrator._pr_fetcher, "fetch", lambda _url: pr)

    artifacts = await orchestrator.plan_only("https://github.com/example/repo/pull/1")

    assert artifacts.review_plan is not None
    assert all(not _CJK.search(line) for line in artifacts.review_plan.rationale)
