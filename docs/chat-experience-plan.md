# Chat 体验升级统一方案（v2）

日期：2026-09-26 · 状态：**待确认** · 协作：claude + mimo + Codex（三方并行）

来源：用户两轮真实会话反馈，全部经代码核实。

---

## 0. 需求清单与分组

| 组 | 主题 | 项数 | 主责 | 涉及层 |
|---|---|---|---|---|
| **A** | 上下文管理 | 7 | **claude** | Python 后端 |
| **B** | 模型配置 | 3 | **Codex** | 配置层 + provider |
| **C** | 渲染与交互 | 6 | **mimo** | TUI |

**为什么这样分**：A 全是后端状态与预算逻辑（claude 刚做过 chat 上下文注入）；C 是纯前端观感（mimo 做过 workbench/表格渲染）；B 需要同时碰 provider 工厂、官方模型元数据与配置助手，风险最高，留给集成方做。

---

## 组 A · 上下文管理（claude）

### A1 · 仓库文件按 finding 行号取窗口 ⭐ 根因修复

- **现状**：`_collect_repo_files` 从**文件头**截断 8000 字符。实测 `index.html` 的 finding 在 237 行，模型只拿到前 ~200 行 → 于是把输出花在"数行号"上。
- **方案**：被 finding 点名的路径 → 取 `finding.line_start ± 80` 行窗口（多条取并集/首窗口），标注「（显示第 157-317 行，文件共 412 行）」；未被点名的仍头部截断但标注「（文件共 N 行，仅显示前 M 行）」。预算与降级规则不变。
- **验收**：finding 在 237 行的 run，注入文本覆盖该行且标注窗口。

### A2 · 会话落盘（重启可续）

- **现状**：`Session` 纯内存（代码注释写着 `In-memory only`）；`chat_session.save/load_chat_session` **写好了但从未被调用**。
- **方案**：会话创建 / 每轮 chat 完成后落盘；backend 启动时恢复；`/new` 清空。只存 `role/content/timestamp`，**不存 review 上下文**（每轮现算）。
- **验收**：存一次 → 新实例恢复相同消息；`/new` 后为空。

### A3 · 历史窗口与预算

- `session.messages[-40:]` → **80 条**；裁剪时**明确告知**（不再静默丢弃）。
- `chat_context_budget`（8000）改为**可配置**。
- **验收**：长对话后早期内容不静默消失；改预算生效。

### A4 · 上下文超额 tips

- **现状**：超预算时静默裁剪（只在注入文本里写"预算受限"）。
- **方案**：发生裁剪时在**事件 + 状态栏**提示：「上下文超出预算，已按 L1→L2→L3 裁剪；`/compact` 可压缩历史，`/context` 查看范围」。
- **验收**：超预算 run 出现该提示；未裁剪时不出现（不制造噪音）。

### A5 · chat 内上下文长度提示（参考 mimo）

- **方案**：状态栏显示 `上下文 12% · 2.4k/20k`（优先用模型返回 usage，缺失则估算并标注）；事件 `context.usage` 实时更新。
- **依赖**：`context_window` 来自组 B 的模型规格（缺失时按 32k 兜底并标注"估算"）。
- **验收**：一轮对话后数值增长；接近上限时变色。

### A6 · `/compact` **压缩上下文**（与 Claude Code / MiMo 同义）

**语义澄清**：`/compact` = **压缩当前上下文**——把较早消息压成一段摘要并**替换原文**，释放上下文窗口；它不是"只输出一份总结"（那是另一种东西，见下）。

- **行为**：保留最近 10 轮**原文**；更早的消息 → 一段「（历史摘要）」；摘要**进入历史**并随 A2 落盘。压缩只调用一次模型。
- **可选指令**（对齐 Claude Code）：`/compact 保留 API 细节` —— 括号外的文字作为压缩指令传给模型，用于强调哪些信息必须保留。
- **反馈**：压缩前后显示占用变化（如 `2.4k → 0.6k tokens`），并说明保留了哪几轮原文。
- **失败**：保留原历史不动并报错（绝不半途丢消息）。
- **验收**：`/compact` 后消息数下降、摘要进历史、占用下降；后续对话仍能引用被压缩的早期事实（抽查）；失败时历史完好。

> 若只想要"看一眼总结、不改上下文"，后续可加 `/summarize`（只读、不替换）；本方案先不做，避免两个命令语义打架。

### A7 · `/history` 对话历史调用

- **现状**：`/history` 目前只服务**审查 run**。
- **方案**：`/history` 无参 → 列出**对话消息**（编号/时间/前 60 字）；`/history <n>` 回显第 n 条；`/history --runs` 保留原审查列表语义（旧行为不变）。
- **验收**：新命令列出消息；旧 `/history <run_id>` 仍可用。

