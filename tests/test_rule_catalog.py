"""规则目录（`rule_catalog`）覆盖与中文本地化测试。

对应 P6 计划 §3.4：
- 目录覆盖：每条规则都有三段中文文案，无空值；
- 反向覆盖：扫描两个分析器的 `_finding(...)` 调用，规则键必须全部登记在目录里；
- 中文渲染：`static_rule` finding 在 zh 语言下标题/问题/建议全部为中文。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.analyzers import python_ast_analyzer, rule_catalog, static_analyzer
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.rule_catalog import RULE_CATALOG, TLS_AST_RULE_KEY
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.finding_localizer import _RULE_ZH, localize_deterministic_finding

CJK_PATTERN = re.compile("[一-鿿]")

ANALYZER_MODULES = (static_analyzer, python_ast_analyzer)


def build_file(source: str, filename: str = "src/app.py") -> tuple[FileDiff, object]:
    """把整段源码标记为变更行，便于规则命中。"""
    lines = source.splitlines()
    patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    file_diff = FileDiff(
        filename=filename,
        status=FileStatus.MODIFIED,
        additions=len(lines),
        changes=len(lines),
        patch=patch,
    )
    return file_diff, ContextBuilder().build_context(filename, patch, source)


def static_findings(source: str):
    return StaticAnalyzer().analyze(*build_file(source))


def ast_findings(source: str):
    return PythonAstAnalyzer().analyze(*build_file(source))


# 每个规则键一段能触发它的最小源码。
TRIGGERS = {
    "dynamic_execution": (static_findings, "eval(user_input)"),
    "html_injection": (static_findings, "element.innerHTML = data"),
    "hardcoded_secret": (static_findings, 'password = "hunter2secret"'),
    "sql_interpolation": (static_findings, 'q = f"SELECT * FROM t WHERE {x}"'),
    "unsafe_yaml_load": (static_findings, "data = yaml.load(payload)"),
    "hardcoded_credential_constant": (static_findings, 'API_KEY = "abcdef1234567890"'),
    "debug_mode_enabled": (static_findings, "run(debug=True)"),
    "mutable_default_argument": (
        ast_findings,
        "def collect(item, bucket=[]):\n    return bucket\n",
    ),
    "bare_except": (
        ast_findings,
        "def run():\n    try:\n        pass\n    except:\n        pass\n",
    ),
    "raise_without_from": (
        ast_findings,
        "def run():\n    try:\n        pass\n"
        "    except Exception:\n        raise RuntimeError('x')\n",
    ),
    "uncontextualised_value_error": (
        ast_findings,
        "def parse(raw):\n    raise ValueError(f'bad {raw}')\n",
    ),
    "weak_hash_algorithm": (ast_findings, "digest = hashlib.md5(payload)"),
    "is_literal_comparison": (ast_findings, "def check(value):\n    return value is 5\n"),
    "unsafe_deserialization": (ast_findings, "obj = pickle.loads(payload)"),
    "subprocess_shell_true": (ast_findings, "subprocess.run(cmd, shell=True)"),
    "http_request_without_timeout": (ast_findings, "response = requests.get(url)"),
    "unclosed_resource": (ast_findings, 'handle = open("out.txt", "w")\nhandle.write("x")\n'),
    # TLS 证书校验关闭在逐行与 AST 两侧各有实现，两个键都要被覆盖。
    "tls_verification_disabled": (static_findings, "requests.get(url, verify=False)"),
    TLS_AST_RULE_KEY: (ast_findings, "requests.get(url, verify=False)"),
}


def called_rule_keys(module) -> set[str]:
    """扫描模块源码里所有 `_finding(...)` 调用的规则键。

    用 AST 而不是正则：规则键既可能是字面量，也可能是目录导出的常量
    （`rule=TLS_AST_RULE_KEY`），这里按模块命名空间解析。
    """
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_finding"):
            continue

        target = node.args[0] if node.args else None
        for keyword in node.keywords:
            if keyword.arg == "rule":
                target = keyword.value

        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            keys.add(target.value)
        elif isinstance(target, ast.Name):
            resolved = getattr(module, target.id, None)
            assert isinstance(resolved, str), f"{module.__name__}: {target.id} 未解析为规则键"
            keys.add(resolved)
        else:  # pragma: no cover - 规则键写法不合规时直接失败
            raise AssertionError(f"{module.__name__}: _finding 调用缺少可解析的规则键")
    return keys


def finding_for(rule_key: str):
    """按触发源码取出该规则产出的第一条 finding。"""
    finder, source = TRIGGERS[rule_key]
    rule_id = RULE_CATALOG[rule_key].rule_id
    matched = [finding for finding in finder(source) if finding.rule_id == rule_id]
    assert matched, f"{rule_key} 没有产出 rule_id={rule_id} 的 finding"
    return matched[0]


class TestCatalogCoverage:
    def test_every_rule_has_chinese_copy(self):
        for key, definition in RULE_CATALOG.items():
            for english, chinese in (
                (definition.title, definition.title_zh),
                (definition.problem, definition.problem_zh),
                (definition.suggestion, definition.suggestion_zh),
            ):
                assert chinese.strip(), f"{key} 的中文文案为空"
                assert CJK_PATTERN.search(chinese), f"{key} 的中文文案不含汉字：{chinese!r}"
                assert chinese != english, f"{key} 的中文文案与英文完全相同"

    def test_rule_metadata_is_valid(self):
        for key, definition in RULE_CATALOG.items():
            assert definition.rule_id == key or key == TLS_AST_RULE_KEY
            assert definition.severity in {"critical", "high", "medium", "low", "info"}
            assert definition.category in {
                "correctness",
                "security",
                "resource",
                "error_handling",
                "performance",
                "concurrency",
                "architecture",
            }
            assert 0.0 < definition.confidence <= 1.0

    def test_records_sharing_a_rule_id_share_their_chinese_copy(self):
        by_rule_id: dict[str, list] = {}
        for definition in RULE_CATALOG.values():
            by_rule_id.setdefault(definition.rule_id, []).append(definition)

        assert len(by_rule_id) == 18
        for rule_id, definitions in by_rule_id.items():
            expected = definitions[0]
            for definition in definitions[1:]:
                assert (definition.title_zh, definition.problem_zh, definition.suggestion_zh) == (
                    expected.title_zh,
                    expected.problem_zh,
                    expected.suggestion_zh,
                ), f"{rule_id} 的多条记录中文文案不一致"
                assert definition.title == expected.title

    def test_every_catalog_entry_has_a_trigger(self):
        assert set(RULE_CATALOG) == set(TRIGGERS)


class TestReverseCoverage:
    def test_analyzer_call_sites_are_all_in_catalog(self):
        for module in ANALYZER_MODULES:
            keys = called_rule_keys(module)
            assert keys, f"{module.__name__} 里没有扫描到 _finding 调用"
            unknown = keys - set(RULE_CATALOG)
            assert not unknown, f"{module.__name__} 使用了未登记的规则键：{sorted(unknown)}"

    def test_catalog_has_no_unused_entry(self):
        used: set[str] = set()
        for module in ANALYZER_MODULES:
            used |= called_rule_keys(module)

        assert used == set(RULE_CATALOG), f"目录与实现不一致：{sorted(set(RULE_CATALOG) ^ used)}"

    def test_analyzer_findings_match_catalog_text(self):
        for key in TRIGGERS:
            definition = RULE_CATALOG[key]
            produced = finding_for(key)

            assert produced.sources == ["static_rule"]
            assert (
                definition.localize(produced.title) is not None
            ), f"{key} 的标题与目录模板不一致：{produced.title!r}"
            if "{" not in definition.title:
                assert produced.title == definition.title
            if "{" not in definition.problem:
                assert produced.problem == definition.problem
            assert produced.suggestion == definition.suggestion
            assert produced.category == definition.category
            assert produced.severity == definition.severity
            assert produced.confidence == definition.confidence


class TestChineseRendering:
    def test_static_rule_findings_render_fully_in_chinese(self):
        for key in TRIGGERS:
            finding = finding_for(key)

            localized = localize_deterministic_finding(finding, "zh-CN")

            for english, chinese in (
                (finding.title, localized.title),
                (finding.problem, localized.problem),
                (finding.suggestion, localized.suggestion),
            ):
                assert CJK_PATTERN.search(chinese), f"{key} 未本地化：{chinese!r}"
                assert chinese != english, f"{key} 仍是英文：{chinese!r}"
            assert localized.sources == ["static_rule"]
            assert localized.rule_id == finding.rule_id

    def test_dynamic_title_localization_keeps_the_variant(self):
        weak_hash = ast_findings("digest = hashlib.md5(payload)")[0]
        deserialization = ast_findings("obj = pickle.loads(payload)")[0]

        assert localize_deterministic_finding(weak_hash, "zh-CN").title == "弱哈希算法（md5）"
        assert (
            localize_deterministic_finding(deserialization, "zh-CN").title
            == "不安全的反序列化（pickle）"
        )

    def test_tls_rules_from_both_analyzers_share_the_chinese_copy(self):
        line_finding = finding_for("tls_verification_disabled")
        ast_finding = finding_for(TLS_AST_RULE_KEY)

        assert line_finding.problem != ast_finding.problem
        assert localize_deterministic_finding(line_finding, "zh-CN").problem == (
            localize_deterministic_finding(ast_finding, "zh-CN").problem
        )

    def test_catalog_chinese_matches_legacy_table(self):
        """旧表覆盖的规则，中文输出必须与改造前一致（无行为回归）。"""
        legacy_titles = set(_RULE_ZH)
        catalog_titles = {definition.title for definition in RULE_CATALOG.values()}

        assert legacy_titles <= catalog_titles
        for definition in RULE_CATALOG.values():
            if definition.title not in _RULE_ZH:
                continue
            title_zh, problem_zh, suggestion_zh = _RULE_ZH[definition.title]
            assert definition.title_zh == title_zh
            assert definition.problem_zh == problem_zh
            assert definition.suggestion_zh == suggestion_zh

    def test_english_language_keeps_the_original_text(self):
        finding = finding_for("dynamic_execution")

        assert localize_deterministic_finding(finding, "en-US") == finding

    def test_rule_catalog_exports_rule_ids(self):
        assert rule_catalog.all_rule_ids() == {
            definition.rule_id for definition in RULE_CATALOG.values()
        }
        assert (
            rule_catalog.rule_for_id("tls_verification_disabled")
            is RULE_CATALOG["tls_verification_disabled"]
        )
        assert rule_catalog.rule_for_id("") is None
        assert rule_catalog.rule_for_id("not-a-rule") is None
