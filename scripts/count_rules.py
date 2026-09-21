"""统计确定性规则的实际数量，供 UI 显示与文档核对。"""

import io
import re

FILES = [
    ("src/ai_pr_review/services/analyzers/static_analyzer.py", "static"),
    ("src/ai_pr_review/services/analyzers/python_ast_analyzer.py", "ast"),
]

total = 0
for path, label in FILES:
    source = io.open(path, encoding="utf-8").read()
    # 规则名出现在 _finding(...) / _add(...) 的最后一个位置参数 "rule"
    rules = set(re.findall(r'"([a-z][a-z0-9_]{3,})",\s*\n?\s*\)', source))
    rules = {r for r in rules if r not in {"static_rule", "ai_analysis"}}
    print(f"{label:8} {len(rules):>3} 条: {', '.join(sorted(rules))}")
    total += len(rules)

print(f"\n合计 {total} 条")

from ai_pr_review.config import MODEL_PROVIDER_PRESETS  # noqa: E402

print(f"供应商预设: {len(MODEL_PROVIDER_PRESETS)} 个")