---

## 组 B · 模型配置（Codex）

### B1 · 上下文长度与输出长度进配置助手

- **现状**：`ProviderModelConfig` 有 `context_window`/`max_output`，但界面改不了（只有预设）。
- **方案**：配置助手新增「模型规格」屏（每个被使用的槽一次）：上下文长度、单次最大输出；非法值回退预设 + warning；三出口（`config.setup`/`config.options`/`model.status`）同步。
- **验收**：改后持久化并回显；非法值回退 + warning；`max_tokens` 随之变化。

### B2 · 模型规格与能力同步（**主源已选定**）

- **现状**：规格写死在 `PROVIDER_MODEL_PRESETS`；官方 `/v1/models` 通常**不返回**上下文长度与思考能力。
- **方案**（依据 `docs/model-metadata-sources.md` 的实测评估）：
  - **主源 models.dev**（`api.json`）：提供 `limit.context` / `limit.output` /
    `reasoning_options`（`toggle` / `effort+values` / `budget_tokens+min`）/ 价格；
    223 providers、5452 个 reasoning 模型，DeepSeek 条目与本机实测**逐项吻合**。
  - **交叉源 OpenRouter**（`supported_parameters`）用于 OpenAI 兼容生态的参数名校验。
  - **官方文档**用于关键供应商的语义校验（如 DeepSeek 的 effort 兼容映射表）。
  - 合并策略：只覆盖"来源确认存在"的字段，其余保持预设并标注
    `source: modelsdev|openrouter|official|presets`。
  - **缓存与刷新**（修正：先前写的"1 小时 TTL"没有依据——models.dev 是静态元数据
    文件，只在模型发布/调整时变化，几 MB 一个文件，频繁拉纯属浪费）：
    · 本地**文件缓存**，有效期 **7 天**；
    · **惰性刷新**：缓存过期后，**下次真正需要时**才在后台拉一次（不搞定时轮询）；
    · **手动刷新**：配置助手里一个「刷新模型规格」按钮，随时可用（用户主动时立即拉）；
    · **拉取失败 → 用旧缓存**，界面标注「数据可能过期（最后更新 X）」；
    · 完全离线时用内置预设，不阻塞配置流程。
  - **冲突不自动二选一**：标记 `needs_verification`，UI 提示并给出一键实测入口
    （`_p5_verify/p6proto/probe_*` 脚本可直接复用）。
- **边界**：拿不到就**如实标注 unknown**，绝不套用别家取值；models.dev 不区分端点
  （Ollama 的 `think` 原生有效、兼容端点失效），这类差异仍需抽验。
- **验收**：DeepSeek 条目能自动带出 `context=1,000,000` / `output=393,216` /
  `effort∈{low,high,max}` + `toggle`；来源字段出现在快照里；冲突时标记而非猜测；
  **7 天内不重复下载**（缓存命中）；手动刷新能立即拉取；断网时回退到预设/旧缓存且不报错。

### B3 · 第三方中转站的自定义参数

- **现状**：可用 `custom` provider，但模型规格仍取预设。
- **方案**：中转站场景允许逐项自定义 `base_url` / `api_key` / 模型名 / **上下文长度** / **最大输出**，全部落盘并回显；`custom`/未知供应商**不再套用官方预设规格**。
- **验收**：自定义端点 + 自带规格 → 请求体与状态栏都用自定义值，不与官方预设有牵连。

---

## 组 C · 渲染与交互（mimo）

### C1 · 表格自适应调优

- **现状**：已用 `{ widthMode: "full", wrapMode: "word", cellPadding: 1 }`，宽表偏松、窄表偏挤。
- **方案**：按终端宽度分档 —— 窄（<100 列）→ `content` + `cellPadding: 0`；宽（≥100）→ `full` + `cellPadding: 1`；超宽按列比例收敛，保证不溢出。
- **验收**：120×30 与 209×51 下同一张 3 列表格都不溢出、不过度留白。

### C2 · 代码块折叠

- **方案**：>15 行的代码块默认只渲染前 15 行 + `▸ 展开（共 M 行）`；按键（建议 `Alt+L`，避免与 `Alt+E` 解释冲突）展开/收起；短块不受影响。
- **技术**：TUI 侧维护"已展开代码块"状态；在 `renderNode` 返回的 CodeRenderable 上做截断。
- **验收**：长块默认折叠、可展开；120×30 不溢出；短块无变化。

### C3 · 动画

