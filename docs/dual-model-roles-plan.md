# 双模型角色分离方案（CHAT / REVIEW）

状态：**待评审**（尚未开发）
日期：2026-09-25
相关实测：`docs/claude-p6-dual-model-strategies.md`

---

## 1. 为什么做这个改造

### 1.1 现状：一个三选一，决定两件事

配置助手的第 1 步"运行模式"提供 `cloud / local / hybrid / offline`，落盘时
写成一个字段 `preferences.hybrid_strategy`（`jsonl_server.py::_apply_setup`）。
这一个字段**同时**决定：

| 谁 | 现在读什么 | 代码位置 |
|---|---|---|
| 聊天（`/chat` 的每次回复） | 活跃槽 = `_active_provider_config()` | `jsonl_server.py::_chat` → `config.ai_client.model_provider` |
| 审查（`/review` 的逐文件调用） | `hybrid_strategy` → `ModelSelector` | `services/model_selector.py::_get_strategy` |

### 1.2 由此产生的三个真实问题

1. **聊天与审查的需求本质不同**：聊天要快、要多语言、要省 token；审查要
   长上下文、要严格 JSON、要证据校验。强行共用一个槽是妥协。
2. **`hybrid` 的自动路由不可预期**：实测（PR #29，2 个文件）`balanced`
   两次运行都**全部走本地**——`_should_use_remote` 的触发条件（高危路径 /
   静态高危 finding / 变更量 > 300 行）在中小 PR 上不会命中。比赛演示时
   无法承诺"这一轮到底走哪条路"。
3. **用户没有表达真实需求的机会**："聊天用云、审查用本地省钱"这种最常见
   的组合，现在根本无法配置。

### 1.3 目标

用**两个显式选择**替代一个打包决定；把自动路由从"默认行为"降级为
"审查侧的高级选项"。

---

## 2. 目标模型

两个角色，各自独立选择：

```
CHAT   槽  → 只用于对话（chat 会话）
REVIEW 槽  → 只用于 /review 的模型审查
```

| 角色 | 可选值 | 说明 |
|---|---|---|
| CHAT | `remote` / `local` | 二选一，模型名取该槽的 `default_model` |
| REVIEW | `remote` / `local` / `hybrid` | 第三项是**高级选项**（保留现有自动路由） |

### 2.1 组合矩阵（每个组合都有明确用途）

| # | CHAT | REVIEW | 场景 | 成本 | 说明 |
|---|---|---|---|---|---|
| 1 | remote | remote | 质量优先 | 高 | 比赛默认推荐；全云 |
| 2 | remote | local | **省钱** | 低 | 聊天用云（便宜、快），审查走本地 |
| 3 | local | remote | 隐私 + 质量 | 中 | 敏感对话不出本机，审查仍用云 |
| 4 | local | local | **全离线** | 0 | 断网演示 / 数据不出本机 |
| 5 | 任一 | hybrid | 高级 | 混合 | 本地打底 + 高复杂度回退云端 |

> 组合 2 与 3 是本次改造的主要收益：它们在当前架构下**无法配置**。

---

## 3. 数据模型

### 3.1 新增字段（`config.py::Preferences`）

```python
chat_slot: str = ""     # "remote" | "local" | ""（空 = 跟随运行模式预设）
review_slot: str = ""   # "remote" | "local" | "hybrid" | ""（空 = 跟随预设）
hybrid_strategy: str = "balanced"   # 保留：派生视图 + 向后兼容
```

字段语义（**关键**）：这两个字段是**可选覆盖**，不是必填项。

| 值 | 含义 |
|---|---|
| `""`（默认） | 跟随用户在配置助手第 1 步选的运行模式预设 |
| `"remote"` / `"local"` | 显式覆盖为远端槽 / 本地槽 |
| `"hybrid"`（仅 review_slot） | 显式启用按复杂度自动分流 |

### 3.2 单一事实来源

