# review 链路思考档位评估（真机验证 + 建议）

> 任务：`.agent-bus/tasks/claude-review-reasoning-assess.json`（agent `claude`）· 日期：2026-09-26
> 脚本：`scripts/verify_review_reasoning.py`（可复跑）· 端点：DeepSeek 官方 `deepseek-flash`
> 密钥：只从 `DEEPSEEK_API_KEY` 环境变量读取，**从不打印、不落盘**；除 DeepSeek 端点外无任何网络请求。
> 关联：`docs/verification-matrix.md`（Live-review-think 行）· `docs/reasoning-effort-probe.md`（裸 API 四档）· `docs/chat-deepseek-live-verification.md`（chat 侧四档）· `docs/claude-backend-followup.md` §2.5
>
> **阅读顺序（2026-09-26 更新）**：**§10 = 最新状态**（第二步落地后的产品入口真机复验：四档数据 + 长 diff × max 预算边界 + 未决项收口）；
> **§9 = 第二步落地记录**（offline wire 证据）；**§1–§8 = 第一步的历史评估**（旧语义 + `extra_params` 夹具真机数据），方法学仍在但结论已被 §10 取代。

---

## 0. 结论（先说）

1. **代码现状（`deepseek` 家族）不是"review 不碰思考参数"，而是"review 显式关闭思考"。**
   `review_code` 确实从不传 `reasoning_effort`，但它带 `structured_output=True`，provider 会据能力档案追加
   `thinking: {"type": "disabled"}`（`review_policy.py:16` ← `model_capabilities.py:32`）。
   真机请求体证实：`{"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}`，无 `reasoning_effort`。
   **这条只对供应商名 = `deepseek` 成立**：`anthropic` 的 policy 返回 `{}`（Anthropic provider 也不看 `structured_output`），
   `ollama`/`local` 被 provider 改写成 `structured_output=False` + `think=False`（`ollama.py:26-28`），
   其余 OpenAI 兼容供应商只有 `response_format`——**思考行为随供应商而异**，详见 §1.1 末表。
   验收矩阵原表述"review 分支不传该参数"已按本节修正（不传的是 effort，不是 thinking，且必须带供应商限定）。
2. **只补一行 `reasoning_effort` 是无效改动**——真机场景 c（wire 上同时有 `reasoning_effort=low` 与 `thinking=disabled`）reasoning 仍为 **0 字符**。
   deepseek 的 review 要吃档位，至少要**覆盖 policy 的 disabled**（`thinking: {"type": "enabled"}`）；
   `reasoning_effort` 负责选档，不传时按官方文档默认 `high`——**enabled-only 的情形本轮没有单独真机验证**（§6 #7）。
3. **代价实测（最小 review 调用，输出额度 6144）**：思考从关到 `max`，reasoning 0 → 3688 字符，
   completion tokens 421 → 1519（**约 3.6×**），单文件耗时 2.2s → 6.4s（**约 2.9×**），答案与 JSON 结构均正常（`finish_reason=stop`，7/7 断言过）。
4. **建议：选 (c)「review 单独档位」，但分两步走**——本轮先把语义写死并加静态断言（零行为变更），
   等产品要"深度审查"时再接入口，且默认值取 `off`（= 现状）。理由见 §4：`(b)` 与双槽路由的设计相冲突（跨槽串味），
   `(a)` 只有当产品明确"review 永不思考"时才够用。

---

## 1. 代码现状（只读审计，未改任何 src）

### 1.1 审查链路的模型调用栈

| 层 | 位置 | 与思考参数的关系 |
|---|---|---|
| 混合编排（**CLI 默认**） | `hybrid_orchestrator.py:371-377`；`AIClient` 按文件重建 provider 配置 `:124-154`；默认开启见 `cli.py:1395,1414` | 同样落到 `AIClient.review_code`；低复杂度文件可被路由到本地 ollama，本地 provider 会强制 `think=False` + `structured_output=False`（`ollama.py:26-28`） |
| 逐文件审查（标准编排） | `review_orchestrator.py:836`（跨文件 `:910`） | 每个文件一次 `ai_client.review_code(system, user)` |
| 客户端 | `ai_client.py:59` `review_code` → `:86-92` `provider.chat(..., structured_output=True)` | **不传** `thinking` / `reasoning_effort` |
| 客户端额度 | `ai_client.py:66-74` → `model_capabilities.py:66-77` | deepseek + 小输入 = **6144**（无思考预留） |
| OpenAI 兼容 provider | `openai.py:379` `_chat_sync`；passthrough `:386-388`；结构化策略 `:391-395` | 只透传调用方**显式给过**的 `think`/`reasoning_effort`；`structured_output=True` 时 `setdefault` 能力档案参数 |
| 结构化策略 | `review_policy.py:10-18` | `supports_json_object → response_format`；`supports_thinking_disable → thinking: disabled` |
| 能力档案 | `model_capabilities.py:25-35`（`:32` `supports_thinking_disable=True`，`reasoning_field="reasoning_content"`） | **deepseek 上"关思考"的唯一来源**（供应商名 → 能力档案 → 参数，见下表） |

**净效果随供应商而异**（同一段 policy 代码，判据来自能力档案；离线核对 `structured_review_params(name, model)`）：

| 供应商 | policy 追加 | review 请求体里的思考参数 |
|---|---|---|
| `deepseek` | `response_format` + `thinking: {disabled}` | **显式关闭**（本次真机对象）：`{model, messages, max_tokens: 6144, response_format: {json_object}, thinking: {disabled}}` |
| `ollama` / `local` | policy 不生效——`OllamaProvider.chat` 先把 `structured_output` 改写成 `False`（`ollama.py:28`） | `think: false`（另一条机制，`ollama.py:26`） |
| `anthropic` | `{}` | 不发（provider 不看 `structured_output`；= 供应商默认） |
| `openai`/`qwen`/`zhipu`/`moonshot`/`siliconflow`/`openrouter` | 只有 `response_format` | 不发 → **供应商默认**（思考型模型即开启，未实测） |

### 1.2 同一产品里其它模型调用路径的对照

| 路径 | 位置 | 思考参数 |
|---|---|---|
| chat（TUI/JSONL） | `jsonl_server.py:2660-2681`（`_chat_reasoning_effort` `:2088`，预算 `:293`） | 按用户档位传 `reasoning_effort`；`off`→`"none"`；low/high/max **预留思考预算**（+4000/+8000/+12000） |
| chat（CLI 单轮） | `cli.py:2450-2460`（`reasoning_effort` 在 `:2457`） | 仅本地 provider 传 `reasoning_effort="none"`，其余不传（= 供应商默认） |
| **建议 patch 生成** | `patch_generator.py:374-380`（`structured_output=False`） | **不关思考**：不结构化 → 不走 policy → 对 DeepSeek 是"默认开启"（代码推断，未真机验证） |
| review 逐文件/跨文件（deepseek） | §1.1 | **显式关闭**（其它供应商见 §1.1 末表：本地 `think=false`、anthropic/多数兼容供应商 = 供应商默认） |

