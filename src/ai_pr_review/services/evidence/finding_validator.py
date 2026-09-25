"""Validate model findings against the actual PR evidence."""

from __future__ import annotations

import hashlib
import re

from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.models.review_plan import Evidence
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.prompt_assembler import Finding, finding_has_source


class FindingValidator:
    """Attach evidence status without silently deleting model output."""

    def validate(self, finding: Finding, file_diff: FileDiff, context: FileContext) -> Evidence:
        messages: list[str] = []
        valid_location = finding.file == file_diff.filename
        if not valid_location:
            messages.append("Finding file does not match the file being reviewed.")

        content = getattr(context, "full_content", "") or ""
        line_count = len(content.splitlines()) if content else None
        if finding.line_start < 1 or finding.line_end < finding.line_start:
            messages.append("Finding line range is invalid.")
        elif line_count is not None and finding.line_end > line_count:
            messages.append("Finding line range is outside the available file content.")

        changed_lines = self._changed_lines(file_diff.patch or "")
        changed_line = any(
            line in changed_lines for line in range(finding.line_start, finding.line_end + 1)
        )
        if not changed_line:
            messages.append("Finding does not point to a changed line in the PR diff.")

        snippet = finding.code_snippet.strip()
        snippet_matches = bool(snippet and self._snippet_matches(snippet, content))
        if snippet and not snippet_matches:
            messages.append("Code snippet was not found in the available file content.")

        if not valid_location or any(
            message in messages
            for message in (
                "Finding line range is invalid.",
                "Finding line range is outside the available file content.",
            )
        ):
            status = "invalid"
        elif messages:
            status = "needs_review"
        else:
            status = "valid"

        return Evidence(
            file=file_diff.filename,
            line_start=finding.line_start,
            line_end=finding.line_end,
            changed_line=changed_line,
            code_snippet=finding.code_snippet,
            source="static_rule" if finding_has_source(finding, "static_rule") else "ai_analysis",
            validation_status=status,
            validation_messages=messages,
        )

    def validate_against_contexts(
        self,
        finding: Finding,
        contexts: list[tuple[FileDiff, FileContext]],
    ) -> Evidence:
        """Validate a finding produced from a multi-file prompt."""
        for file_diff, context in contexts:
            if finding.file == file_diff.filename:
                return self.validate(finding, file_diff, context)
        return Evidence(
            file=finding.file,
            line_start=finding.line_start,
            line_end=finding.line_end,
            code_snippet=finding.code_snippet,
            source="cross_file",
            validation_status="invalid",
            validation_messages=["Finding file is not present in the cross-file review context."],
        )

    def annotate(self, finding: Finding, evidence: Evidence) -> Finding:
        finding_id = finding.finding_id or self._build_finding_id(finding)
        return finding.model_copy(
            update={
                "finding_id": finding_id,
                "evidence": [*finding.evidence, evidence],
                "evidence_status": evidence.validation_status,
                "evidence_issues": evidence.validation_messages,
            }
        )

    def _build_finding_id(self, finding: Finding) -> str:
        raw = "|".join([finding.file, str(finding.line_start), finding.title, finding.problem])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _snippet_matches(self, snippet: str, content: str) -> bool:
        if snippet in content:
            return True
        normalize = lambda value: re.sub(r"\s+", " ", value).strip()
        normalized_snippet = normalize(snippet)
        return bool(normalized_snippet) and normalized_snippet in normalize(content)

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
            if not in_hunk or raw_line.startswith("+++"):
                continue
            if raw_line.startswith("+"):
                changed.add(current)
                current += 1
            elif raw_line.startswith("-") or raw_line.startswith("\\"):
                continue
            else:
                current += 1
        return changed
