# P6 · 双模型三策略实跑结论

日期：2026-09-25 · 验收脚本：`_p5_verify/p6proto/verify_dual_model_strategies.py`
（`_p5_verify/` 不进仓库；脚本可随时重跑）

目标 PR：https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/29
双槽：`remote = deepseek/deepseek-flash`、`local = ollama/qwen3.5:4b`（本机 GPU）

## 1. 结论：三种策略都能真实跑通

| 策略（TUI 名称） | 实跑项目 | run | findings | 计费 | 耗时 | local/remote 调用 | 路由模型 |
|---|---|---|---|---|---|---|---|
| `remote_only`（Cloud） | deepseek-flash | `02abb912` | 0 | **≈$0.0223** | 7.2s | 0 / 2 | `deepseek-flash` |
| `local_only`（Local） | qwen3.5:4b | `fabb942b` | 0 | **$0.0** | 74.1s | 2 / 0 | `qwen3.5:4b` |
| `balanced`（Hybrid） | 远程槽为入口、逐文件选模 | `9816c025` | 0 | **$0.0** | 70.5s | 2 / 0 | `qwen3.5:4b` |

三条 run 都产出了合规 `ReviewResult` 并落库（证据计数、`filtered_findings`、
`strategy`、`local_calls/remote_calls` 一并写入 metadata）。

> 为什么选 PR #29：它的 diff 只有 2 个文件、远小于上下文窗口，适合把变量
> 收敛到「路由与计费」本身，而不是模型的能力上限。

## 2. 实跑暴露并修复的三个缺陷

### 2.1 本地调用被按云端价格计费

每个文件的客户端复用了 `ai_client` 的价格表（3.0/15.0 每 million），因此
`local_only`（remote=0）也曾报出 ≈$0.0311 —— 与远程运行一模一样。

修法：`HybridReviewOrchestrator._client_config_for(..., is_local=True)` 显式把
`input/output_cost_per_million` 覆写为 0；远程路径保持用户价格表不变。
回归测试：`test_hybrid_local_calls_are_not_billed_at_cloud_rates`。

### 2.2 `routing_model` 记录不实

落库时恒写 `model_selector.local_model`，于是 `remote_only` 的运行在
`/history` 与 CLI 报告里读起来像是由 Ollama 完成的。

修法：按 `stats["local_calls"]/remote_calls` 决定实际路由描述（两者皆有时写
`local + remote`）；`getattr(..., 默认值)` 兼容只实现
`select_model_for_task` 的测试桩。

### 2.3 全部文件失败会被读成「审查完成，发现 0 个问题」

本编排器按原语义吞掉单文件异常继续跑；只看 findings 数量时，一把失效的
API Key 会伪装成一次干净的 0 findings 审查（实跑中真实出现过：远程
`api_key` 缺失时三个策略都“通过”且成本为 0）。

修法（本次）：

- 逐文件失败进 `failed_files`（文件名 + 错误），并统计
  `failed_file_count` 落 metadata；
- summary 分档：全部失败 → `审查失败：N 个文件均未能完成模型审查（首个错误：…）`；
  部分失败 → `审查完成（部分失败）：X 个文件已审查，Y 个文件未能审查，发现 N 个问题`；
- 修掉 `reviewed_count` 把失败文件也算进“已审查”的旧语义（曾同时报
  “4 个已审查 / 4 个未能审查”）。

回归测试：`test_hybrid_reports_every_file_failure_as_a_failure`、
`test_hybrid_partial_file_failure_is_visible_in_the_summary`。
真实样本：`fabb942b` 的 summary 为「审查完成（部分失败）：1 个文件已审查，
1 个文件未能审查，发现 0 个问题」，metadata 记有
`failed_files: [src/ai_pr_review/cli.py]`。

## 3. 已知边界（不是缺陷，但需要知情）

1. **`balanced` 当前实际全走本地**：两个文件都被
   `evaluate_file_complexity` 判为低复杂度，`_should_use_remote` 未触发远程
   回退。混合策略的“混合”需要更复杂的输入才能观察到；若要改变行为，应
   单独调整复杂度阈值，而不是在验收里顺手改掉。
2. **本地 4B 模型有 JSON 失败率**：本轮 `local_only` 有 1/2 个文件因模型输出
   非 JSON 而失败（`AIClient` 的 STRICT RECOVERY 复述已尝试一次）。现在这类
   失败会显式标注 DEGRADED，不再静默降级为 0 findings。
3. **验收脚本要求远程凭据**：`remote_slot.api_key` 为空时它在开跑前打印
   `remote api key : MISSING` 并声明远程调用会失败，避免再次把“全失败”读成
   “干净通过”。
4. **取消语义**（上一轮已验收）：OpenAI 兼容 provider 的 `chat` 走
   `asyncio.to_thread`，取消只中止 await 侧；工作线程仍会等到 socket 超时
   才退出（默认 Anthropic SDK 不受影响）。

## 4. 复跑方式

```powershell
$env:DEEPSEEK_API_KEY = '<deepseek key>'   # 远程槽凭据（不落盘）
$env:GITHUB_TOKEN     = '<github token>'   # 可选：PR 为 public 时匿名亦可
python _p5_verify\p6proto\verify_dual_model_strategies.py remote_only local_only balanced
```

脚本会临时切换 `preferences.hybrid_strategy`、结束后还原并 `config.save()`；
报告写在 `_p5_verify/reports/dual-model-strategies.md`。