即（以 deepseek 为例）：同一轮 review 里，"找问题"显式关思考、"写修复补丁"按供应商默认开思考——
两条路径目前没有任何一处读过用户的档位偏好。
`tests/test_model_providers.py:428-434` 把 deepseek 的 policy 结论钉死（`thinking: disabled`），`:182` 在 wire 层断言过它。

---

## 2. 真机数据

方法：`scripts/verify_review_reasoning.py` 走**产品自己的审查链路**（`AIClient.review_code` + `PromptAssembler` 生成的真 prompt，
系统 3340 字符 / 用户 1276 字符；最小 diff 为一段"SQL 字符串拼接"改动），4 个场景 × 1 次调用。
`max_retries=1`——不吃格式修复重试，调用次数可核对；`TEMP/TMP` 指向仓库内 `.pytest_claude`。

**档位走的是哪条路径**：没有裸 API、没有改 src，全部经 `AIClient.review_code` → `provider.chat`。
差异只有一个 `AIClientConfig.extra_params`（`config.py:1178`，落盘字段）——`_chat_sync` 把它展开进请求体
（`openai.py:384`；流式孪生 `_stream_chat_sync` 在 `:161`），而 `structured_review_params` 用的是 `setdefault`（`:391-395`），
所以**用户显式给的值能覆盖 policy 的 `thinking: disabled`**。场景 3/4 正是靠这一点做的对照实验；
脚本 docstring 里也如实标注：这只是"测量夹具"，不是推荐把 `extra_params` 当落地入口（落地入口见 §4.3）。
`default` 场景不带任何 extra_params，即产品当前原样请求。

| 场景 | 请求体 `thinking` | 请求体 `reasoning_effort` | reasoning 字符 | 答案字符 | findings | completion tokens | 耗时 | finish_reason |
|---|---|---|---|---|---|---|---|---|
| `default`（**现状**，无 extra_params） | `{"type": "disabled"}` | *缺省* | **0** | 1150 | 2 | 421 | 2.2s | stop |
| `effort_low_only`（只加 effort） | `{"type": "disabled"}` | `low` | **0** | 1575 | 3 | 567 | 2.9s | stop |
| `think_low`（覆盖 policy + low） | `{"type": "enabled"}` | `low` | **384** | 1322 | 2 | 634 | 2.9s | stop |
| `think_max`（覆盖 policy + max） | `{"type": "enabled"}` | `max` | **3688** | 1343 | 2 | 1519 | 6.4s | stop |

- 输出额度均为产品口径 **`max_tokens=6144`**（不是配置字面量 4096）；4 次调用全部 `response_format=json_object`，JSON 均解析成功。
- **复跑对照**（同脚本第一次运行，仪器修正前）：default 0 / effort_only 0 / low **387** / max **2978** 字符，答案 1234/1771/1207/1829，
  耗时 2.3/3.4/2.5/6.3s。两轮在"disabled ⇒ 0 字符"与"max ≫ low > 0"上一致；答案长度本身有随机波动（findings 2↔3），
  与档位无关（前两行档位未生效）。
- 调用计数：**每次运行 4 次 provider 调用**，无隐藏重试（脚本断言 g）。两轮共 8 次（第一轮的探针只看 `provider.chat` 的 kwargs，
  漏看了 policy 在 provider 内部追加的 `thinking`；已改为在 `urllib.request.urlopen` 层记录请求体，第一轮数据仅作复现性对照）。
- 成本影响：输入约 4.6k 字符（≈1.2k tokens，按产品估算口径），成本由输出主导；`max` 档每次调用多花约 1.1k completion tokens，
  按逐文件 × 并发 2 × 文件数放大。

---

## 3. 脚本断言（7/7）

| # | 断言 | 门禁 | 结果 |
|---|---|---|---|
| a | 现状请求体：`thinking=disabled` 且无 `reasoning_effort` | ✅ | PASS |
| b | 现状：reasoning=0 且答案非空（1150 字符，2 findings） | ✅ | PASS |
| c | 只补 `reasoning_effort` 不足以开思考（wire 有 low，reasoning 仍 0） | ✅ | PASS |
| d | `thinking=enabled` + low：reasoning 384 字符且答案非空 | ✅ | PASS |
| e | `thinking=enabled` + max：reasoning 3688 字符且答案非空（`finish_reason=stop`） | ✅ | PASS |
| f | max 档 reasoning > low 档（单次抽样，方向性） | ✅ | PASS（384 < 3688） |
| g | 每个场景恰好 1 次 provider 调用（无隐藏重试） | ✅ | PASS（per_scenario 四项均 1） |

退出码：`0` 门禁全过 / `1` 有门禁断言失败 / `2` 环境不可用（无密钥、认证失败、四个场景全部失败）。

回归（本轮改动 = 新增脚本 + 新增本文档 + `docs/verification-matrix.md` 两行，未动 `src/` 与 `tests/`）：
`python -m pytest -q --no-cov` → **1144 passed, 1 skipped, 1 warning in 88.41s**（`TEMP/TMP=.pytest_claude`）。
条数与 `docs/verification-matrix.md` §3.1 的记录一致（那里是另一次现场复跑，91.99s；通过/跳过数相同，时长差异属机器负载）。

> 断言 g 在 run2 之后收紧为"每个场景恰好 1 次"（原先只校验总数 4）。run2 四个场景全部成功、
> 且 `max_retries=1` 下重试分支不可能触发（`ai_client.py:109` 要求 `attempt < max_retries-1`），
> 因此 run2 记录同样满足收紧后的判据。同批改动还包括输出多一行 `ProviderResponse.reasoning`
> 非空计数（服务于 §6 #2；渲染路径已用离线 dry-run 验证）——两者都不改变 run2 的任何数字。
日志证据：`.pytest_claude/review-reasoning-run2.utf8.log`（本报告数据，7/7）、`.pytest_claude/review-reasoning-run1.utf8.log`（仪器修正前，6/7——唯一失败项是当时还没取证到 wire 上的 `thinking`）。
同名 `.log` 是 Windows 中文控制台的 cp936 原始捕获，`.utf8.log` 是同一内容的转码副本（逐行一致，仅编码不同）。

---

## 4. 三选一建议

### 4.1 (a) 保持不传 —— 只在产品明确"review 永不思考"时成立

