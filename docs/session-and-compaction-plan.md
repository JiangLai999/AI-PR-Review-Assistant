# 方案：多会话切换 + 上下文压缩改造（对标 mimocode）

> 背景：用户实测后要求对标 MiMo Code 的**会话切换**与**上下文压缩**。
> 两份源码级调研已完成（`_reference_audit/MiMo-Code-clean`）：
> - 切换：`ctrl+x`→`l`（会话列表）、`ctrl+x`→`n`（新建）、命令面板 Previous/Next session、
>   CLI `-c/-s <id>/--fork`、SDK `unstable_resumeSession`；
> - 压缩：三层机制 —— 自动触发（`session/overflow.ts`，90% 阈值 + 摘要预留核算）、
>   压缩本体（`session/compaction.ts`，40k token 尾部 + 按 API 轮 + 文件清单 + 工具结果收缩）、
>   裁剪（prune：20k 阈值 / 保护最近 40k）。
>
> 本文只出方案，未动代码。分期待评审后派单。

---

## A. 多会话切换

### A0. 现状

| 项 | 现状 |
|---|---|
| 存储 | **单文件** `chat_session.json`（一次只有一个会话） |
| 新建 | `/new` = **清空当前**（不是新建并存） |
| 恢复 | A2：后端重启恢复**那一个**会话 |
| 列表/切换/命名/删除 | **全无** |

### A1. 目标（对齐 mimocode 的能力面，保留我们的交互风格）

1. 多会话并存，各自独立消息与 review 绑定；
2. **列表 + 选择即切换**；
3. 新建不丢旧的；可重命名、可删除；
4. 旧数据自动迁移，零手工操作。

### A2. 存储设计

```
<config 同目录>/
├── sessions/
│   ├── index.json               # 索引：id / title / created_at / updated_at / message_count
│   ├── <session-id>.json        # 每个会话的完整消息（沿用现有消息结构）
│   └── ...
└── chat_session.json            # 旧文件：首次启动时迁移为 legacy 会话，之后只读保留
```

- 写入沿用现有原子写模式（tempfile + `os.replace` + fsync，`chat_session.py` 已有先例）；
- **索引与文件的一致性**：先写会话文件、后更新索引；索引更新失败时下轮启动按目录扫描修复（自愈）；
- **会话 id**：单调 ASCII（与 bus 的 `[A-Za-z0-9_-]` 约束同风格），不暴露 UUID 给用户；
  显示用**标题**（首条用户消息截断 40 字；重命名可覆盖）。

### A3. 后端协议（`jsonl_server.py`）

| 方法 | 语义 | 返回 |
|---|---|---|
| `session.list` | 会话列表（含当前标记） | `[{id,title,updated_at,message_count,current}]` |
| `session.switch` | 载入目标会话并设为 active | `{session: {...}, messages: [...]}` |
| `session.rename` | 改标题 | `{id,title}` |
| `session.delete` | 删除（**当前会话禁止删**，或删后自动切到最近一个） | `{deleted, next?}` |
| `session.create` | 已有；语义改为"**新建并切换**"（不再复用清空） | 现有结构 + `auto_title` |

要点：
- `session.switch` 前**先落盘当前会话**（与 `/new` 同款持久化路径）；
- `current_run_id`（review 绑定）**随会话走**（按 session 存储，已在 A2 语义内）；
- 所有命令沿用现有 `command.execute` 分发（`/sessions` 等），TUI 侧拦截转协议方法。

### A4. TUI 交互（`app.tsx` + `command-menu.ts`）

| 入口 | 行为 |
|---|---|
| **`/sessions`** | 弹出会话列表：`▸ 标题 · 3 分钟前 · 12 条`；`↑↓` 选、`Enter` 切换、`r` 重命名、`d` 删除、`Esc` 关闭 |
| `Ctrl+X` → `L`（可选，对齐 mimocode 手感） | 同 `/sessions`；单键 `Alt+S` 亦可，二选一由实现定 |
| `/new` | 新建并切换（标题自动生成） |
| 状态栏（可选） | 显示当前会话标题（窄终端隐藏） |

### A5. 分期

| 期 | 内容 | 可独立验收 |
|---|---|---|
| **P1** | 存储层多会话 + 迁移 + `session.list/switch/rename/delete` + 单测 | ✅ 纯后端，命令级可验 |
| **P2** | TUI `/sessions` 弹窗 + manual 帧断言 | ✅ 帧级证据 |
| **P3** | 快捷键 + 状态栏会话名 | 可选 |

### A6. 风险

- **迁移**：旧 `chat_session.json` 若损坏 → 跳过迁移并记 warning（不阻塞启动）；
- **删除当前会话**：先切到最近一个再删（避免"无会话"态扩散到全链路）；
- **并发**：单进程内 TUI 串行调用，无需锁；但 `_persist` 与 `switch` 之间要有"当前会话 id"单一真源。

---

## B. 上下文压缩改造

### B0. 现状

| 项 | 现状 |
|---|---|
| 触发 | 仅手动 `/compact` |
| 保留 | **最近 10 轮（按条数，硬编码）** |
| 摘要 | 纯文本（模型生成），失败保留原历史 |
| 文件清单 | 无 |
| 压缩自身预留 | 无（长会话上压缩请求可能自己超窗）|
| 压力提示 | 超额后才 tips（被动） |

### B1. 目标（借鉴 mimocode 的四个机制，按优先级）

