"""`finding_localizer`：按 rule_id 本地化与旧标题表回退的行为测试。"""

from __future__ import annotations

from ai_pr_review.services.finding_localizer import localize_deterministic_finding
from ai_pr_review.services.prompt_assembler import Finding


def build_finding(**overrides) -> Finding:
    payload = {
        "severity": "high",
        "category": "security",
        "file": "src/app.py",
        "line_start": 3,
        "line_end": 3,
        "title": "Possible SQL injection",
        "problem": "SQL text appears to be assembled with string interpolation.",
        "suggestion": "Use parameterized queries.",
        "confidence": 0.9,
        "code_snippet": 'query = f"SELECT * FROM t WHERE {x}"',
        "sources": ["static_rule"],
    }
    payload.update(overrides)
    return Finding(**payload)


class TestRuleIdLocalization:
    def test_localizes_by_rule_id(self):
        finding = build_finding(
            rule_id="sql_interpolation",
            title="Possible SQL injection",
            category="security",
        )

        localized = localize_deterministic_finding(finding, "zh-CN")

        assert localized.title == "可能的 SQL 注入"
        assert localized.category == "安全性"
        assert localized.rule_id == "sql_interpolation"
        assert localized.sources == ["static_rule"]

    def test_rule_id_with_mismatched_title_falls_back_to_the_title_table(self):
        # rule_id 与标题指的不是同一条规则（例如历史库被人工改写过标题）时，
        # 目录无法反解动态片段，退回按标题匹配的旧表。
        finding = build_finding(rule_id="dynamic_execution", title="Unsafe YAML deserialization")

        localized = localize_deterministic_finding(finding, "zh-CN")

        assert localized.title == "不安全的 YAML 反序列化"

    def test_title_rewritten_by_hand_falls_back_to_english(self):
        finding = build_finding(rule_id="sql_interpolation", title="SQL injection (v2)")

        assert localize_deterministic_finding(finding, "zh-CN") == finding


class TestLegacyFallback:
    def test_legacy_title_without_rule_id_is_still_localized(self):
        finding = build_finding(title="Bare except swallows every exception")

        localized = localize_deterministic_finding(finding, "zh-CN")

        assert localized.title == "裸 except 捕获所有异常"

    def test_legacy_title_variant_appends_the_suffix(self):
        finding = build_finding(title="Mutable default argument (legacy)")

        localized = localize_deterministic_finding(finding, "zh-CN")

        assert localized.title == "可变默认参数（legacy）"

    def test_unknown_rule_id_and_title_stays_english(self):
        finding = build_finding(rule_id="not_a_rule", title="Something entirely new")

        assert localize_deterministic_finding(finding, "zh-CN") == finding


class TestLocalizationGates:
    def test_model_findings_are_never_localized(self):
        finding = build_finding(sources=["ai_analysis"])

        assert localize_deterministic_finding(finding, "zh-CN") == finding

    def test_model_finding_cannot_fake_a_rule_id(self):
        # 模型产出的 finding 即使自述了规则身份，来源不是 static_rule 也不会本地化。
        finding = build_finding(sources=["ai_analysis"], rule_id="sql_interpolation")

        assert localize_deterministic_finding(finding, "zh-CN").title == finding.title

    def test_non_chinese_language_keeps_the_finding(self):
        finding = build_finding(rule_id="sql_interpolation")

        assert localize_deterministic_finding(finding, "en-US") == finding
        assert localize_deterministic_finding(finding, "ja-JP") == finding