当显式覆盖存在时，**两个 slot 是事实来源**；`hybrid_strategy` 同时承担两个角色：

1. 运行模式预设的持久化载体（用户没细化路由时，它就是唯一事实来源）；
2. 审查侧的**派生视图**（用户细化过路由时，由 `review_slot` 折算写入）。

折算规则：

| review_slot | 派生的 `hybrid_strategy` |
|---|---|
| `remote` | `remote_only` |
| `local` | `local_only` |
| `hybrid` | `balanced` |

### 3.3 读取规则（兼容旧配置）

```python
def resolve_chat_slot(cfg) -> str:
    explicit = (cfg.preferences.chat_slot or "").strip().lower()
    if explicit in {"remote", "local"}:
        return explicit
    # 旧配置没有 chat_slot：按 hybrid_strategy 推导
    return "local" if cfg.preferences.hybrid_strategy == "local_only" else "remote"

def resolve_review_slot(cfg) -> str:
    explicit = (cfg.preferences.review_slot or "").strip().lower()
    if explicit in {"remote", "local", "hybrid"}:
        return explicit
    return {
        "local_only": "local",
        "remote_only": "remote",
        "balanced": "hybrid",
    }.get(cfg.preferences.hybrid_strategy, "remote")
```

### 3.4 旧配置迁移（等价映射）

| 旧 `hybrid_strategy` | 新 `chat_slot` | 新 `review_slot` | 行为是否改变 |
|---|---|---|---|
| `remote_only` | `remote` | `remote` | 不变 |
| `local_only` | `local` | `local` | 不变 |
| `balanced` | `remote` | `hybrid` | 不变（聊天仍走远程入口） |

迁移在读取时惰性完成（`resolve_*`），不强制改写磁盘。

---

## 4. 配置界面设计（TUI 配置助手 · 像素风）

采用**两级设计：预设优先、细化为可选**。多数用户只选预设，不理解"槽"也能用；
有明确分工需求的用户再进入细化页。

### 4.1 第 1 步：运行模式预设（保留 + 扩展）

```
╔══════════════════════════════════════════════════════════════╗
║  CONFIGURATION // 运行模式                                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   ┌────────────────────────────────────────────────────┐     ║
║   │  ▸ 云端    对话与审查都使用云端模型（质量优先）      │     ║
║   │    本地    对话与审查都使用本地模型（离线可用）      │     ║
║   │    混合    对话用云端；审查按复杂度自动分流          │     ║
║   │    自定义  分别指定「对话模型」和「审查模型」 ← 新增  │     ║
║   └────────────────────────────────────────────────────┘     ║
║                                                              ║
║   ↑↓ 选择 · Enter 下一步 · Esc 退出                            ║
╚══════════════════════════════════════════════════════════════╝
```

| 预设 | 落盘结果 |
|---|---|
| 云端 | `hybrid_strategy=remote_only`，`chat_slot=""`，`review_slot=""` |
| 本地 | `hybrid_strategy=local_only`，两个 slot 留空 |
| 混合 | `hybrid_strategy=balanced`，两个 slot 留空 |
| **自定义** | 进入 §4.2 细化页，写入 `chat_slot` / `review_slot`（并折算 `hybrid_strategy`） |

> `offline` 旧值保持兼容：读取时等价于"本地"。

### 4.2 路由细化页（仅"自定义"出现）

```
╔══════════════════════════════════════════════════════════════╗
║  CONFIGURATION // 路由细化（高级）                             ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   对话模型 · 聊天区使用                                        ║
║   ┌────────────────────────────────────────────────────┐     ║
║   │  ▸ 云端   deepseek-flash                           │     ║
║   │    本地   qwen3.5:4b                                │     ║
║   └────────────────────────────────────────────────────┘     ║
║                                                              ║
║   审查模型 · /review 使用                                     ║
║   ┌────────────────────────────────────────────────────┐     ║
║   │    云端   deepseek-flash                           │     ║
║   │  ▸ 本地   qwen3.5:4b                                │     ║
║   │    混合   按文件复杂度自动分流（高级）                │     ║
║   └────────────────────────────────────────────────────┘     ║
║                                                              ║
║   ↑↓ 选择 · Tab/←→ 切换方框 · Enter 下一步 · Esc 返回          ║
╚══════════════════════════════════════════════════════════════╝
```

