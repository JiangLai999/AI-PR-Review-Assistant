"""基准测试：用已知缺陷样例衡量审查策略的实际效果。

设计目标：

1. 每个样例都是一个自带已知缺陷的小型文件，不依赖网络和真实 PR。
2. 把“期望发现”与“实际发现”做可解释的匹配，输出精确率、召回率、
   误报率、行号准确率等指标。
3. 同一套样例可以跑不同策略（静态规则、AST 规则、两者合并），
   便于比较策略优劣。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExpectedFinding:
    """样例中预先埋入的已知缺陷。"""

    rule: str
    line: int
    severity: str
    category: str
    description: str = ""


@dataclass(slots=True)
class BenchmarkCase:
    """一个基准样例。"""

    case_id: str
    filename: str
    language: str
    source: str
    expected: list[ExpectedFinding] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def changed_line_count(self) -> int:
        return len(self.source.splitlines())


@dataclass(slots=True)
class CaseOutcome:
    """单个样例的评测结果。"""

    case_id: str
    strategy: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    line_hits: int = 0
    matched_rules: list[str] = field(default_factory=list)
    missed_rules: list[str] = field(default_factory=list)
    unexpected_titles: list[str] = field(default_factory=list)
    avg_confidence: float = 0.0

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 0.0

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)

    @property
    def false_positive_rate(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.false_positives / predicted if predicted else 0.0

    @property
    def line_accuracy(self) -> float:
        return self.line_hits / self.true_positives if self.true_positives else 0.0

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "strategy": self.strategy,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "line_accuracy": round(self.line_accuracy, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "matched_rules": sorted(self.matched_rules),
            "missed_rules": sorted(self.missed_rules),
            "unexpected_titles": sorted(self.unexpected_titles),
        }


@dataclass(slots=True)
class BenchmarkReport:
    """汇总报告。"""

    strategy: str
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def _total(self, attribute: str) -> int:
        return sum(getattr(outcome, attribute) for outcome in self.outcomes)

    @property
    def true_positives(self) -> int:
        return self._total("true_positives")

    @property
    def false_positives(self) -> int:
        return self._total("false_positives")

    @property
    def false_negatives(self) -> int:
        return self._total("false_negatives")

    @property
    def line_hits(self) -> int:
        return self._total("line_hits")

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 0.0

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)

    @property
    def false_positive_rate(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.false_positives / predicted if predicted else 0.0

    @property
    def line_accuracy(self) -> float:
        return self.line_hits / self.true_positives if self.true_positives else 0.0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "case_count": len(self.outcomes),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "line_accuracy": round(self.line_accuracy, 4),
            "cases": [outcome.to_dict() for outcome in self.outcomes],
        }

    def render_text(self) -> str:
        lines = [
            f"Benchmark strategy: {self.strategy}",
            f"Cases: {len(self.outcomes)}",
            "",
            f"{'case':<28}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>8}",
            "-" * 64,
        ]
        for outcome in self.outcomes:
            lines.append(
                f"{outcome.case_id:<28}{outcome.true_positives:>4}"
                f"{outcome.false_positives:>4}{outcome.false_negatives:>4}"
                f"{outcome.precision:>8.2f}{outcome.recall:>8.2f}{outcome.f1:>8.2f}"
            )
        lines.extend(
            [
                "-" * 64,
                f"{'TOTAL':<28}{self.true_positives:>4}{self.false_positives:>4}"
                f"{self.false_negatives:>4}{self.precision:>8.2f}"
                f"{self.recall:>8.2f}{self.f1:>8.2f}",
                "",
                f"Precision:          {self.precision:.4f}",
                f"Recall:             {self.recall:.4f}",
                f"F1:                 {self.f1:.4f}",
                f"False positive rate:{self.false_positive_rate:>8.4f}",
                f"Line accuracy:      {self.line_accuracy:.4f}",
            ]
        )
        return "\n".join(lines)


__all__ = [
    "BenchmarkCase",
    "BenchmarkReport",
    "CaseOutcome",
    "ExpectedFinding",
]
