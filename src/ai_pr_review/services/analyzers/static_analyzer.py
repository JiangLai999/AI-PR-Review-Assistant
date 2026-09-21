"""Lightweight deterministic checks that complement model review."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from ai_pr_review.models.pr_data import FileDiff
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
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Dynamic code execution",
                    "The changed line executes dynamically constructed code, which can become arbitrary code execution when input is influenced by users.",
                    "Remove dynamic execution or strictly constrain and validate the input before using a safe alternative.",
                    "security",
                    "high",
                    line,
                    0.98,
                    "dynamic_execution",
                )
            )
        if "dangerouslysetinnerhtml" in lowered or "innerhtml" in lowered:
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Potential HTML injection",
                    "The changed line writes HTML directly and may allow untrusted content to become executable markup.",
                    "Prefer escaped text rendering or sanitize untrusted HTML with a well-maintained allowlist.",
                    "security",
                    "high",
                    line,
                    0.94,
                    "html_injection",
                )
            )
        if re.search(r"(?:password|api[_-]?key|secret|token)\s*=\s*['\"]", line, re.I):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Possible hard-coded secret",
                    "A credential-like value appears to be assigned directly in source code.",
                    "Move the value to a secret manager or environment variable and rotate it if it was real.",
                    "security",
                    "critical",
                    line,
                    0.91,
                    "hardcoded_secret",
                )
            )
        if re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", line, re.I) and re.search(
            r"""\bf["']|\.format\(|%\s*\w|\+\s*\w""", line, re.I
        ):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Possible SQL injection",
                    "SQL text appears to be assembled with string interpolation or concatenation.",
                    "Use parameterized queries or the database library's bound-parameter API.",
                    "security",
                    "high",
                    line,
                    0.88,
                    "sql_interpolation",
                )
            )
        if re.search(r"\byaml\.load\s*\(", line) and not re.search(
            r"SafeLoader|safe_load|Loader\s*=", line
        ):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Unsafe YAML deserialization",
                    "`yaml.load` without a safe loader can construct arbitrary Python objects from untrusted input.",
                    "Use `yaml.safe_load` or pass `Loader=yaml.SafeLoader` explicitly.",
                    "security",
                    "critical",
                    line,
                    0.9,
                    "unsafe_yaml_load",
                )
            )
        if re.search(r"\bverify\s*=\s*False\b", line):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "TLS certificate verification disabled",
                    "Certificate verification is turned off, so the connection is open to man-in-the-middle interception.",
                    "Remove `verify=False` and trust a proper CA bundle instead.",
                    "security",
                    "high",
                    line,
                    0.9,
                    "tls_verification_disabled",
                )
            )
        if re.search(
            r"\b(?:SECRET|TOKEN|PASSWORD|API_?KEY)_?[A-Z0-9_]*\b\s*=\s*['\"][^'\"]{8,}['\"]", line
        ):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Possible hard-coded credential constant",
                    "A credential-looking constant is assigned a literal secret value in source code.",
                    "Load the secret from the environment or a secret manager, and rotate it if it was real.",
                    "security",
                    "critical",
                    line,
                    0.85,
                    "hardcoded_credential_constant",
                )
            )
        if (
            re.search(r"\bdebug\s*=\s*True\b", line, re.I)
            or re.search(r"""\[['"]DEBUG['"]\]\s*=\s*True""", line)
        ) and not re.search(r"#\s*noqa|test|dev", line, re.I):
            findings.append(
                self._finding(
                    filename,
                    line_number,
                    "Debug mode may be enabled in production",
                    "A debug flag is hard-coded to True, which can expose stack traces and an interactive debugger.",
                    "Drive the flag from configuration or the environment instead of source.",
                    "security",
                    "medium",
                    line,
                    0.7,
                    "debug_mode_enabled",
                )
            )
        return findings

    def _finding(
        self,
        filename: str,
        line_number: int,
        title: str,
        problem: str,
        suggestion: str,
        category: str,
        severity: str,
        snippet: str,
        confidence: float,
        rule: str,
    ) -> Finding:
        raw_id = f"{filename}:{line_number}:{rule}"
        finding_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]
        return Finding(
            finding_id=finding_id,
            severity=severity,
            category=category,
            file=filename,
            line_start=line_number,
            line_end=line_number,
            title=title,
            problem=problem,
            suggestion=suggestion,
            confidence=confidence,
            code_snippet=snippet.strip(),
            sources=["static_rule"],
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