设计约束（沿用你此前提出的界面要求）：

- 两个方框各自用 ↑↓ 选择，**选中项高亮**（像素主题 accent 色 + `▸` 标记）；
- `Tab` / `←→` 在两个方框间移动焦点，**不需要在框外回车**；
- 显示的是**槽别名 + 实际模型名**（`本地 qwen3.5:4b`），不是抽象的 remote/local；
- 模型名来自 `config.options`（`_setup_options`），不硬编码在前端；
- 中英双语文案同时提供（`ui_language` 决定）。

### 4.3 后续阶段的影响

| 阶段 | 现状 | 改后 |
|---|---|---|
| 2 模型服务 | 选供应商 / base_url | 按**用到的槽**出现：云端槽被使用才问供应商与 base_url；本地槽被使用才问 Ollama 端点 |
| 3 凭据与模型 | 单个 API Key + 单个模型 | 云端槽被使用时才要求 API Key；每个被使用的槽各选一个模型 |
| 6 确认页 | 显示运行模式 | 显示 `运行模式` + `对话 deepseek-flash` + `审查 qwen3.5:4b` 三行摘要 |

### 4.4 状态栏

```
● 就绪  CHAT deepseek-flash · REVIEW qwen3.5:4b    0 条消息
```

选择"混合"审查时显示 `REVIEW hybrid (local↔remote)`，便于用户知道当前是自动分流。

---

## 5. 运行时改动点

### 5.1 后端

| # | 位置 | 改动 |
|---|---|---|
| 1 | `config.py::Preferences` | 新增 `chat_slot` / `review_slot` |
| 2 | `config.py`（模块级函数） | 新增 `resolve_chat_slot()` / `resolve_review_slot()`（§3.3 规则） |
| 3 | `config.py::AppConfig._sync_runtime_sections` | 只负责把**聊天**槽的 provider/model/api_key 同步进 `ai_client`（保持现有行为）；不再隐含表达审查路由 |
| 4 | `backend/jsonl_server.py::_chat` | 显式读 `resolve_chat_slot()`；本地槽时沿用现有 `reasoning_effort="none"` 处理 |
| 5 | `backend/jsonl_server.py::_apply_setup` | `runtime_profile` 增加 `custom`；接受 `chat_slot` / `review_slot`，写槽位 + 折算 `hybrid_strategy` |
| 6 | `backend/jsonl_server.py::_setup_options` | 返回值增加 `slots: {chat: [...], review: [...]}`（含各槽 `label` 与 `default_model`）；预设列表增加 `custom` |
| 7 | `services/model_selector.py::_get_strategy` | 改为读 `resolve_review_slot()`（`remote→REMOTE_ONLY`、`local→LOCAL_ONLY`、`hybrid→BALANCED`） |
| 8 | `ui/pixel_theme.py::runtime_mode_label` / 状态渲染 | 状态栏显示两个模型名（及 `hybrid` 标记） |
| 9 | `cli.py`（`config` / `doctor` 输出） | 展示 `CHAT/REVIEW` 两行，不再只显示"运行策略" |
| 10 | `backend/jsonl_server.py::_model_status`（`model.status`） | 返回值带 `chat` / `review` 两个字段（模型名 + 槽位 + 是否 hybrid） |

### 5.2 TUI（`frontend/tui/src/app.tsx`）

