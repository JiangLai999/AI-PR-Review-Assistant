# L2 符号定位验收报告（真实仓库）

日期：2026-09-26
脚本：`_p5_verify/p6proto/verify_l2_symbol_location.py`
目标：`JiangLai999/AI-PR-Review-Assistant` @ 远端默认分支 HEAD

## 结论

**PASS** —— 2 个真实符号共 10 处命中，**每一处都重新读取该文件核对过行内容**，
全部能在 GitHub 上人工核对。

| 符号 | 命中 | 请求（tree / file） | 耗时 |
|---|---|---:|---:|
| `ReviewOrchestrator` | 5 | 1 / 2 | 1.4 s |
| `ContextBuilder` | 5 | 1 / 2 | 1.3 s |
| **合计** | **10** | **2 / 14** | **2.7 s** |

## 命中明细（✓ = 重新读取后该行确实含符号）

### `ReviewOrchestrator`

```
src/ai_pr_review/services/review_orchestrator.py:38   ✓ class ReviewOrchestrator:
src/ai_pr_review/services/review_orchestrator.py:196  ✓ __all__ = ["ReviewArtifacts", "ReviewOrchestrator"]
tests/test_review_orchestrator.py:1                   ✓ """ReviewOrchestrator tests."""
tests/test_review_orchestrator.py:16                  ✓ from ... import ReviewOrchestrator
tests/test_review_orchestrator.py:173                 ✓ orchestrator = ReviewOrchestrator(config)
```

### `ContextBuilder`

```
src/ai_pr_review/services/context_builder.py:71  ✓ class ContextBuilder:
tests/test_context_builder.py:4                  ✓ from ... import ContextBuilder
tests/test_context_builder.py:51                 ✓ builder = ContextBuilder(ContextBuilderConfig(context_lines=2))
tests/test_context_builder.py:75                 ✓ builder = ContextBuilder(ContextBuilderConfig(enable_tree_sitter=False))
tests/test_context_builder.py:90                 ✓ builder = ContextBuilder(ContextBuilderConfig(enable_tree_sitter=False))
```

## 与验收标准的对照（docs/repo-aware-review-plan.md §5）

| 标准 | 结果 |
|---|---|
| stub 数据源 → 解析出 文件:行 | ✅ 单测覆盖（`tests/test_symbol_locator.py`，38 例） |
| 真实仓库：检索到的引用可在 GitHub 上核对 | ✅ 本报告（逐行重读核对） |
| 限流/失败降级不中断审查 | ✅ 代码路径 + 单测（读树/读文件抛错都降级为空） |

## 性能观察

- **1.3–1.4 s / 符号**，请求数 `tree=1 + file≈2`，**远低于**侦察时的保守估算
  （§4 曾估 4–7 请求 / 3–7 s）；原因是候选排序把定义方文件排在前面，
  命中 `max_results_per_symbol` 后立即停止。
- 两个符号各自重新读了一次 tree（脚本未跨符号复用），生产中每次审查只读一次。

## 备注

- 远端默认分支**落后本地 68 个 py 文件**（见 `docs/mimo-l2-recon.md`），因此
  验收刻意选**远端确实存在**的符号；像 `RepoSymbolLocator` 本身这种本地新增
  符号在远端检索不到，属预期而非缺陷。
- GitHub Code Search 在本机环境整体不可用（恒 0 命中 + 10 req/min 限流），
  所以本模块走 `trees + contents + 本地 grep` 路线，与本报告一致。
