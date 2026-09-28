"""Domain models for agent planning and evidence tracking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "critical"]


class ReviewPlan(BaseModel):
    """Deterministic plan produced before model calls begin."""

    intent: str = "Review the pull request for correctness and security risks."
    risk_level: RiskLevel = "medium"
    risk_categories: list[str] = Field(default_factory=list)
    priority_files: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    requires_cross_file_analysis: bool = False
    estimated_file_reviews: int = 0
    rationale: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """Evidence attached to a finding and validated against the PR diff."""

    file: str
    line_start: int
    line_end: int
    changed_line: bool = False
    code_snippet: str = ""
    source: Literal[
        "diff",
        "context",
        "static_rule",
        "cross_file",
        "ai_analysis",
    ] = "ai_analysis"
    validation_status: Literal["valid", "invalid", "needs_review"] = "needs_review"
    validation_messages: list[str] = Field(default_factory=list)


class CrossFileImpact(BaseModel):
    """A lightweight, explainable signal that files may be related."""

    source_file: str
    related_files: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    requires_review: bool = False


class InterfaceChange(BaseModel):
    """A definition whose signature changed inside the PR.

    These are the changes that most often break callers in other files:
    parameter lists, return types, async-ness and inheritance.
    """

    symbol: str
    kind: Literal["function", "class", "method"]
    file: str
    line: int
    change: Literal[
        "parameters_changed",
        "return_type_changed",
        "became_async",
        "stopped_being_async",
        "base_classes_changed",
        "added",
    ]
    before: str = ""
    after: str = ""

    def describe(self) -> str:
        return (
            f"{self.symbol} ({self.change}): {self.before or '<none>'} -> {self.after or '<none>'}"
        )


class CrossFileReference(BaseModel):
    """A place where a symbol is referenced outside its defining file."""

    symbol: str
    file: str
    line: int
    referencing_file: str

    def describe(self) -> str:
        return (
            f"{self.referencing_file}:{self.line} references {self.symbol} defined in {self.file}"
        )
