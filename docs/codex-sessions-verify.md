# 多会话 + 压缩 · 端到端验收（scripts/verify_sessions.py）

> 任务：`.agent-bus/tasks/codex-sessions-verify.json`
> **执行说明**：原派 codex（独立验收线），但其两轮运行都陷入长时间代码探索
> （第二轮 44 分钟 / 30.9 万 tokens）且**零落盘**、最后远端 compaction 崩溃——
> 脚本与本文档由主控接手实现（2026-09-27）。契约依据：方案
> `docs/session-and-compaction-plan.md` §契约 v1；实现见 `docs/claude-sessions-compaction.md`。

## 1. 用例与验证点

走**真实 `JsonlBackend`**（临时目录），模型调用替换为进程内 stub（不发网络、不需密钥）。

| # | 用例 | 验证点 |
|---|---|---|
| 1 | **会话生命周期** | create×3（各自 chat 一轮）→ `list` 3 条且 `current` 正确、降序、每条有 `message_count` → `switch` 回第 1 个取回其消息 → `rename` 后 list 反映新标题 → 删非当前（`next` 保持当前）→ **删当前（自动切最近）** → 重新 create（id 不冲突） |
| 2 | **迁移 + 持久化** | 预置旧格式 `chat_session.json`（2 条消息）→ 启动 → list 含 `title="legacy"` 且 `message_count=2` → 重启 → 会话集合与消息完整保持 |
| 3 | **索引自愈** | 删 `index.json` → 重启 → 按目录扫描仍能列出；删会话文件（索引仍引用）→ 重启 → 不崩、该条被剔除 |
| 4 | **压缩边界** | 6 轮长消息（`tail=4000` 下限确保触发）→ `/compact` → `kind=compact`、`kept_turns≥1`、`replaced_messages` 存在；摘要首条含 `<conversation-summary`、`trigger=`、`## 已压缩对话涉及的文件` 且清单含讨论过的 `src/app.py`；**保留段以 user 开头（整轮不拆散）**；二次压缩仍成功且 ≥1 轮 |
| 5 | **压力分级** | `_pressure_level`：10→low / 65→medium / 85→high / 120→critical / **None→null**（"算不出"与"很轻"是两件事）；端到端一轮 chat 后 `assistant.finished.context` 含 `pressure` 七键 |

## 2. 真实运行（主控复跑）

```bash
TEMP/TMP=<repo>/.pytest_codex python scripts/verify_sessions.py
# → 5/5 cases passed

python scripts/verify_sessions.py --json   # 机器可读
```

退出码：`0` 全过；`1` 有失败；后端方法缺失或异常时对应用例以
`NOT IMPLEMENTED:` / 原始异常如实记录（不伪造 PASS）。

## 3. 上手即踩的四个差异（脚本首跑暴露，均已按实现修正）

1. **chat 需要 dummy Key**：`_chat` 在拿到 stub provider 之前校验非本地槽 Key——
   脚本需先补 `provider.api_key`（对照 `tests/test_jsonl_backend.py` 的 `_chat_ready_backend`）；
2. **迁移在 `serve()` 触发**（`jsonl_server.py:4859` 调 `session_store.migrate_legacy()`），
   直连 `JsonlBackend` 的脚本必须补这一步，否则 legacy 用例假失败；
3. **`/compact` 是命令**（`command.execute` name=compact）而非顶层方法；
4. **"装得下就不压缩"**：默认 `tail=40000` 下普通会话不会产生摘要——验收必须把预算
   调到下限或把内容压过预算，否则 XML/文件清单断言是假失败（产品行为正确）。

## 4. 未决项（诚实清单）

- `_pressure_level(float("nan"))` 会落到 `low`（实现只把 `None` 当"算不出"）——
  NaN 属异常输入，脚本按契约只断言 `None→null`；若要防护可另开小任务；
- 本脚本的 stub 模型不产生真实 reasoning/usage，**上下文占比走估算**——
  真实 usage 场景由 `scripts/verify_chat_live.py` / `verify_deepseek_live.py` 覆盖；
- 迁移是**一次性**的：迁移后 CLI（`pr-review chat`，仍用 `chat_session.json`）与 TUI
  （`sessions/`）互不可见——见实现文档 §5，属已记录的已知边界。
