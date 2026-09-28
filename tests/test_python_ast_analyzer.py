"""Python AST 分析器与扩展静态规则测试。"""

from __future__ import annotations

from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder


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
    context = ContextBuilder().build_context(filename, patch, source)
    return file_diff, context


def rules_for(source: str) -> list[str]:
    file_diff, context = build_file(source)
    findings = PythonAstAnalyzer().analyze(file_diff, context)
    return [finding.title for finding in findings]


class TestPythonAstAnalyzer:
    def test_detects_mutable_default_argument(self):
        source = "def collect(item, bucket=[], cache={}):\n    return bucket\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert len(findings) == 1
        assert findings[0].title == "Mutable default argument"
        assert "`bucket`" in findings[0].problem
        assert "`cache`" in findings[0].problem
        assert findings[0].category == "correctness"
        assert findings[0].sources == ["static_rule"]

    def test_ignores_immutable_defaults(self):
        source = "def collect(item, count=0, label='x', flag=None):\n    return count\n"

        assert PythonAstAnalyzer().analyze(*build_file(source)) == []

    def test_detects_bare_except(self):
        source = "def run():\n    try:\n        pass\n    except:\n        pass\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any(finding.title == "Bare except swallows every exception" for finding in findings)

    def test_ignores_typed_except(self):
        source = "def run():\n    try:\n        pass\n    except ValueError:\n        pass\n"

        assert PythonAstAnalyzer().analyze(*build_file(source)) == []

    def test_detects_unsafe_deserialization(self):
        source = "import pickle\n\ndef load(payload):\n    return pickle.loads(payload)\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any("Unsafe deserialization" in finding.title for finding in findings)
        assert any(finding.severity == "critical" for finding in findings)

    def test_detects_subprocess_shell_true(self):
        source = "import subprocess\n\ndef run(cmd):\n    subprocess.run(cmd, shell=True)\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any("shell=True" in finding.title for finding in findings)

    def test_detects_disabled_tls_verification(self):
        source = "import requests\n\ndef fetch(url):\n    return requests.get(url, verify=False)\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any("TLS certificate verification" in finding.title for finding in findings)

    def test_detects_identity_comparison_with_literal(self):
        source = "def check(value):\n    return value is 5\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any("Identity comparison" in finding.title for finding in findings)

    def test_allows_identity_comparison_with_none(self):
        source = "def check(value):\n    return value is None\n"

        assert PythonAstAnalyzer().analyze(*build_file(source)) == []

    def test_detects_unclosed_resource(self):
        source = 'def write():\n    handle = open("out.txt", "w")\n    handle.write("x")\n'

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert any("without guaranteed cleanup" in finding.title for finding in findings)

    def test_with_block_resource_is_not_reported(self):
        source = (
            'def write():\n    with open("out.txt", "w") as handle:\n        handle.write("x")\n'
        )

        assert PythonAstAnalyzer().analyze(*build_file(source)) == []

    def test_skips_non_python_files(self):
        source = "def collect(item, bucket=[]):\n    return bucket\n"
        file_diff, _ = build_file(source, filename="src/app.js")
        _, context = build_file(source, filename="src/app.js")

        assert PythonAstAnalyzer().analyze(file_diff, context) == []

    def test_syntax_error_is_ignored(self):
        source = "def broken(:\n    pass\n"

        assert PythonAstAnalyzer().analyze(*build_file(source)) == []

    def test_only_reports_findings_on_changed_lines(self):
        source = "def collect(item, bucket=[]):\n    return bucket\n"
        lines = source.splitlines()
        patch = f"@@ -1,1 +1,1 @@\n{lines[0]}\n+{lines[1]}\n"
        file_diff = FileDiff(
            filename="src/app.py",
            status=FileStatus.MODIFIED,
            additions=1,
            changes=1,
            patch=patch,
        )
        context = ContextBuilder().build_context("src/app.py", patch, source)

        # 第 1 行是上下文行（未变更），因此可变默认参数不应被报告。
        assert PythonAstAnalyzer().analyze(file_diff, context) == []

    def test_findings_carry_usable_evidence(self):
        source = "def collect(item, bucket=[]):\n    return bucket\n"

        findings = PythonAstAnalyzer().analyze(*build_file(source))

        assert findings[0].finding_id
        assert findings[0].line_start == 1
        assert findings[0].line_end == 1
        assert findings[0].code_snippet == "def collect(item, bucket=[]):"


class TestExtendedStaticRules:
    def _rules(self, line: str) -> list[str]:
        source = f"x = 1\n{line}\n"
        file_diff, context = build_file(source)
        return [f.title for f in StaticAnalyzer().analyze(file_diff, context)]

    def test_detects_unsafe_yaml_load(self):
        assert "Unsafe YAML deserialization" in self._rules("data = yaml.load(payload)")

    def test_allows_safe_yaml_load(self):
        assert "Unsafe YAML deserialization" not in self._rules("data = yaml.safe_load(payload)")

    def test_allows_yaml_load_with_safe_loader(self):
        assert "Unsafe YAML deserialization" not in self._rules(
            "data = yaml.load(payload, Loader=yaml.SafeLoader)"
        )

    def test_detects_verify_false(self):
        assert "TLS certificate verification disabled" in self._rules(
            "response = requests.get(url, verify=False)"
        )

    def test_detects_hardcoded_credential_constant(self):
        assert "Possible hard-coded credential constant" in self._rules(
            'API_KEY = "abcdef1234567890"'
        )

    def test_ignores_env_loaded_credential(self):
        assert "Possible hard-coded credential constant" not in self._rules(
            "API_KEY = os.environ['API_KEY']"
        )

    def test_detects_debug_mode(self):
        assert "Debug mode may be enabled in production" in self._rules("run(debug=True)")
        assert "Debug mode may be enabled in production" in self._rules("settings['DEBUG'] = True")

    def test_ignores_debug_lookalike_names(self):
        assert "Debug mode may be enabled in production" not in self._rules("debug_logging = True")

    def test_existing_rules_still_work(self):
        assert "Dynamic code execution" in self._rules("eval(user_input)")
        assert "Possible SQL injection" in self._rules('q = f"SELECT * FROM t WHERE {x}"')