- **今天的行为已经是一种选择**（能力驱动的显式关闭），不是"未实现"；它对结构化输出最稳（`response_format` + 无思考，2.2s/文件、421 tokens）。
- 若选 (a)，必须补三件事，否则语义仍会被下一个人重新问一遍：
  1. 文档写死"review 不使用用户档位，且对支持关闭思考的供应商显式关闭"；
  2. **静态断言**：`structured_review_params("deepseek", ...) == {response_format, thinking: disabled}`（已有 `tests/test_model_providers.py:428-434`）
     + 一条 wire 级用例断言 `reasoning_effort` 不出现在审查请求体里。
  3. 顺带澄清 `patch_generator` 路径（§1.2 第 3 行）：同一轮 review 内两条路径思考行为相反，若 (a) 是正式语义，这里也该显式关闭。
- 风险：用户可见的 `/think off|low|high|max` 只管聊天，review 深度在 UI 上无处可调——产品上是否接受，需要拍板。

### 4.2 (b) 全局档位也管 review —— 建议否决

- 本产品的双槽路由（`chat_slot` / `review_slot`）允许审查模型与聊天模型**不是同一个**；
  用聊天槽的档位去改审查请求正是 `docs/claude-backend-followup.md` §2.5 已否决过的"跨槽串味"。
- 语义也不对齐：chat 的 `auto` 表示"让 provider 自己定"，而 review 的等效默认是 `off`（现状）；
  用户在 chat 里为了省钱选 `off`，review 就**跟着永不思考**（反过来为聊天选 `max`，审查成本会静默 ×3.6，而聊天本身并不需要）。
- 唯一优点是"一个旋钮"，但代价是 review 的默认行为被 chat 的偏好绑定，属于隐式行为变更。

### 4.3 (c) review 单独档位 —— 推荐，两步走

**第一步（零行为变更，可立即落地）**：把 review 的思考语义写成可执行事实——
文档（本文件 §1）+ 一条 wire 级 pytest（`review_code` 发出的请求体含 `thinking: disabled`、不含 `reasoning_effort`），
等价于给现状加锁，不引入新配置项。

**第二步（产品要"可调审查深度"时）**：新增 `preferences.review_reasoning_effort`，词表复用 chat 的
`off|low|high|max|auto`（**默认 `off` = 现状**，`auto` = 不干预、由 policy 决定），实现要点：

> **状态：已落地**（任务 `claude-review-effort-step2`，2026-09-26）。下表的每个落点都已实现，
> 实际文件:行号、wire 断言与测试数字见本文 **§9**；下表保留为设计原稿（行号是设计时的，已过时）。

| 落点 | 位置 | 要点 |
|---|---|---|
| 偏好字段 + 归一化 | `config.py`（`normalize_chat_reasoning_effort` 同款，`:962`） | 非法值告警回退，保持"加载坏文件也要能起"的口径 |
| 请求注入 | `ai_client.py:86-92`（`AIClientConfig` 加字段，`:1178` 区） | 注入点必须在 `review_code` 里按请求计算，**不要走落盘的 `extra_params`**：混合编排会按文件重建 provider 配置并用 `dict(selected_config.extra_params)` 覆盖（`hybrid_orchestrator.py:151`），本地分支还会换成 ollama 预设（`:367-369`）。`off` → 维持 policy 的 `thinking: disabled`；`low/high/max` → **至少**覆盖成 `thinking: {"type": "enabled"}` 再传 `reasoning_effort`（真机 c 证明只传 effort 无效；enabled-only = 默认 high 未单独验证） |
| 预算预留 | `model_capabilities.py:66-77` | 按 chat `CHAT_REASONING_TOKEN_BUDGETS`（`jsonl_server.py:293`）同口径加 +4000/+8000/+12000，并仍受 `max_output` 封顶——思考与答案抢同一个 completion 额度（`docs/reasoning-effort-probe.md` 的教训：预算是真的会顶满） |
| 出口（可选） | `jsonl_server.py` `config.snapshot` / `_setup_options`、`cli.py preferences` | 与 `chat_reasoning_effort` 同样式；review 侧目前没有 `/think` 等价命令，需产品决定入口 |
| 成本护栏 | `ai_client.py` `_reserve_cost`/`_enforce_cost_limits` | `max` 档输出 token ×3.6，`max_cost_per_run` 默认 5 美元仍够，但应把倍数写进文档/提示 |
| 测试 | `tests/test_model_providers.py`（wire 断言）、`tests/test_config.py`（词表 pinning） | 参考 `test_symbol_locate_vocabulary_matches_the_config_layer` 的"配置层不告警 ⇔ 入口接受"写法 |

**成本估计**：一个配置项 + 请求注入 + 预算预留 + 词表/接线用例，规模与既有的 `claude-symbol-locate-config` 同量级；
风险集中在 review 请求体（已被测试与真机钉住）与预算计算（有 chat 侧成熟先例）。
**风险**：`max` 档在长 diff 上可能把 6144（跨文件 12288）额度大量吃在 reasoning 上——本任务的最小 diff 未触及该边界，
上线前应按"最长 prompt × max 档"补一次真机验证（§6 #3）。

---

## 5. 与 chat 侧一致性分析

| 维度 | chat（TUI/JSONL） | review（当前） | 若走 (c) 后 |
|---|---|---|---|
| 档位来源 | `preferences.chat_reasoning_effort` | 无（按供应商能力档案/ provider 决定） | `preferences.review_reasoning_effort`（默认 off） |
| 线上参数 | `reasoning_effort: off→"none" / low/high/max` | deepseek：`thinking: {disabled}`；本地：`think: false`；anthropic / 多数兼容供应商：**不发（供应商默认）** | off→不变；其余→`thinking: enabled` + `reasoning_effort`（非 deepseek 供应商需各自给出等价参数，见 `docs/reasoning-effort-matrix.md`） |
| 预算预留 | +4000/+8000/+12000，且受 `max_output` 封顶 | 无 | 同口径补齐 |
| 思考可见性 | `assistant.reasoning_delta` 流式 + TUI `ThinkingBlock` 折叠 | **拿不到**：非流式路径不回填 `ProviderResponse.reasoning`（`openai.py:439-444`），只有 token 计数 | 需要时另行改造（见 §6 #2） |
| 空答案兜底 | 思考吃满预算 → 答案为空有实测教训与预留 | 不适用（无思考） | 必须沿用同一预留，否则重演"空答案→格式错误" |
| 本地 provider | 置灰/`none`，并预留额度 | 靠 `OllamaProvider` 的 `think=False`（`ollama.py:26`）关思考，与 policy 无关 | 同 chat：本地不开放档位 |

