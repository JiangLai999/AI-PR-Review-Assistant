# review 链路思考档位评估（真机验证 + 建议）

> 任务：`.agent-bus/tasks/claude-review-reasoning-assess.json`（agent `claude`）· 日期：2026-09-26
> 脚本：`scripts/verify_review_reasoning.py`（可复跑）· 端点：DeepSeek 官方 `deepseek-flash`
> 密钥：只从 `DEEPSEEK_API_KEY` 环境变量读取，**从不打印、不落盘**；除 DeepSeek 端点外无任何网络请求。
> 关联：`docs/verification-matrix.md`（Live-review-think 行）· `docs/reasoning-effort-probe.md`（裸 API 四档）· `docs/chat-deepseek-live-verification.md`（chat 侧四档）· `docs/claude-backend-followup.md` §2.5

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
| 3 | 大 prompt × max 档的预算边界未测 | 本次最小 diff（prompt 4.6k 字符）reasoning 仅 3688 字符；长 diff 下 max 档可能顶到 6144/12288 上限 |
| 4 | 单模型单端点单样本 | 只有 `deepseek-flash`（官方端点）各 1 次；`deepseek-chat`、中转站（custom 端点）、其它供应商未测；裸 API 的单调性由 `docs/reasoning-effort-probe.md`（每档 3 次）背书 |
| 5 | `patch_generator` 路径未真机验证 | §1.2：`structured_output=False` ⇒ 对 DeepSeek 是"思考默认开启"，仅代码推断 |
| 6 | 本任务未提交 | 任务约束禁止 git 操作；证据为工作区文件 `scripts/verify_review_reasoning.py`、本文件、`docs/verification-matrix.md`（Live-review-think 行 + §2 #1 两行）、`.pytest_claude/review-reasoning-run{1,2}.utf8.log` |
| 7 | `thinking: enabled` 不带 effort 的情形未测 | 真机只测了 enabled+low / enabled+max 两个组合；按官方文档缺省应为 `high`，未实测（§0.2 的措辞已按此收窄） |
| 8 | 混合编排（CLI 默认路径）未单独真机验证 | `hybrid_orchestrator.py:371-377` 同样调 `review_code`，但会按文件重建 provider 配置、可能把低复杂度文件路由到本地模型；本次真机只覆盖 `AIClient` + `review_orchestrator` 的等价调用参数（kwargs 完全一致，因为都是 `review_code`），路由差异未测 |
| 9 | 非 deepseek 供应商的 review 思考行为未测 | §1.1 末表是按 `structured_review_params` 的离线结果推的；"兼容供应商 = 供应商默认（思考型即开启）"只有代码推断 |

---

## 7. 复跑指引

```powershell
# 密钥只从环境变量读，勿写进命令行/文档
$env:TEMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_claude'
$env:TMP=$env:TEMP
$env:PYTHONIOENCODING='utf-8'   # 中文输出重定向到文件时避免 cp936 乱码
python scripts/verify_review_reasoning.py            # 4 次调用，打印表格 + 断言
python scripts/verify_review_reasoning.py --json     # 机器可读
python scripts/verify_review_reasoning.py --model deepseek-chat   # 换模型
```

退出码：`0` 门禁全过；`1` 有门禁断言失败；`2` 环境不可用（无密钥 / 认证失败 / 四场景全部失败）。
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