| # | 位置 | 改动 |
|---|---|---|
| 11 | `SetupScreen` / `screenStages` | `runtime` 预设项增加 `custom`；新增 `route_chat` / `route_review` 两个 screen（stage 1） |
| 12 | `SetupWizardDialog` | 预设分支（选 custom 才进入细化页）+ 两个选择器的键盘模型（↑↓ 选择、Tab 切换、Enter 提交、Esc 返回） |
| 13 | 提交载荷 | `config.setup` 增加 `runtime_profile: "custom"` 与 `chat_slot` / `review_slot` 字段；其它预设不发送这两个字段（保持旧载荷兼容） |
| 14 | 状态栏组件 | `CHAT x · REVIEW y`（hybrid 时额外标记） |
| 15 | i18n 文案表 | 中英各一组新文案（预设第 4 项、细化页标题、两个方框标签、混合说明） |

### 5.3 命令（可选，建议同期做）

| 命令 | 现状 | 改后 |
|---|---|---|
| `/model` | 查看当前模型 | 查看 `CHAT/REVIEW` 两行 |
| `/model <name>` | 切换当前模型 | 兼容：切换 **CHAT** 模型 |
| `/model chat <name>` | — | 新增：切聊天模型 |
| `/model review <name>` | — | 新增：切审查模型（含 `hybrid`） |

### 5.4 配置快照契约（前端只读这些字段）

`config.snapshot` / `config.setup` / `model.status` 的返回体统一新增：

```json
{
  "routing": {
    "profile": "custom",
    "chat":   { "slot": "remote", "label": "云端", "model": "deepseek-flash" },
    "review": { "slot": "local",  "label": "本地", "model": "qwen3.5:4b" }
  }
}
```

- `slot` 取值：`remote` / `local` / `hybrid`（仅 review 可能为 hybrid）；
- `profile` 是**预设名**（`cloud` / `local` / `hybrid` / `offline` / `custom`），
  供确认页与状态栏显示"用户选的是哪一档"；
- 前端**不得**自行由 `hybrid_strategy` 推导槽位（推导只在后端 `resolve_*` 发生）。

---

## 6. 分期计划与验收

### P1 · 后端数据模型（不动 UI）

- 新增两个字段 + `resolve_*` + 派生写回；`_chat` 与 `ModelSelector` 改为读解析器。
- 单测：三种旧策略的等价映射；显式 slot 优先于派生值；`remote/local/hybrid` 全组合路由正确。
- 验收：全量 pytest 绿；**旧配置不改磁盘**也能跑出与改造前一致的行为。

### P2 · 协议层

- `config.options` / `config.setup` 支持双 slot；同步 `cli.py` 的 `config` 输出。
- 测试：`test_jsonl_backend.py` 增补 `config.setup` 双 slot 用例（含只传一个 slot 的部分更新）。

### P3 · TUI 配置界面

- 第 1 阶段双选择器 + 状态栏 + i18n；`bun run typecheck` + `bun test src`；真机截图（120×30 / 209×51）。
- 键盘：↑↓ / Tab / ←→ / Enter / Esc 全路径手测。

### P4 · 验收与文档

- 4 个组合各跑一次真实审查（复用 `_p5_verify/p6proto/verify_dual_model_strategies.py`，
  扩展为按 `chat_slot/review_slot` 组合驱动），核对：走哪个模型、计费、`routing_model` 元数据。
- 更新 `docs/`（本方案 → 实现记录）+ README / 比赛演示脚本口径。

---

## 7. 决策点（需要你拍板）

1. **REVIEW 侧是否保留"混合（高级）"？**
   建议：**保留**。代码与测试已存在，且"智能分流"是比赛卖点；只要默认不选，
   就不会再把不可预期性带入常规演示。
2. **默认组合是什么？**
   建议：**`CHAT=remote · REVIEW=remote`**（比赛现场最稳），本地组合作为演示项。
3. **自动路由的阈值是否同时调？**
   建议：**本轮不动**。slot 显式化之后，"混合"变成用户主动选择的选项，
   阈值调优可以单独作为一个后续任务（有独立的验收标准）。