一句话：**chat 的档位是"用户可见的体验旋钮"，review 的档位是"成本/质量取舍"**；两者默认值应当不同（chat 默认 `auto`，review 建议默认 `off`），
所以它们不该是同一个开关。

---

## 6. 未决 / 未验证项（诚实清单）

| # | 项 | 说明 |
|---|---|---|
| 1 | 产品语义未拍板 | 本任务把事实与代价补齐了，但"review 要不要可调档位"仍是产品决策（(c) 第二步的入口形态也待定） |
| 2 | review 侧看不到思考文本 | 非流式 `_chat_sync` 不填 `ProviderResponse.reasoning`（`openai.py:439-444`），reasoning 只在 `content` 为空时被当答案兜底（`:463-473`）——开了思考也只有 token 计数；若 content 为空，兜底文本会进 JSON 解析并失败 |
| 3 | ~~大 prompt × max 档的预算边界未测~~ **已收口（2026-09-26，见 §10.4）** | 382 行 / 29.6k 字符 patch × `max`（产品入口）：completion **5139 / 20192 tokens（余量 15053）**、`finish_reason=stop`、答案 6393 字符、JSON 可解析——未截断、未空答；预留 12000 只用了 22.4% |
| 4 | 单模型单端点单样本 | **部分收口**（§10.2/§10.3）：仍是 `deepseek-flash` + 官方端点，但样本扩到"短四档 4 + 长四档 3 + 长 off 1"；`deepseek-chat`、中转站（custom 端点）、其它供应商未测；裸 API 的单调性由 `docs/reasoning-effort-probe.md`（每档 3 次）背书 |
| 5 | `patch_generator` 路径未真机验证 | §1.2：`structured_output=False` ⇒ 对 DeepSeek 是"思考默认开启"，仅代码推断 |
| 6 | 本任务未提交 | 任务约束禁止 git 操作；证据为工作区文件 `scripts/verify_review_reasoning.py`、本文件、`docs/verification-matrix.md`（Live-review-think 行 + §2 #1 两行）、`.pytest_claude/review-reasoning-run{1,2}.utf8.log` |
| 7 | `thinking: enabled` 不带 effort 的情形未测 | 真机只测了带 effort 的组合（第一版 enabled+low / enabled+max；第二步后 low/high/max 四档全部带 effort，见 §10.5）；按官方文档缺省应为 `high`，**仍未实测**（§0.2 的措辞已按此收窄） |
| 8 | 混合编排（CLI 默认路径）未单独真机验证 | `hybrid_orchestrator.py:371-377` 同样调 `review_code`，但会按文件重建 provider 配置、可能把低复杂度文件路由到本地模型；本次真机只覆盖 `AIClient` + `review_orchestrator` 的等价调用参数（kwargs 完全一致，因为都是 `review_code`），路由差异未测 |
| 9 | 非 deepseek 供应商的 review 思考行为未测 | §1.1 末表是按 `structured_review_params` 的离线结果推的；"兼容供应商 = 供应商默认（思考型即开启）"只有代码推断 |

---

## 7. 复跑指引

> **2026-09-26 更新（第二步后）**：脚本默认口径已从"extra_params 夹具四场景"换成
> **产品入口**的 `levels` + `long` 两个场景（默认 7 次调用）。上面 §2 的四个夹具场景仍在，
> 用 `--scenario legacy` 调出。当前默认命令与数据见 §10。

```powershell
# 密钥只从环境变量读，勿写进命令行/文档
$env:TEMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_claude'
$env:TMP=$env:TEMP
$env:PYTHONIOENCODING='utf-8'   # 中文输出重定向到文件时避免 cp936 乱码
python scripts/verify_review_reasoning.py                       # 默认：四档（短）+ 长 diff × max ×2 + off 对照 = 7 次调用
python scripts/verify_review_reasoning.py --json                # 机器可读
python scripts/verify_review_reasoning.py --scenario levels     # 只跑四档（4 次）
python scripts/verify_review_reasoning.py --scenario long       # 只跑长 diff 边界（3 次）
python scripts/verify_review_reasoning.py --scenario levels --prompt long --level low,high,max
                                                                # 四档跑在长 diff 上（3 次；max 兼具边界样本，§10 的数据就是这么来的）
python scripts/verify_review_reasoning.py --scenario legacy     # 第一版 extra_params 夹具（4 次，§2 数据）
python scripts/verify_review_reasoning.py --model deepseek-chat # 换模型（注意封顶来源会变，见 §10.2）
```

脚本内置**硬预算**：计划超过 `CALL_BUDGET = 8` 次真实调用直接拒绝跑（exit 2），不会因为参数组合悄悄多花钱。

退出码：`0` 门禁全过；`1` 有门禁断言失败；`2` 环境不可用（无密钥 / 认证失败 / 场景全部失败 / 超预算）。
两次运行之间无需清理任何文件（脚本不落盘、不写配置、不建临时目录）。
---

## 8. 已加锁（第一步完成，2026-09-26）

`tests/test_review_wire.py` —— 4 条 **wire 级**断言，钉住本文 §1 记录的现状。
（说明：该任务原派 codex，因其模型中转持续网络失败无法完成，由主控实现并验证。）

| 用例 | 钉住的现状 |
|---|---|
| `test_deepseek_review_wire_disables_thinking` | `response_format: json_object` + `thinking: {type: disabled}` + **不含** `reasoning_effort` + `max_tokens=6144`（能力档案值） |
| `test_local_ollama_review_wire_forces_think_false` | `think: false`（另一条机制），无 `thinking` 对象、无 `reasoning_effort` |
| `test_anthropic_review_wire_sends_no_thinking_params` | 不发 `thinking`/`reasoning_effort`（policy 空表 + provider 不看 `structured_output`） |
| `test_patch_generator_path_wire_snapshot` | 非结构化路径：无 `thinking`/`reasoning_effort` —— **现状快照，不是期望语义**（§1.2 风险项），产品决定统一时先改此断言 |

实现方法：monkeypatch `urllib.request.urlopen`（provider 的真实出网口）捕获请求体，不 mock
请求构造；anthropic 走 SDK，改用 `client_factory` 捕获传给 provider 的 kwargs。

复跑：`python -m pytest -q --no-cov tests/test_review_wire.py`（4 passed，0.2s）。

**触发第二步的信号**：产品要"可调审查深度"时按 §4.3 实现（`preferences.review_reasoning_effort`
默认 off），届时本文件的断言按新语义更新（off 档保持不变，low/high/max 出现
`thinking: enabled` + `reasoning_effort` 且预算随档位增加）。

---

## 9. 第二步已落地（任务 `claude-review-effort-step2`，2026-09-26）

