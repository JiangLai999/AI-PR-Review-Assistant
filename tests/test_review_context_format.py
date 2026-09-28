"""追问审查的**排版规则**测试（`services/review_context.py` 的双语 `ANSWER_FORMAT_RULES`）。

规则文案是注入 system prompt 的契约：前端用受限 Markdown 渲染器，白名单之外的语法
（HTML 标签、图片、脚注）渲染不出来，而"结论先行 / 引用 `文件:行` / 上下文没有就说
需要查看源码"是回答质量的底线。因此逐条断言**具体子串**，而不是只看长度或非空。
"""

from __future__ import annotations

import re

import pytest

from ai_pr_review.services.review_context import (
    ANSWER_FORMAT_RULES_EN,
    ANSWER_FORMAT_RULES_ZH,
    CONTEXT_RULES,
    answer_format_rules,
    wrap_review_context,
)

# 中文字符（基本区）：中文规则至少命中一次，英文规则里一个都不该出现。
CJK = re.compile("[\\u4e00-\\u9fff]")


def test_language_selector_english_else_chinese():
    assert answer_format_rules("en-US") == ANSWER_FORMAT_RULES_EN
    assert answer_format_rules("en") == ANSWER_FORMAT_RULES_EN
    assert answer_format_rules("EN_gb") == ANSWER_FORMAT_RULES_EN
    assert answer_format_rules("zh-CN") == ANSWER_FORMAT_RULES_ZH
    # 语言缺失/空串一律回落中文（默认语言），不能返回空规则。
    assert answer_format_rules(None) == ANSWER_FORMAT_RULES_ZH
    assert answer_format_rules("") == ANSWER_FORMAT_RULES_ZH
    assert ANSWER_FORMAT_RULES_ZH != ANSWER_FORMAT_RULES_EN


def test_english_rules_have_no_chinese_and_chinese_rules_have_chinese():
    assert CJK.search(ANSWER_FORMAT_RULES_EN) is None
    assert ANSWER_FORMAT_RULES_EN.isascii()
    assert CJK.search(ANSWER_FORMAT_RULES_ZH) is not None


def test_both_languages_cover_the_renderer_whitelist():
    for token in (
        "#/##/###",
        "- 或 1. 列表",
        "**加粗**",
        "`行内代码`",
        "```",
        "最多 4 列",
        "> 引用",
    ):
        assert token in ANSWER_FORMAT_RULES_ZH, token
    for token in (
        "#/##/###",
        "- or 1. lists",
        "**bold**",
        "`inline code`",
        "```",
        "4 columns max",
        "> blockquotes",
    ):
        assert token in ANSWER_FORMAT_RULES_EN, token


def test_both_languages_forbid_html_and_image_syntax():
    assert "禁止 HTML 标签" in ANSWER_FORMAT_RULES_ZH
    assert "禁止图片语法" in ANSWER_FORMAT_RULES_ZH
    assert "禁止脚注与 HTML 表格" in ANSWER_FORMAT_RULES_ZH
    assert "No HTML tags" in ANSWER_FORMAT_RULES_EN
    assert "no image syntax" in ANSWER_FORMAT_RULES_EN
    assert "no footnotes or HTML tables" in ANSWER_FORMAT_RULES_EN


def test_both_languages_keep_the_honesty_and_citation_rules():
    # 与 CONTEXT_RULES 第 2/3 条同义，不得互相矛盾。
    assert "文件:行" in ANSWER_FORMAT_RULES_ZH
    assert "严重度" in ANSWER_FORMAT_RULES_ZH
    assert "需要查看源码" in ANSWER_FORMAT_RULES_ZH
    assert "file:line" in ANSWER_FORMAT_RULES_EN
    assert "severity" in ANSWER_FORMAT_RULES_EN
    assert "source code must be inspected" in ANSWER_FORMAT_RULES_EN


def test_both_languages_state_the_conclusion_and_length_limits():
    assert "结论先行" in ANSWER_FORMAT_RULES_ZH
    assert "400 字" in ANSWER_FORMAT_RULES_ZH
    assert "30 行" in ANSWER_FORMAT_RULES_ZH
    assert "Conclusion first" in ANSWER_FORMAT_RULES_EN
    assert "400 words" in ANSWER_FORMAT_RULES_EN
    assert "30 lines" in ANSWER_FORMAT_RULES_EN


def test_wrap_review_context_defaults_to_chinese_rules():
    text = wrap_review_context("run-x", "CTX")
    assert '<review_context run_id="run-x">' in text
    assert "\nCTX\n</review_context>\n" in text
    assert CONTEXT_RULES in text
    assert CONTEXT_RULES.split("\n", 1)[0] in text  # 诚实约束首行仍然在
    assert ANSWER_FORMAT_RULES_ZH in text
    assert ANSWER_FORMAT_RULES_EN not in text
    # 排版规则排在诚实约束之后（先讲依据，再讲怎么写）。
    assert text.index(CONTEXT_RULES) < text.index(ANSWER_FORMAT_RULES_ZH)


def test_wrap_review_context_english_switches_only_the_format_rules():
    text = wrap_review_context("run-x", "CTX", language="en-US")
    assert '<review_context run_id="run-x">' in text
    assert ANSWER_FORMAT_RULES_EN in text
    assert ANSWER_FORMAT_RULES_ZH not in text
    # 上下文块与诚实约束不受语言影响（既有契约零改动）。
    assert "\nCTX\n</review_context>\n" in text
    assert CONTEXT_RULES in text


def test_language_is_keyword_only_so_existing_callers_are_unaffected():
    with pytest.raises(TypeError):
        wrap_review_context("run-x", "CTX", "en-US")  # type: ignore[misc]