- ① 流式光标 `▊` 闪烁；② 等待首 token 的 spinner（`⠋⠙⠹…`）；③ 新消息淡入。
- **验收**：流式有光标、等待有 spinner、结束即停止（无残留）。

### C4 · 回复耗时信息

- 依赖组 A 的 `duration_seconds`：TUI 在 assistant 消息**底部**显示 `· 3.2s`。
- **验收**：每条回复都有；字段缺失时不显示（不伪造）。

### C5 · 思考内容独立展示

- provider 已收集 `reasoning_parts` → 后端发 `assistant.reasoning_delta` / `reasoning_done`；TUI **灰色斜体独立区块**，**回复开始后收起**；**绝不混入正文或历史**。
- **验收**：思考与正文分离；历史里不含思考文本。

### C6 · 思考强度可选（DeepSeek **实测有效** ✓）

**实测（`docs/reasoning-effort-probe.md`）**：`deepseek-flash` 支持
`reasoning_effort: low|high|max`（默认 high）与 `thinking: disabled`；
reasoning 长度**单调**：`disabled(0) < low(2.6k) < high(4.5k) < max(6.8k)`。
（第一版实测曾误判为"无效"，原因是题目太简单 + `max_tokens` 截断 + 样本不足；
修正后结论明确。）

**档位设计**：

| 档位 | 请求参数 |
|---|---|
| `off` | `{"thinking": {"type": "disabled"}}` |
| `low` | `{"reasoning_effort": "low"}` |
| `high`（默认） | `{"reasoning_effort": "high"}` |
| `max` | `{"reasoning_effort": "max"}` |

只暴露文档认可的有效值（`low/high/max` + 关闭）；`minimal/medium/xhigh/ultra`
属兼容映射，不作为档位出现在 UI 里。

**⚠️ 必须配套的 token 预算**：实测中 `max_tokens=2000` + `effort=max` 时
**答案被思考挤成空串**（completion 顶满 2000、answer_chars=0）。因此
`max_tokens` 要**按 effort 预留思考开销**（如
`answer_budget + reasoning_budget(effort)`），否则用户会看到空回复。

**其它供应商**：沿用同一套"**先实测再开放**"的规矩（MiMo `variant`、
OpenAI 推理系），不支持者 UI 置灰、`/think` 明确说明、请求体不带该参数。

**各供应商差异已实测成表**（`docs/reasoning-effort-matrix.md`）：思考控制分成
**四种参数模型**——枚举档位（DeepSeek / OpenAI）、预算制（Anthropic）、
变体名（MiMo）、开关（Ollama 原生）。统一四档 `off/low/high/max` 由后端映射：
OpenAI 无 `max` → 就近用 `high`；Anthropic 用 `budget_tokens`（2k/16k/64k）。
**Ollama 当前走的 OpenAI 兼容端点会忽略 `think`**（实测），因此本地模型默认
**置灰并说明**，除非改走原生端点。

- **验收**：① 四档在支持模型上产出**单调差异**且命令生效并持久化；
  ② **答案不为空**（预算预留生效）；③ 不支持的供应商得到明确说明而非假选项。

---

## 4. 依赖与批次

| 批次 | 内容 | 主责 | 依赖 |
|---|---|---|---|
| **①** | A1+A2+A3（上下文根因 + 落盘） | claude | 无 |
| **②** | A4+A5+C4（tips / 长度提示 / 耗时） | claude（后端字段）+ mimo（展示） | ① |
| **③** | B1+B3（规格可配 + 中转站自定义） | Codex | 无 |
| **④** | B2（官方同步，"未知即标注"） | Codex | ③ |
| **⑤** | A6+A7（compact + 对话历史命令） | claude | ①② |
| **⑥** | C1+C2（表格调优 + 代码折叠） | mimo | 无（可与①并行） |
| **⑦** | C3+C5+C6（动画 + 思考分离/强度） | mimo + claude | 无 |

**并行策略**：第一批同时开 **①（claude，后端）** 与 **⑥（mimo，TUI）**——写集不重叠；**② 的 C4 与 A4 共用后端字段，必须同批串行**；**③④（Codex）** 可插入任意空档。

---

## 5. 需要确认的点

1. **A4 tip 呈现**：建议**状态栏常驻 + 回复只在裁剪时提一句**。
2. **A6 `/compact` 保留轮数**：建议保留最近 10 轮原文。
3. **A5 长度口径**：建议**优先 usage，缺失时估算并标注**。
4. **B2 刷新时机**：建议配置助手手动刷新 + 后台 1 小时 TTL。
5. **C2 折叠阈值/按键**：建议 15 行 + `Alt+L`。
6. **C6 档位**：`off/low/medium/high/max` 是否够（按供应商能力降级）。