第二步按 §4.3 实现：**review 独立档位、默认 `off`**（= 现状逐字不变），入口是 preferences /
CLI `config preferences` / 配置助手后端字段。本任务约束**不发真实网络请求**，因此下面是
offline wire 证据（monkeypatch `urllib.request.urlopen` 读真实请求体）+ 静态核对，
真机结论仍以上文 §2 为准。

### 9.1 落点（工作区 HEAD，行号以本次改动后的文件为准）

| 层 | 位置 | 要点 |
|---|---|---|
| 词表 + 默认值 | `config.py:748`（`REVIEW_REASONING_EFFORTS = CHAT_REASONING_EFFORTS`）、`:749`（`DEFAULT_REVIEW_REASONING_EFFORT = "off"`） | 复用 chat 那一份元组（同序、同一个对象），只有默认值不同 |
| 归一化 | `config.py:984`（`normalize_review_reasoning_effort`） | 与 `normalize_chat_reasoning_effort` 同款：大小写/空白归一、非法值告警回退 `off`、绝不抛异常、不回显原值 |
| 偏好字段 | `config.py:1051`（`PreferencesConfig.review_reasoning_effort`），在 `__post_init__` 归一化 | 加载/导入/向导三条路径共用同一套回退规则 |
| 运行时副本 | `config.py:1227`（`AIClientConfig.review_reasoning_effort`）；同步点 `config.py:1445`（`_sync_runtime_sections`） | preferences 是唯一入口；落盘 `ai_client` 段的旧值不得盖过它。放 `ai_client` 上是因为混合编排按文件重建配置用的是 `**self.config.ai_client.__dict__`（`hybrid_orchestrator.py:142-154`） |
| 请求注入 | `ai_client.py:102`（`review_code` 里按请求计算）、`:177`（读档位）、`:192`（`_review_reasoning_plan`）、`:249`（`_review_tokens_with_budget`）、`:259`（`_review_max_output` 封顶来源）、`:280`（`_review_request_provider`） | 参数分两路，拆分由 `reasoning_specs.split_reasoning_params` 唯一决定：`think`/`reasoning_effort` 走 `chat(**kwargs)` 白名单（Anthropic 协议下该通道失效，参数直接丢弃）；`thinking`/`enable_thinking`/`thinking_budget`/`reasoning` 走**本次请求新建的** provider 配置副本（`dataclasses.replace`）——落盘配置与共享 provider 一个字节都不写 |
| 通道判据 | `reasoning_specs.py:616`（`reasoning_kwargs_consumed`）、`:631`（`reasoning_delivery_blocked_reason`）、`:650`（`split_reasoning_params`） | 注入点与出口共用一份判据，避免"代码不注入、出口宣称已生效" |
| 快照出口 | `jsonl_server.py:912`（`config.snapshot.review_reasoning_effort`） | 与 `chat_reasoning_effort` 同样式；前端接入另行排期（本任务不改 TUI） |
| 配置助手出口 | `jsonl_server.py:982`（`_review_reasoning_options`）、`:1337`（`config.options`）、`:1694`（`config.setup` 写入）、`:1866`（`model.status`） | `{value, options[5], label}`；不支持注入的供应商附 `state`/`reason`（本地置灰 / 未收录 / Anthropic 协议端点丢弃参数）；三个出口同键同形（与 repo_context/symbol_locate 同一约定） |
| CLI 出口 | `cli.py:3454`（`_review_reasoning_note`，内部 `inert_reason` `:3468`）、`:3553`（`--review-reasoning-effort`，`click.Choice` 用 config 词表）、`:3608`（写入 + 回显 + 追加说明） | 一条命令脚本化；档位非 off/auto 而审查槽供应商送不出参数时，payload 追加 `review_reasoning_note`（hybrid 会把本地槽一并说明） |
| 向导回归 | `cli.py:1134`、`:1226` | 两个 `PreferencesConfig` 重建点原样带回档位（否则跑一次向导会静默重置为 off） |

### 9.2 wire 证据（deepseek，monkeypatch `urlopen` 读请求体；`tests/test_review_wire.py`）

| 档位 | 请求体 `thinking` | `reasoning_effort` | `max_tokens` | 说明 |
|---|---|---|---|---|
| 未设置 / `off`（默认） | `{"type": "disabled"}` | 缺省 | 6144 | **与改造前逐字相同**（第一步断言原样保留） |
| `low` | `{"type": "enabled"}` | `low` | 10144 | 6144 + 4000 |
| `high` | `{"type": "enabled"}` | `high` | 14144 | 6144 + 8000 |
| `max` | `{"type": "enabled"}` | `max` | 18144 | 6144 + 12000 |
| `auto` | `{"type": "disabled"}` | 缺省 | 6144 | "不干预" ⇒ 与 off 同形（由 policy 决定） |
| 非法值（构造后赋 `"extreme"`） | `{"type": "disabled"}` | 缺省 | 6144 | 静默回退 off（配置层已告警过） |

预算封顶与其它供应商（同文件）：anthropic `max` → `max_tokens=8192`（= 规格 `max_output`，
请求值 16096 被截）、`thinking.budget_tokens=4096`（官方约束 `budget_tokens < max_tokens`
且给回答留出基础额度）；qwen `high` → `enable_thinking=true` + `thinking_budget=4096`
（cap 后 `8192-4096`）；api2d（transparent）`high` → 透传 `reasoning_effort` +
`max_tokens=12096`（`min(4096+8000, 预设 gpt-4o-mini 16384)`）；
baichuan / 未收录供应商 → **不注入、不预留**（`max_tokens` 仍是 4096）；
ollama/local → 仍是 `think: false`、无 `thinking`/`reasoning_effort`、不预留。

**封顶来源 = 内置预设优先**（`_review_max_output`，与 chat `_chat_max_output` 的取舍一致）：
`PROVIDER_MODEL_PRESETS` 是仓库里唯一可引用的厂商数值，没有该模型时才退回能力档案
（deepseek 32_768 / anthropic 8_192 / 其余 8_192）。这条修正了一个真实缺陷：能力档案对
未收录供应商一律给 8192（比预设的 4096 **大**），只按它封顶会让 stepfun/hunyuan/custom-model
这类模型的请求额度被档位顶到 8096——超过模型输出上限，云端直接 400
（`tests/test_review_wire.py::test_review_budget_is_capped_by_the_preset_not_the_profile_default`
钉住 4096）。