4. **`/model` 命令的兼容策略**
   建议：`/model <name>` 保持兼容并作用于 CHAT；新增 `chat` / `review` 子命令。

---

## 8. 工作量与风险

| 阶段 | 规模 | 主要风险 |
|---|---|---|
| P1 | ~1 轮 | 40+ 处 `hybrid_strategy` 引用的语义清理；`_sync_runtime_sections` 的副作用边界 |
| P2 | ~1 轮 | 协议兼容（老 TUI 前端 / 老 JSONL 调用方） |
| P3 | ~1–2 轮 | TUI 焦点与键盘模型是主要工作量 |
| P4 | ~1 轮 | 需要真实凭据（运行时环境变量注入，不落盘） |

**总计 4–5 轮**。P1、P2 完成前，界面保持"运行模式"不变，功能等价，
因此可以随时中断而不破坏现有比赛版本。

---

## 9. CHAT 的审查上下文（Review-Aware Chat）

> 这一节回答"CHAT 槽存在的意义"：聊天必须能解读**本项目的审查结果**，
> 而不是一个通用聊天工具。

### 9.1 现状审计（2026-09-25）

| 能力 | 状态 | 位置 / 证据 |
|---|---|---|
| 确定性 finding 解释 | ✅ 有 | `jsonl_server._explain_run`：**模板渲染、不调模型、不可追问** |
| Finding 反馈记录 | ✅ 有 | `_record_feedback`（§10.3） |
| 历史趋势分析（调模型） | ⚠️ 仅 CLI，且只看统计 | `cli._handle_analyze_history_action`：只喂条数/成本/模型，不喂 finding 内容 |
| CLI 自然语言动作路由 | ✅ 有 | `services/agent/router.py`（把"解释问题"路由成动作，不注入内容） |
| **TUI chat 携带 review 上下文** | ❌ 没有 | `_chat()` 的 system prompt 只有一句语言指令 |
| **会话绑定当前 run** | ❌ 没有 | `jsonl_server.Session` 只有 `session_id / messages / published_run_ids` |
| **追问 / 多轮深度解读** | ❌ 没有 | — |
| **跨 run 对比对话** | ❌ 没有 | — |

**决定性证据**：`jsonl_server.py` 中 `session.messages` 仅 3 处引用
（L882 快照 / L898 拼 history / L922 写回），**审查完成后不向对话流写入任何
内容** —— 因此 chat 模型对"刚审完的 PR"一无所知。

**直接后果**（现在一个都答不了）：

1. "刚才那条 75% 置信度的问题，为什么判成中风险？"
2. "这两条 finding 是不是同一个问题？"
3. "帮我写一段给同事的修复说明，包含文件:行。"

用户只能手动复制粘贴 findings——这正是"单调聊天工具"的观感来源。

### 9.2 方案：会话绑定 + 上下文注入

#### A. 会话绑定（TUI）

```python
@dataclass
class Session:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    published_run_ids: set[str] = field(default_factory=set)
    current_run_id: str | None = None      # 新增
```

| 触发 | 行为 |
|---|---|
| `/review` 完成 | 自动绑定该 run |
| `/history <run_id>` | 绑定 + 载入工作台 |
| `/explain <run_id>` | 绑定 |
| `/context` | 显示当前绑定与 token 估算 |
| `/context <run_id>` | 切换绑定 |
| `/context off` | 解绑（回到普通聊天） |

#### B. 上下文构建器（新模块）

```
services/review_context.py
    build_review_context(store, run_id, *, token_budget) -> ReviewContext
```

分层，按预算从下往上裁剪：

| 层 | 内容 | 默认 |
|---|---|---|
| L1 | 运行摘要：PR url/标题/作者、summary、统计、模型、成本、证据校验计数 | 总是保留 |
| L2 | findings 清单：severity / 文件:行 / 置信度 / 证据状态 / 标题 | 总是保留 |
| L3 | 重点 finding 全文：problem / suggestion / 代码片段 / 证据疑点 | 按严重度取前 N |
| L4 | 被过滤 finding 的计数与门槛（`filtered_findings`） | 预算内 |