1. **保留口径：token + 对话轮分组**（替代"10 轮条数"）；
2. **摘要带文件清单**（承接仓库上下文：压缩后仍能回答"动过哪些文件"）；
3. **自动触发 + 压力分级**（可选，默认建议"提示"而非"静默自动"）；
4. **压缩调用自身预留空间**（长会话安全）。

### B2. 保留策略（P1）

```
tail_budget = min(compaction_tail_tokens, effective_window × 0.25)
从最新往回，按【对话轮】（user+assistant+工具链）累加估算 token
直到超出 tail_budget；被剩下的部分 → 交给摘要
```

- `compaction_tail_tokens` 默认 **40_000**（对齐 mimocode），可配；
- **按轮分组**：一轮 = 一条 user + 其后的 assistant（含 reasoning/工具）。保证不把
  "问题"与"回答"拆到两侧；
- token 估算：优先真实 `usage`（我们已有 `finished.usage`），缺失用 `estimate_tokens`；
- 兼容：`/compact` 的"保留最近 10 轮"改为本策略（`CHAT_COMPACT_KEPT_TURNS` 退化为下限兜底：
  至少保 1 轮，避免极端配置下清空对话）。

### B3. 摘要结构（P1+P2）

```
<conversation-summary trigger="manual|auto" replaced_messages="22" kept_turns="3">
被压缩的历史摘要：
…（模型生成的摘要正文）…

## 已压缩对话涉及的文件
- website/index.html（讨论过 3 次）
- website/js/main.js（讨论过 1 次）
</conversation-summary>
```

- XML 结构对齐 mimocode（含触发源与统计，便于模型理解"这是摘要不是原话"）；
- **文件清单数据源**：被压缩消息里的路径（复用 `_mentioned_repo_paths` 的正则）+ 该会话
  绑定 run 的 finding 文件（`_findings_file_paths`）——两者都已有实现，无需新解析器；
- 摘要提示词显式要求"保留对文件/结论的指代关系"。

### B4. 自动触发与压力分级（P3，可选）

```
usable = min(chat_context_budget, model_window) × trigger_ratio   # ratio 默认 0.9
每轮结束后：
  used_percent >= 90  → pressure=high：状态栏变黄 + 提示"可 /compact"
  used_percent >= 100 → pressure=critical：提示 +（可选）自动压缩
```

- **默认只提示，不静默自动**（自动会消耗一次模型调用；我们的 chat 有自己的成本口径，
  且本地模型摘要质量不稳定）；
- 配置项：`preferences.compaction_auto`（默认 false）、`compaction_trigger_ratio`（默认 0.9）、
  `compaction_tail_tokens`（默认 40000）；
- 状态栏复用 A5 的 `上下文 12% · 2.4k/20k`，加颜色/图标区分压力级。

### B5. 压缩自身的安全网（P3 配套）

- 摘要请求发送前，把待摘要内容**截断到 `usable × 0.6`**（不超过模型可用窗口），
  超出部分分段摘要（简单实现：只摘要最近 N token 的待压缩段，更早的直接丢弃并在摘要里标注
  "更早的 M 条已省略"）；
- 摘要失败：**保留原历史**（现有语义不变），并返回可读错误。

### B6. 分期

| 期 | 内容 | 验收 |
|---|---|---|
| **P1** | token + 对话轮保留策略；XML 摘要结构；配置项 `compaction_tail_tokens` | 单测：长消息 1 轮不整段丢；短消息多轮全保留；边界（预算小于一轮）|
| **P2** | 摘要文件清单（消息路径 + finding 文件） | 单测 + 可读性抽查 |
| **P3** | 自动触发（默认提示）+ 压力分级 + 压缩预留/分段 | 单测 + manual 帧（压力配色）|

### B7. 风险

- **token 估算误差**（我们本地 usage 为 0）：保留策略以估算为准，误差会让"实际保留量"偏移，
  但比"按条数"更接近真实；估算函数已有确定性（`estimate_tokens`）；
- **摘要质量**：本地小模型摘要可能丢关键信息——默认不自动压缩可缓解；文档里建议"大模型会话用手动、
  本地会话用 prune 式截断"（prune 是否引入见下）；
- **是否引入 prune（工具结果收缩）**：我们的 chat 没有"工具调用结果"这种大块内容
  （review 上下文是**每轮现算**、不落盘），因此 **prune 不适用，明确不做**。

---

## C. 实施顺序建议（若两份都批准）

```
A-P1（多会话存储，后端）──→ A-P2（TUI 列表）
        ↘ 两者可并行（不同文件）
B-P1（压缩保留策略，后端）──→ B-P2（文件清单）──→ B-P3（自动触发，前后端）
```

- **并行切分**：A-P1 与 B-P1 都在 `jsonl_server.py`，**必须串行或合并为一个后端任务**；
  A-P2（TUI）可与任一后端期并行；
- 总工期估计：A-P1+P2 ≈ 1 个大任务；B-P1+P2 ≈ 1 个中任务；B-P3 ≈ 1 个中任务。

## D. 待拍板

1. A 的快捷键：`Ctrl+X→L`（mimocode 手感）还是 `Alt+S`（我们现有键位体系）？
2. B 的自动压缩：默认**只提示**（本方案建议）还是**静默自动**？
3. A-P3（状态栏会话名）与 B-P3（压力配色）是否合并到同期做？
4. 两份方案的**实施顺序**：先 A 后 B、先 B 后 A、还是 A-P1 与 B-P1 合并成一个后端大任务？