**Anthropic 协议的中转端点整档不生效**：`factory` 按 `api_format == "anthropic"` 选 provider，
`AnthropicProvider.chat()` 只读 `max_tokens`/`system_prompt`/`extra_params`——kwargs 里的
`reasoning_effort` 会被丢弃。判据收在 `reasoning_specs.split_reasoning_params`
（+`reasoning_kwargs_consumed`）：这类端点两路皆空 ⇒ **不注入、不预留**，
且 `config.options` 与 CLI 说明会把它的 `state` 标成 `unsupported` 并给出原因
（`ANTHROPIC_PROTOCOL_REASON`），不再宣称"已透传"。

**不落盘**：跑完 `max` 档后 `client._config.extra_params == {}` 且
`client._provider.config.extra_params == {}`（另有"同一客户端先 max 再 off"的用例断言第二次
请求回到 `disabled`）——这正是 §4.3 提醒的混合编排陷阱（按文件重建配置会用
`dict(selected_config.extra_params)` 覆盖）。

**`off` = 维持现状，不是"对所有供应商强发 disabled"**：`off`/`auto` 一律不注入任何参数，
deepseek 的 `disabled` 来自 policy（`supports_thinking_disable` 只对 deepseek 为真），
其余供应商维持各自默认。规格表里 zhipu/moonshot 等家的 off 档虽然写着
`{"thinking": {"type": "disabled"}}`，review 侧**不会**下发它——强发一个从未真机验证过的
关闭参数属于行为变更（`tests/test_review_wire.py` 的
`test_off_and_auto_never_inject_for_non_deepseek_providers` 钉住这一点）。

### 9.3 测试与出口核对

| 文件 | 新增用例 | 覆盖 |
|---|---|---|
| `tests/test_config.py:791-910` | 22 条 | 词表 pinning（`REVIEW_REASONING_EFFORTS == ("off","low","high","max","auto")` 且 `is CHAT_REASONING_EFFORTS`）、默认 off（preferences + AIClientConfig + from_env）、合法值不告警、大小写归一、非法值回退 + 不回显原值、旧配置静默加载、坏值加载保住其它设置、落盘往返 + `__dict__`/`asdict` 视图、preferences → `ai_client` 同步（含落盘旧值不得覆盖） |
| `tests/test_review_wire.py:200-568` | 17 条 | 四档 × deepseek 的 wire 断言（含 `auto`、非法值、跨请求不残留，两条"不注入"用例带**正对照**）、`off`/`auto` 对非 deepseek 供应商**不注入**（zhipu）、本地置灰、置灰/未收录不注入、transparent 透传 + 预设封顶（stepfun/hunyuan 不被顶到 8192）、Anthropic 协议中转端点整档不生效、qwen 预算通道、anthropic 封顶 |
| `tests/test_jsonl_backend.py:6822-6981` | 6 条 | snapshot 默认 off、`config.options` 词表与 label、`config.setup` 写入 → 落盘 → 重载 → `ai_client` 档位、非法值整单失败且不写、置灰供应商（本地/未收录/Anthropic 协议中转）的出口说明、三出口同键同形 |
| `tests/test_reasoning_specs.py:372-431` | 4 条 | `split_reasoning_params` 两路拆分、Anthropic 协议丢 kwargs 但保留预算参数、`reasoning_kwargs_consumed` 与 factory 分支一致、`reasoning_delivery_blocked_reason` 与注入点判据同源 |

命令与数字（`TEMP/TMP=.pytest_claude`）：

```
python -m pytest -q --no-cov            → 1299 passed, 1 skipped, 1 warning in 85.18s
python -m pytest -q --no-cov tests/test_config.py          → 171 passed（含 22 条新增）
python -m pytest -q --no-cov tests/test_review_wire.py     → 18 passed（4 条第一步 + 14 条新增）
python -m pytest -q --no-cov tests/test_jsonl_backend.py   → 234 passed（含 5 条新增）
```

条数对照：改动前同一条全量命令的最近一次记录是 1258 passed + 1 skipped
（`docs/verification-matrix.md` §1 的 C6b 行，reasoning-specs 任务，2026-09-26），
本次新增条数全部来自上表三个文件（另有 4 条落在 `tests/test_reasoning_specs.py`：
`split_reasoning_params` / Anthropic 协议的通道判据）。

CLI 出口实测（临时配置目录，`AI_PR_REVIEW_CONFIG` 指向它；无网络调用）：
`pr-review config preferences --review-reasoning-effort high` → 退出码 0、payload
`"review_reasoning_effort": "high"`、落盘 `preferences.review_reasoning_effort == "high"`；
`--review-reasoning-effort turbo` → 退出码 2（click 词表拒绝）。向导两个重建点的回带由
`cli._prompt_interface_preferences` / `cli._prompt_preferences` 直调核对（返回对象仍是 `max`）。

### 9.4 本次未做 / 未决

| # | 项 | 说明 |
|---|---|---|
| 1 | ~~真机（联网）验证~~ **已完成（2026-09-26，见 §10）** | 本次按 §7 复跑指引走**产品入口**：短四档 + 长 diff（382 行）四档 + 长 off 对照，完成调用 8 次、10/10 门禁全过；wire 形态与本节离线表逐字一致（`off`=`disabled`+无 effort，`low/high/max`=`enabled`+effort+预算随档位增加） |
| 2 | 低成本/长 diff 的预算边界 | §6 #3 仍在：`max` 档在长 prompt 上可能把额度大量吃在 reasoning 上（cap 只保证不超 `max_output`，不自动降档） |
| 3 | 前端接入 | TUI 尚未渲染 `config.options.review_reasoning_effort`（本任务明确不改前端）；状态栏也没有该字段（只进了 `config.options` 与 `config.snapshot`） |
| 4 | 向导丢字段（**既有问题，非本任务引入**） | `cli._prompt_interface_preferences` / `cli._prompt_preferences` 整体重建 `PreferencesConfig`，字段清单里没有 `repo_context`（4 项）、`symbol_locate`、`chat_slot`/`review_slot`、`chat_reasoning_effort`、`chat_context_budget` —— 跑一次 CLI 向导会把它们静默重置为默认值。本任务只把自己的字段加进清单（否则新档位有同样问题），其余字段的取舍（哪些该在向导里提问）建议另开任务处理 |
| 5 | review 侧看不到思考文本 | §6 #2 仍在：非流式 `_chat_sync` 不回填 `ProviderResponse.reasoning`，开了档位也只有 token 计数 |
| 6 | 用户逐模型规格不影响封顶 | `_review_max_output` 只读得到 `PROVIDER_MODEL_PRESETS`（`AIClientConfig` 不带 provider 的逐模型表）。配置助手里手写的 `provider.models[...].max_output` 比预设小（如 2048）时，档位仍按预设封顶；比预设大时也不会放宽。off 档的基础额度（`calculate_review_output_budget`）本来就是这个口径，不是本次引入的差异 |
| 7 | 每次请求新建 provider 的 SDK 客户端不复用 | 走 `extra_params` 通道的供应商（anthropic/zhipu/qwen/siliconflow…）在开启档位时**每个请求**新建一份 provider 配置副本 + provider；anthropic 会在 `_default_client_factory` 里新建一个 `AsyncAnthropic`（未显式 `aclose()`，随 GC 回收）。100 文件 × `high` ≈ 100 个客户端实例（并发上限 2）。chat 侧本来就是每轮新建 provider，口径一致；若后续要优化，可给 provider 加"按参数复用"的缓存 |
| 8 | `config import` 对旧导出会把档位打回 off | `config_entry.run_config_import` 整体替换 `preferences`（与其它偏好一致）：旧的导出文件里没有这个键，导入后按默认 `off` 处理。文档已在这里点名，避免下一次"导入后档位怎么没了"的困惑 |
| 9 | Anthropic 协议的中转端点只能"置灰" | 见 §9.2 末段：这类端点的 effort 透传会被 SDK 丢弃，因此整档不生效（有出口说明）。若将来要支持，需要按 Anthropic 的 `thinking.budget_tokens` 参数形态另开一条规格（当前按供应商名查表，`custom` 拿到的是 transparent 那条） |

