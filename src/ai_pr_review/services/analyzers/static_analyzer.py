"""Lightweight deterministic checks that complement model review."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.services.analyzers.rule_catalog import get_rule
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.prompt_assembler import Finding


class StaticAnalyzer:
    """Run safe, dependency-free checks on changed lines."""

    def analyze(self, file_diff: FileDiff, context: FileContext) -> list[Finding]:
        content = getattr(context, "full_content", "") or ""
        if not content:
            content = context.diff
        lines = content.splitlines()
        changed_lines = self._changed_lines(file_diff.patch or "")
        findings: list[Finding] = []
        for line_number in sorted(changed_lines or range(1, len(lines) + 1)):
            if line_number > len(lines):
                continue
            line = lines[line_number - 1]
            findings.extend(self._check_line(file_diff.filename, line_number, line))
        return findings

    def _check_line(self, filename: str, line_number: int, line: str) -> list[Finding]:
        findings: list[Finding] = []
        lowered = line.lower()
        if re.search(r"\b(eval|exec)\s*\(", line):
            findings.append(self._finding(filename, line_number, line, rule="dynamic_execution"))
        if "dangerouslysetinnerhtml" in lowered or "innerhtml" in lowered:
            findings.append(self._finding(filename, line_number, line, rule="html_injection"))
        if re.search(r"(?:password|api[_-]?key|secret|token)\s*=\s*['\"]", line, re.I):
            findings.append(self._finding(filename, line_number, line, rule="hardcoded_secret"))
        if re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", line, re.I) and re.search(
            r"""\bf["']|\.format\(|%\s*\w|\+\s*\w""", line, re.I
        ):
            findings.append(self._finding(filename, line_number, line, rule="sql_interpolation"))
        if re.search(r"\byaml\.load\s*\(", line) and not re.search(
            r"SafeLoader|safe_load|Loader\s*=", line
        ):
            findings.append(self._finding(filename, line_number, line, rule="unsafe_yaml_load"))
        if re.search(r"\bverify\s*=\s*False\b", line):
            findings.append(
                self._finding(filename, line_number, line, rule="tls_verification_disabled")
            )
        if re.search(
            r"\b(?:SECRET|TOKEN|PASSWORD|API_?KEY)_?[A-Z0-9_]*\b\s*=\s*['\"][^'\"]{8,}['\"]", line
        ):
            findings.append(
                self._finding(
                    filename, line_number, line, rule="hardcoded_credential_constant"
                )
            )
        if (
            re.search(r"\bdebug\s*=\s*True\b", line, re.I)
            or re.search(r"""\[['"]DEBUG['"]\]\s*=\s*True""", line)
        ) and not re.search(r"#\s*noqa|test|dev", line, re.I):
            findings.append(self._finding(filename, line_number, line, rule="debug_mode_enabled"))
        return findings

    def _finding(
        self,
        filename: str,
        line_number: int,
        snippet: str,
        *,
        rule: str,
        **params: str,
    ) -> Finding:
        """按规则键从目录取文案构造 Finding。

        规则键保持 `rule="..."` 关键字形式：`web_server.count_deterministic_rules()`
        与 `tests/test_rule_catalog.py` 都靠它把规则数量与目录对齐。
        """
        definition = get_rule(rule)
        raw_id = f"{filename}:{line_number}:{definition.rule_id}"
        finding_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]
        return Finding(
            finding_id=finding_id,
            file=filename,
            line_start=line_number,
            line_end=line_number,
            code_snippet=snippet.strip(),
            sources=["static_rule"],
            **definition.build_fields(),
        )

    def _changed_lines(self, patch: str) -> set[int]:
        changed: set[int] = set()
        current = 0
        in_hunk = False
        for raw_line in patch.splitlines():
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw_line)
            if match:
                current = int(match.group(1))
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if raw_line.startswith("+++"):
                continue
            if raw_line.startswith("+"):
                changed.add(current)
                current += 1
            elif raw_line.startswith("-") or raw_line.startswith("\\"):
                continue
            else:
                current += 1
        return changed
