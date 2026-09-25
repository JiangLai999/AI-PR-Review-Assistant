"""统计确定性规则的实际数量，供 UI 显示与文档核对。

P6 起规则由 `analyzers.rule_catalog` 统一登记，所以这里读目录而不是扫描调用形态：
旧实现按位置参数正则匹配，目录重构后固定打印 0 条（静默失准）。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ai_pr_review.services.analyzers.rule_catalog import RULE_CATALOG, all_rule_ids  # noqa: E402

ids = sorted(all_rule_ids())
print(f"目录键 {len(RULE_CATALOG)} 个 / 去重规则 {len(ids)} 条")
for rule_id in ids:
    definition = next(item for item in RULE_CATALOG.values() if item.rule_id == rule_id)
    print(f"  {rule_id:<32} {definition.severity:<8} {definition.title_zh}")

print(f"\n合计 {len(ids)} 条")

from ai_pr_review.config import MODEL_PROVIDER_PRESETS  # noqa: E402

print(f"供应商预设: {len(MODEL_PROVIDER_PRESETS)} 个")