---

## 10. 第二步后 · 真机复验（任务 `claude-review-live-verify`，2026-09-26）

第二步（§9）落地时只有 offline wire 证据，§9.4 #1 写着"上线前建议按 §7 复跑一次真机"。本节就是那次复跑：
**走产品入口**（`preferences.review_reasoning_effort` → `AIClientConfig.review_reasoning_effort` →
`ai_client._review_reasoning_plan`），不再用 §2/§4.3 的 `extra_params` 夹具；端点仍是 DeepSeek 官方 `deepseek-flash`。

### 10.1 方法

| 项 | 值 |
|---|---|
| 入口 | `AIClient.review_code` 真实调用；每个场景一个 `AIClient`，档位写在 `AIClientConfig.review_reasoning_effort`（产品字段，不是夹具）。`max_retries=1`（调用数可核对，且不允许格式修复重试掩盖"答案被挤空"），`timeout_seconds=300` |
| 长 diff | **382 行 / 13038 字符** patch（`difflib.unified_diff` 合成，含拼串 SQL / 无超时 / 无重试 / 全局缓存等真实缺陷）→ 产品 `ContextBuilder`（tree-sitter 解析出 11 个函数，窗口上下文 12216 字符）→ `PromptAssembler`：**user 26226 + system 3340 = 29566 字符** |
| 短 diff | §2 那一份最小 diff：system 3340 + user 1276 = **4616 字符** |
| 命令 | run3：`python scripts/verify_review_reasoning.py`（默认口径：短四档 + 长 diff off 对照）；run4：`python scripts/verify_review_reasoning.py --scenario levels --prompt long --level low,high,max` |
| 调用 | **完成 8 次**（run3：短 off/low/high/max + 长 off；run4：长 low/high/max）；另有 1 次中途终止，见 §10.6 |
| 密钥 | 只从 `DEEPSEEK_API_KEY` 读，**不打印、不落盘**；除 DeepSeek 端点外无任何网络请求；`TEMP/TMP` 指向仓库内 `.pytest_claude` |

日志：`.pytest_claude/review-live-run4.utf8.log`（本节主数据，**10/10 门禁全过，exit 0**）、
`.pytest_claude/review-live-run3.utf8.log`（含被中止的那次与短 diff 数据）。

### 10.2 四档数据（长 diff · 产品入口）

| 档位 | wire `thinking` | `reasoning_effort` | `max_tokens` | reasoning 字符 | reasoning tokens | completion tokens | 答案 ≈tokens | 答案字符 | findings | JSON | finish | 耗时 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `low` | `{"type":"enabled"}` | `low` | 12192 | 1931 | 476 | 1343 | 867 | 2226 | 3 | ✅ | stop | 6.0s |
| `high` | `{"type":"enabled"}` | `high` | 16192 | 7310 | 1877 | 3420 | 1543 | 4331 | 5 | ✅ | stop | 13.9s |
| `max` | `{"type":"enabled"}` | `max` | **20192** | **9828** | **2693** | **5139** | 2446 | 6393 | 7 | ✅ | stop | 20.7s |

- **预算与产品规则逐字吻合**：12192 = 8192+4000、16192 = 8192+8000、20192 = 8192+12000。
  8192 是 `calculate_review_output_budget` 对 ≥12k 字符输入的 deepseek 基础额度（`model_capabilities.py:83`）；
  +4000/+8000/+12000 来自 `CHAT_REASONING_TOKEN_BUDGETS`（`config.py:753`）。
- **封顶口径修正（实测核对）**：任务书写"受 `max_output=32768` 封顶"——32768 是**能力档案**给 deepseek 的值，
  而 `_review_max_output` 是**内置预设优先**：`deepseek-flash` 在 `PROVIDER_MODEL_PRESETS` 里 `max_output = 384000`
  （`config.py:372`），所以 +12000 全额生效、根本触不到封顶。32768 只在"预设里没有的模型"上生效
  （如 `--model deepseek-chat`：20192 < 32768，仍不封顶）。**结论：本档位在 deepseek 上不存在被 `max_output` 截断的风险。**
- **单调性成立**（单次抽样）：reasoning 字符 1931 < 7310 < 9828；tokens 476 < 1877 < 2693；
  completion tokens 1343 < 3420 < 5139；耗时 6.0 < 13.9 < 20.7s。
- 三档 `finish_reason` 全为 `stop`，答案全部非空且 JSON 可解析（findings 3/5/7）。

**与 §2（最小 diff）的量级对照**：同样 `max` 档，短 diff reasoning 3688 字符 / completion 1519 tok / 6.4s
→ 长 diff 9828 字符 / 5139 tok / 20.7s（**2.7× / 3.4× / 3.2×**）。注意 §2 是 `extra_params` 夹具、本表是产品入口
（wire 形态逐字一致，入口不同），倍数只作量级参考。

### 10.3 短 diff 对照（run3，含 off 基线）

| 场景 | `max_tokens` | reasoning 字符 | completion tokens | 答案字符 | findings | finish | 耗时 |
|---|---|---|---|---|---|---|---|
| 短 × `off`（现状） | 6144 | **0** | 702 | 1851 | 3 | stop | 3.6s |
| 短 × `low` | 10144 | *未采到* | *未采到* | *未采到* | 2 | — | 1.9s |
| 短 × `high` | 14144 | *未采到* | *未采到* | *未采到* | 3 | — | 4.5s |
| 短 × `max` | 18144 | *未采到* | *未采到* | *未采到* | 2 | — | 5.1s |
| 长 × `off` | 8192 | **0** | 1846 | 4646 | 7 | stop | 7.2s |