#### C. 注入方式：system prompt（不进对话历史）

```
你正在协助分析一次 PR 审查结果。以下是本次会话绑定的审查上下文：
<review_context run_id="..." pr="...">
  ...L1..L4...
</review_context>
规则：引用 finding 时必须给出「文件:行」与严重度；只依据上下文回答；
上下文没有的内容（如未展示的完整代码）必须明确说明"需要查看源码"，
不得臆测。
```

- **不落盘、不写入 `session.messages`**（避免历史膨胀与重复计费）；
- 兼容所有 provider，包括本地 Ollama（不依赖 function calling）；
- 后续可选演进：`get_finding(id)` / `search_history` 工具调用。

#### D. 预算与成本

- 新增 `preferences.chat_context_budget`（默认 8000 tokens）；
- 状态栏显示 `CTX ~3.2k tokens`；
- 裁剪顺序：L4 → L3（只留 top-N）→ L2（只留 high/critical）；
  **L1 永不裁剪**（否则模型会失去"在说哪次审查"）。

#### E. 命令与界面

| 项 | 行为 |
|---|---|
| 状态栏 | `CHAT deepseek-flash · REVIEW qwen3.5:4b · CTX #29 (2 findings)` |
| 审查完成 | chat 区追加一行提示："已绑定本次审查，可直接提问（例：解释第 2 条）" |
| `/explain` | 保留：确定性、零成本、离线可用（与 AI 解读互补） |

#### F. 与双槽方案（§2）的配合

| 组合 | 效果 |
|---|---|
| CHAT=local + REVIEW=local | **全程离线解读**：证据与代码不出本机（比赛强卖点） |
| CHAT=remote + REVIEW=local | 本地审查省钱 + 云端深度解读 |
| CHAT=remote + REVIEW=remote | 质量优先的完整闭环 |

### 9.3 分期与验收

| 阶段 | 内容 |
|---|---|
| P5 | `Session.current_run_id` + 绑定触发 + `/context` + `build_review_context()` + `_chat()` 注入 + 预算裁剪 |
| P6 | TUI 状态栏 / 完成提示 / i18n（中英） |
| P7 | 真实 run 验收 + 文档 |

**验收标准（可逐条核对）**

1. 绑定后问"第 2 条 finding 的文件与行号" → 与 run 记录**逐字一致**；
2. 问"这条的证据校验状态" → 与 `evidence_status` 一致（含 `needs_review` 等）；
3. `/context off` 后问同样问题 → 明确回答"当前没有绑定审查上下文"，
   不编造 findings；
4. 超预算的 run → 状态栏提示裁剪，且 L1/L2 完整保留；
5. 离线（本地 chat 槽，断开网络）→ 仍能完成上述 1–2 问答。

### 9.4 工作量更新

| 阶段 | 规模 |
|---|---|
| P1–P4（双槽） | ~4–5 轮 |
| P5–P7（审查上下文） | ~2–3 轮 |
| **合计** | **~6–8 轮** |

两项可以**独立推进**：即使 §2 的双槽方案推迟，§9 的上下文注入也能先落地
（它只依赖当前 chat 槽，不依赖 slot 拆分）。

### 9.5 与仓库感知方案的关系

`docs/repo-aware-review-plan.md`（仓库代码上下文，L1 共 2–3 轮）与本文档
**互相独立**：前者补充"审查看得见仓库"，后者补充"配置可控 + 聊天能解读"。
三条线合起来构成完整叙事：

```
配置可控（§2/§4） → 审查更准（repo-aware L1） → 聊天能解读（§9）
```

**总盘子**：双槽 4–5 轮 + 审查上下文 2–3 轮 + 仓库感知 L1 2–3 轮 ≈ **9–11 轮**，
可按此顺序分批推进，每批结束都可交付。