- 打星的三行是 §10.6 探针缺陷的产物：**wire 侧（`thinking`/`effort`/`max_tokens`）与产品侧（解析成功、findings 数、
  耗时）都正常**，只有 response 侧的 token/文本没采到；`off` 两行（短/长）完整，是成本基线。
- `off` 仍是"显式关闭"（wire `thinking: {"type":"disabled"}`、无 `reasoning_effort`），与 §9.2 的离线表逐字一致；
  长 diff 下基础额度按产品规则升到 8192（≥12k 字符）。

### 10.4 长 diff × max 的预算边界（本任务重点）

单次抽样，但余量极大，方向性明确：

1. **没有吃满额度**：max 档 completion **5139 / 20192 tokens，余量 15053（74.5% 未用）**；`finish_reason=stop`（非 `length`）。
2. **答案没有被挤空**：原始 `message.content` 6393 字符，**未走** `_extract_message_text` 的 reasoning 兜底
   （`answer_from_reasoning=False`），JSON 解析 + `ReviewResult` 校验通过（findings 7）。
3. **思考确实与答案抢同一份额度**：reasoning 2693 tok 占请求额度 13.3%，占本次 completion 的 **52.4%**
   ——思考比答案（2446 tok）还多，这正是 `docs/reasoning-effort-probe.md` 记录的下限风险的形态；
   但在 382 行规模上离"吃满"还差一个量级。
4. **+12000 预留足够，且远有余量**：预留 12000 全额生效（20192−8192），思考只用了其中 **22.4%**（2693/12000）。
5. **外推的边界**（粗估，仅供量级参考）：`max` 档在 29.6k 字符输入上用了 2693 tok 思考；
   若 reasoning 随输入规模近似线性增长，要吃掉 12000 预留需要约 **4.5 倍输入（≈130k 字符）**——
   远超单文件 review 的典型规模（本样本 382 行已触发 `calculate_review_output_budget` 的最高基础档 8192）。
   **真正会先出问题的是 `max_output` 小的模型**：stepfun/hunyuan 预设 4096 时"基础额度 + 预留"被封回 4096，
   即**实际预留为 0**（§9.2 有 wire 断言）——那里的风险是"档位生效但预留被吃掉"，与本样本无关。

### 10.5 收口：§6 / §9.4 未决项

| 原未决项 | 结论（2026-09-26 真机） |
|---|---|
| §6 #3 大 prompt × max 的预算边界未测 | **收口**：382 行 / 29.6k 字符 patch × max = 5139/20192 tok（余量 15053），未截断、未空答、JSON 可解析（§10.4） |
| §9.4 #1 第二步没有真机复跑 | **收口**：四档全部走产品入口（§10.2/§10.3），wire 形态与 §9.2 的离线断言表逐字一致 |
| §6 #4 单模型单端点单样本 | **部分收口**：仍是单模型（`deepseek-flash`）+ 官方端点；样本从"各 1 次"扩到"短四档 4 + 长四档 3 + 长 off 1"（§10.2/§10.3）。`deepseek-chat`、中转站、其它供应商仍未测 |
| §6 #7 `thinking: enabled` 不带 effort | **仍开放**：本次四档都带 effort，enabled-only（官方默认 high）未覆盖 |
| §6 #2 review 侧看不到思考文本 | **仍开放**：本次 `ProviderResponse.reasoning` 仍 **0/7 非空**（非流式路径不回填），只有 token 计数可用 |

### 10.6 探针缺陷与调用预算（诚实记录）

- **缺陷**：第一次运行（run3）的探针只包了 `AIClient._provider.chat`。开启档位时 `_review_request_provider`
  会**为本次请求新建一个 provider 副本**（`thinking` 走 extra_params 通道），副本上的 `chat` 不是被包住的那一个
  ——于是 run3 里 low/high/max 三档的 **response 侧（reasoning 字符/token、completion tokens、content 字符）
  全部记成 0**。修法：把拦截挪到**工厂层**（`install_chat_probe` 包 `ai_client.create_model_provider`），
  run4 三档全部采到（见 §10.2）。
- **代价与取舍**：run3 的 5 次调用里，第 6 次（长 diff × max）在修复前被**中止**（进程 kill，未产生任何数据）；
  修好后用 run4 的 3 次补齐。**完成调用合计 8 次**（= 任务预算 ≤8）；被中止的那次客户端中断、**是否计费未知**，
  按最坏情况记 9 次，如实列在本任务的预算风险里（不由文档口径消化）。
- 补测的取舍：四档整体挪到长 diff 上跑（`--scenario levels --prompt long`），既补齐 response 侧，
  又直接回答"长 prompt × max"的边界问题；短 diff 的 low/high/max 因此只留 wire + 产品侧结果（§10.3）。
- 复跑：`python scripts/verify_review_reasoning.py`（默认 7 次调用，四档在短 diff 上）；
  脚本内置硬预算 `CALL_BUDGET = 8`，超了直接拒绝跑（exit 2）。

### 10.7 推荐配置（**建议**，本任务不改任何产品代码）

1. **档位与默认值维持现状**：`review_reasoning_effort` 默认 `off`（§9 落地口径，本次真机确认 off 仍是"显式关闭 + 0 reasoning + 6144/8192 基础额度"）；
   要"深度审查"时 **`high` 是性价比拐点**：长 diff 上 high 的 reasoning 是 low 的 3.9 倍（1877 vs 476 tok），
   但 findings 从 3 涨到 5、completion 只涨 2.5 倍（3420 vs 1343）；`max` 再多 1.4 倍 reasoning / 1.5 倍 completion，
   findings 7。成本敏感选 `low/high`，质量优先才上 `max`。
2. **预算预留维持 +4000/+8000/+12000**：长 diff 上 max 只用了预留的 22.4%，**无需上调**；
   若将来要压成本，可考虑按输入规模缩放预留（如 `+min(12000, 输入字符数/4)`），但那是新需求，不是本次结论。
3. **唯一建议的加固（可选，另开任务）**：`max_output ≤ 8192` 的供应商在 `high/max` 档下预留会被封顶吃掉
   （stepfun/hunyuan 预设 4096 的极端情形 = **预留 0**，档位参数照发但额度没涨）。当前出口只在"整档送不出去"时置灰，
   建议给这类情形补一条"档位已生效、但预留被 `max_output` 吃掉"的提示文案（后端字段已具备，属前端/出口范围）。
