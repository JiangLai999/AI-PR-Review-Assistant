# 思考（reasoning/thinking）参数规格调研

- 任务：`opencode-reasoning-research`
- 调研对象：`src/ai_pr_review/config.py` 中 `PROVIDER_MODEL_PRESETS` 的 **19 个**供应商 key
- 抓取/检索日期：**2026-09-26**
- 判定口径（见 §1），置信度口径：`documented`（官方文档原文可证）/ `unknown`（仅第三方来源或未能在官方文档定位）

---

## 1. 判定口径

| 分组 | 供应商 | 判定规则 |
| --- | --- | --- |
| A 组（12） | deepseek, openai, anthropic, qwen, zhipu, moonshot, minimax, doubao, hunyuan, stepfun, baichuan, yi | 官方文档给出思考参数 → `documented`；官方文档明确按模型区分/无该参数 → `unsupported-by-model`；只能找到第三方描述 → `unknown` |
| B 组（2） | openrouter, siliconflow | 聚合平台，优先按平台统一规范判定；平台规范优先于单一上游模型 |
| C 组（4） | api2d, closeai, ohmygpt, custom | 转售/中转/自定义端点，无自有思考参数 → `transparent`（透传上游） |
| D 组（1） | ollama | 本地推理，产品决策：**本地不开放思考展示** → `unsupported`（能力存在但产品不启用） |

参数形态取值：`effort`（档位字符串）| `budget`（token 预算整数）| `variant`（变体/模式开关）| `switch`（布尔开关）| `transparent`（透传上游）| `unsupported`（不支持）。
`local` **不在** `PROVIDER_MODEL_PRESETS` 中，故不计入 19 行总表，单列于 §6。

---

## 2. 总表（19 行）

| # | 供应商 | 参数形态 | off/low/high/max 档参数 | 附加约束 | 来源 URL | 抓取日期 | confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | anthropic | `budget` + `variant` | off=`thinking.type:"disabled"`（旧模型）；无 low/high/max 档；预算走 `budget_tokens`（整数） | `thinking:{type:"enabled", budget_tokens:N}`；N ≥ 1024 且 < `max_tokens`；4.6 起弃用、4.7+ 返回 400；4.7+ 改 `thinking:{type:"adaptive"}` + `output_config:{effort}` | https://platform.claude.com/docs/en/build-with-claude/extended-thinking | 2026-09-26 | documented |
| 2 | openai | `effort` | off=`none`；low=`low`；high=`high`；max=`max`（另有 `minimal`/`medium`/`xhigh`） | Responses 用 `reasoning.effort`，Chat 用 `reasoning_effort`；默认值随模型而变（gpt-5.5 默认 `medium`）；部分模型传 `none` 返回 400；**预设模型 gpt-4o-mini/gpt-4.1 非推理模型** | https://developers.openai.com/api/docs/guides/reasoning | 2026-09-26 | documented |
| 3 | ollama | `switch` + `effort` | off=`think:false`；low/medium/high=`"low"/"medium"/"high"`；max=`"max"` | `/api/chat`、`/api/generate` 的 `think` 字段，boolean 或 `"low"/"medium"/"high"/"max"`；GPT-OSS 只接受 low/medium/high；**产品决策：本地不开放思考展示 → 本项目判定 `unsupported`** | https://docs.ollama.com/capabilities/thinking | 2026-09-26 | documented |
| 4 | deepseek | `switch` + `effort` | off=`thinking.type:"disabled"`；effort=`"low"/"medium"/"high"`（官方示例用 `high`） | Chat Completion 顶层 `"thinking":{"type":"enabled"}` + `"reasoning_effort"`；`deepseek-chat`=非思考、`deepseek-reasoner`=思考（2026-07-24 弃用）；v4-flash/v4-pro 为混合思考模型 | http://api-docs.deepseek.com/ | 2026-09-26 | documented |
| 5 | qwen | `switch` + `budget` + `effort` | off=`enable_thinking:false`；high≈`reasoning_effort:"high"`；max≈`"xhigh"`（部分模型 `max`） | `enable_thinking`（bool，请求体顶层/SDK `extra_body`）；`thinking_budget`（1–32768，文档常用默认 4000）；`reasoning_effort` 与 `thinking_budget` 在 qwen3.8 系不可同传，按区间互映射（0–4096→low、4097–16384→medium、16385–262144→xhigh） | https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions | 2026-09-26 | documented |
| 6 | zhipu | `variant` + `effort` | off=`thinking.type:"disabled"`；GLM-5.3 系：`low`/`high`/`max`；GLM-5.2：`none`/`minimal`/`low`/`medium`/`high`/`xhigh`/`max` | `thinking:{type:"enabled"|"disabled"}`（默认 enabled）；`reasoning_effort` 仅 GLM-5.2+；GLM-5.3 传 `disabled` 报错；`low/medium`→`high`、`xhigh`→`max`；**预设模型 glm-4-flash/plus/air 为 GLM-4 系，官方标注 thinking 仅 GLM-4.5 及以上支持** | https://docs.bigmodel.cn/cn/guide/start/concept-param | 2026-09-26 | documented |
| 7 | moonshot | `switch` + `effort` | off=`thinking.type:"disabled"`（kimi-k2.6）；effort=`"low"/"high"/"max"`（kimi-k3，默认 `max`） | `kimi-k3`：顶层 `reasoning_effort`；`kimi-k2.7-code`：仅 `thinking.type:"enabled"` + `thinking.keep:"all"`；`kimi-k2.6`：`thinking.type` + `thinking.keep`；域名已迁移 platform.moonshot.cn → platform.kimi.com；**预设 moonshot-v1-* 为非思考旧模型** | https://platform.kimi.com/docs/guide/use-thinking-models | 2026-09-26 | documented |
| 8 | minimax | `variant` + `switch` | off=`thinking.type:"disabled"`（仅 M3；M2.x 无法关闭）；adaptive=`"adaptive"`（默认）；无 low/high/max 档 | OpenAI 兼容 `/v1/chat/completions` 的 `thinking:{type:"disabled"\|"adaptive"}`；省略默认 adaptive；另有 `reasoning_split`(bool) 仅拆分输出到 `reasoning_content`/`reasoning_details`，不开关思考；**预设 MiniMax-Text-01/abab6.5s-chat 不在 `thinking` 参数说明的 M3/M2.x 范围内** | https://platform.minimaxi.com/docs/api-reference/text-chat-openai | 2026-09-26 | documented |
| 9 | doubao | `switch` + `effort` | off=`thinking.type:"disabled"`；effort=`"low"/"medium"/"high"/"xhigh"/"max"`（默认 `medium`） | 设 `thinking.type:"disabled"` 时不可同时设 `reasoning_effort`；doubao-seed-1-6 支持 `thinking`/`non-thinking`/`auto`，思考内容上限 32k；官方页为 JS 渲染，证据取自官方域名索引片段 | https://docs.volcengine.com/docs/82379/1449737 | 2026-09-26 | documented |
| 10 | hunyuan | `variant` + `effort` | 无 off 档（Anthropic 兼容示例仅 `{"type":"enabled"}`）；OpenAI 兼容侧 `reasoning_effort: "low"/"medium"/"high"`（平台字段说明） | Anthropic 兼容端点 `https://api.hunyuan.cloud.tencent.com/anthropic/v1/messages` 支持 `thinking`；OpenAI 兼容端点 `…/v1/chat/completions` 无 `enable_thinking`，思考与否由模型名决定（`hunyuan-2.0-thinking-*` vs `hunyuan-2.0-instruct-*`）；TokenHub 的 OpenAI Chat 协议表含 `reasoning_effort`（low/medium/high，混元内部映射）；**预设 hunyuan-turbos-latest / hunyuan-large 为非思考模型** | https://cloud.tencent.com/document/product/1729/111006 | 2026-09-26 | documented |
| 11 | stepfun | `effort` | off=`reasoning_effort` 不传（按模型默认）；low=`"low"`；medium=`"medium"`（默认）；high=`"high"` | Chat Completion 用顶层 `reasoning_effort: low\|medium\|high`；Messages API 用 `output_config.effort`；**仅部分模型支持三档，预设 step-2-16k / step-1-256k 未在支持说明中列名** | https://platform.stepfun.com/docs/zh/guides/developer/reasoning | 2026-09-26 | documented |
| 12 | baichuan | `unsupported` | — | 官方文档中心仅含接入须知/接口文档/知识库等章节，通用大模型（Baichuan4 / Baichuan4-Turbo / Baichuan4-Air / Baichuan3-Turbo）接口参数未列任何 thinking/reasoning 参数；预设 Baichuan4、Baichuan3-Turbo 均为非思考模型 | https://platform.baichuan-ai.com/docs | 2026-09-26 | unsupported-by-model |
| 13 | yi | `unsupported` | — | 官方开放平台仅列 `Yi-Lightning`、`Yi-Vision-V2`，接口兼容 OpenAI 标准 Chat 参数，文档未见 thinking/reasoning 字段；预设 yi-lightning、yi-large 均为非思考模型 | https://platform.lingyiwanwu.com/docs | 2026-09-26 | unsupported-by-model |
| 14 | openrouter | `effort` + `budget` | off=`reasoning.effort:"none"`；low=`"low"`；high=`"high"`；max=`"xhigh"`（另有 `minimal`/`medium`） | 平台统一规范：`reasoning:{effort}` 或 `reasoning:{max_tokens:N}` 二选一；支持 `reasoning.exclude`、`reasoning.enabled`；响应含 `reasoning_details`；**预设 openai/gpt-4o-mini、anthropic/claude-3.5-sonnet 为非推理模型 → 该组模型 `unsupported-by-model`** | https://openrouter.ai/docs/guides/reasoning-tokens | 2026-09-26 | documented |
| 15 | siliconflow | `switch` + `budget` | off=`enable_thinking:false`；无 low/high/max 档（档位由 `thinking_budget` 数值表达） | OpenAI 兼容请求经 `extra_body` 传 `enable_thinking`(bool) + `thinking_budget`(int，思考链最大 token)；响应以 `reasoning_content` 与 `content` 同级返回；Qwen3 系到 `thinking_budget` 会强制停止思考，其他模型可能继续输出 | https://docs.siliconflow.cn/cn/userguide/capabilities/reasoning | 2026-09-26 | documented |
| 16 | api2d | `transparent` | —（跟随上游 OpenAI/Claude） | 官方文档：接口"与 OpenAI 官方严格一致"，仅转发，无自有思考参数定义；支持 `/v1/chat/completions`、`/claude/v1/messages` 等路径 | https://www.api2d.com/doc/doc | 2026-09-26 | transparent |
| 17 | closeai | `transparent` | —（跟随上游 OpenAI/Anthropic/Gemini） | 官方文档：参数与用法"全部同 OpenAI"；平台做 ChatCompletion↔Response/Anthropic/Gemini 协议转换，推理模型建议走 Responses 接口（Chat 上限 5 分钟、Responses 20 分钟） | https://doc.closeai-asia.com/tutorial/api/openai.html | 2026-09-26 | transparent |
| 18 | ohmygpt | `transparent` | —（跟随上游 OpenAI/Anthropic） | 官方文档：统一 OpenAI 兼容端点 `https://api.ohmygpt.com/v1`，仅路由转发；模型库条目直接沿用上游 effort 描述（如 gpt-5.4 "none to xhigh"） | https://docs.ohmygpt.com/docs/api | 2026-09-26 | transparent |
| 19 | custom | `transparent` | —（取决于用户自填 base_url 的上游） | 自定义端点，项目侧仅有 `custom-model` 占位预设；思考参数能力完全取决于所指上游服务 | （无官方文档，配置项定义见仓库 `config.py`） | 2026-09-26 | transparent |

---

## 3. A 组逐家细节（含官方原句摘录）

### 3.1 anthropic — `documented`

- 形态：`thinking:{type:"enabled", budget_tokens:N}`（manual / extended thinking）+ 新版 adaptive thinking。
- 原句（预算约束）：
  > "Minimum of 1,024 tokens. The API rejects smaller values."
  > "Less than max_tokens. Thinking tokens count toward the max_tokens limit for the turn, so the budget must leave room for the final response."
- 版本约束：
  > "Extended thinking (`thinking.type: "enabled"` with `budget_tokens`) is deprecated on Claude 4.6 models… Claude 4.7 and later models don't support it and reject requests that use it, returning a 400 error."
- 迁移目标：`thinking:{type:"adaptive"}` + `output_config:{effort: ...}`。
- 档位换算：官方未给 low/high/max 档位表，只有 token 预算；新版 effort 由 `output_config.effort` 承担。
- 与预设关系：预设 `claude-sonnet-4-20250514` / `claude-opus-4-20250514`（Claude 4.x）在 extended thinking 支持范围内。
- 来源：https://platform.claude.com/docs/en/build-with-claude/extended-thinking 、https://docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking

### 3.2 openai — `documented`（预设模型 `unsupported-by-model`）

- 形态：`reasoning.effort`（Responses API）/ `reasoning_effort`（Chat Completions）。
- 原句：
  > "Supported values are model-dependent and can include none, minimal, low, medium, high, xhigh, and max."
  > "Defaults are also model-dependent rather than universal. gpt-5.5 defaults to medium reasoning effort."
  > "Setting `reasoning.effort` (Responses) or `reasoning_effort` (Chat Completions) to `none` returns HTTP 400."（对不支持 none 的模型，如 GPT-6 Astra）
- 预设约束：`gpt-4o-mini`、`gpt-4.1` 非推理模型，不接受思考档位（传入会被上游忽略或报 unknown parameter）。
- 来源：https://developers.openai.com/api/docs/guides/reasoning

### 3.3 deepseek — `documented`

- 形态：布尔式思考开关 + effort 字符串。
- 原句（官方接口文档示例）：
  > `"thinking": {"type": "enabled"}` 与 `"reasoning_effort": "high"` 同时出现在 create-chat-completion 示例中。
- 模型约束：`deepseek-chat`（非思考）、`deepseek-reasoner`（思考，2026/07/24 弃用）；v4-flash / v4-pro 为混合思考模型，可按请求开关。
- 来源：https://api-docs.deepseek.com/zh-cn/api/create-chat-completion 、http://api-docs.deepseek.com/

### 3.4 qwen（阿里云百炼 / DashScope）— `documented`

- 形态：布尔开关 + token 预算 + effort 三者并存。
- 关键参数：
  - `enable_thinking`（bool，请求体顶层；OpenAI SDK 走 `extra_body`）
  - `thinking_budget`（int，思考 token 上限，1–32768，文档常用默认 4000）
  - `reasoning_effort`（string，模型相关）
- 原句：
  > "Simply place enable_thinking at the top level of the request body (body), alongside parameters such as model and messages, for example `"enable_thinking": true`."
  > "The MiniMax and MiniMax-M3 models from Xiyu Technology do not use this parameter. Instead, use the thinking parameter."
  > "For the qwen3.8 series, reasoning_effort and thinking_budget cannot be set at the same time."
  > "0–4096 corresponds to low, 4097–16384 corresponds to medium, and 16385–262144 corresponds to xhigh."
- 映射：OpenAI 标准值映射 `max`→`xhigh`、`high`→`xhigh`、`minimal`→`low`、`none`→`enable_thinking=False`。
- 来源：https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions 、https://help.aliyun.com/zh/model-studio/deep-thinking 、https://help.aliyun.com/zh/model-studio/batch-inference

### 3.5 zhipu（智谱 / GLM）— `documented`

- 形态：`thinking.type` 开关 + `reasoning_effort` 档位。
- 原句：
  > "thinking … 是否开启思维链深度思考，仅 GLM-4.5 及以上支持。"（默认 `{"type":"enabled"}`）
  > "reasoning_effort … 仅 GLM-5.2 及以上支持。参数支持：max high low（max 为默认值）"
  > "GLM-5.2 模型支持 max xhigh high medium low minimal none，传入 none 或 minimal 模型会放弃思考；传入 low medium 将映射为 high；传入 xhigh 将映射为 max。"
  > "GLM-5.3 / GLM-5.3-FLASH 模型仅支持 max high low。"
- 预设约束：`glm-4-flash` / `glm-4-plus` / `glm-4-air` 低于 GLM-4.5，按官方说明不支持 `thinking` → 这三个预设模型本身 `unsupported-by-model`（供应商参数仍 `documented`）。
- 来源：https://docs.bigmodel.cn/cn/guide/start/concept-param 、https://docs.bigmodel.cn/cn/guide/capabilities/thinking

### 3.6 moonshot（Kimi）— `documented`

- 形态：因模型而异的三套参数。
  - `kimi-k3`：顶层 `reasoning_effort: "low"|"high"|"max"`（默认 `max`）
  - `kimi-k2.7-code`：`thinking.type:"enabled"`（`disabled` 报错）+ `thinking.keep:"all"`
  - `kimi-k2.6`：`thinking.type`（enabled 默认 / disabled）+ `thinking.keep`（null / "all"）
- 来源：https://platform.kimi.com/docs/guide/use-thinking-models （旧域名 platform.moonshot.cn 有 `llms.txt` 指向新域名）
- 预设约束：`moonshot-v1-8k/32k/128k`、`kimi-k2-0711-preview` 为非思考/旧版模型，未出现在思考参数说明的适用模型列表中。

### 3.7 minimax — `documented`

- 形态：`thinking.type` 变体开关（无档位）。
- 原句（OpenAPI schema）：
  > "控制 MiniMax-M3 thinking。省略时默认开启 adaptive thinking，响应会包含 thinking 内容。对于 M2.x 模型，thinking 无法关闭。"
  > `type` enum：`disabled` / `adaptive`，默认 `adaptive`。
  > "reasoning_split：启用后将 thinking 内容拆分到 `reasoning_content` 和 `reasoning_details` 字段。这不会开启或关闭 thinking。"
- 预设约束：`MiniMax-Text-01`、`abab6.5s-chat` 不在 `thinking` 参数所覆盖的 M3/M2.x 列表内。
- 来源：https://platform.minimaxi.com/docs/api-reference/text-chat-openai 、https://platform.minimaxi.com/docs/api-reference/text-post

### 3.8 doubao（火山方舟）— `documented`（官方页 JS 渲染，取官方域名索引片段）

- 形态：`thinking.type` 开关 + `reasoning_effort` 档位。
- 要点：
  - `thinking.type:"disabled"` 关闭思考；设置 disabled 时不能同时设 `reasoning_effort`
  - `reasoning_effort` 取值 `low/medium/high/xhigh/max`，默认 `medium`
  - `doubao-seed-1-6` 支持 `thinking` / `non-thinking` / `auto`，最大思考内容 32k
- 来源：https://docs.volcengine.com/docs/82379/1449737 （页面需 JS 渲染，直接抓取返回 "You need to enable JavaScript"，内容经官方域名检索片段获取）

### 3.9 hunyuan（腾讯混元）— `documented`

- 三条接入路径的差异：
  1. **Anthropic 兼容**：`https://api.hunyuan.cloud.tencent.com/anthropic/v1/messages`，示例即 `thinking = {"type": "enabled"}`（支持模型 `hunyuan-2.0-thinking-20251109` / `hunyuan-2.0-instruct-20251111`）。
  2. **OpenAI 兼容**：`https://api.hunyuan.cloud.tencent.com/v1/chat/completions`，官方调用示例未见 `enable_thinking`/`thinking`，思考与否由模型名区分；`extra_body` 示例仅出现 `enable_enhancement`。
  3. **TokenHub 平台协议**：OpenAI Chat Completions 协议字段表含 `reasoning_effort`（`"low"/"medium"/"high"`，说明"推理深度，适用于思考类模型。混元模型有内部映射转换"）。
- 预设约束：`hunyuan-turbos-latest`、`hunyuan-large` 为非思考模型。
- 来源：https://cloud.tencent.com/document/product/1729/111006 、https://cloud.tencent.com/document/product/1729/111007 、https://www.tencentcloud.com/zh/document/product/1300/82345

### 3.10 stepfun（阶跃星辰）— `documented`

- 形态：`reasoning_effort` 三档字符串。
- 原句：
  > Chat Completion：`reasoning_effort`，取值 `low / medium / high`，`medium` 为默认值。
  > Messages API：使用 `output_config.effort`。
  > "仅三档模型支持"。
- 预设约束：`step-2-16k`、`step-1-256k` 未在支持说明中列名 → 这两个预设模型按 `unsupported-by-model` 处理。
- 来源：https://platform.stepfun.com/docs/zh/guides/developer/reasoning

### 3.11 baichuan（百川智能）— `unsupported-by-model`

- 官方文档中心（`platform.baichuan-ai.com/docs`）章节为：接入须知 / 接口文档 / 医疗大模型 / 通用大模型 / 知识库 / 向量化模型 / 文件管理 / 错误码 / 财务相关 / 发票 / MCP，接口参数未见 thinking/reasoning 字段。
- 通用模型线 Baichuan4 / Baichuan4-Turbo / Baichuan4-Air / Baichuan3-Turbo 定位为企业高可用非思考模型（官方强调首 token 响应速度、token 流速，未宣传思维链）。
- 注意：医疗线 Baichuan-M2 官方描述含"推理模型"字样，但属另一模型族且不在本项目预设内。
- 来源：https://platform.baichuan-ai.com/docs 、https://baichuan-ai.com/home

### 3.12 yi（零一万物）— `unsupported-by-model`

- 官方开放平台模型列表仅 `Yi-Lightning`、`Yi-Vision-V2`；接口"兼容 OpenAI API"，文档未定义 thinking/reasoning 参数。
- 预设 `yi-lightning`、`yi-large` 均非思考模型。
- 来源：https://platform.lingyiwanwu.com/docs 、http://platform.lingyiwanwu.com/

---

## 4. B 组（聚合平台）

### 4.1 openrouter — `documented`（平台统一规范）

- 原句：
  > `reasoning: { effort: "high" }` 或 `reasoning: { max_tokens: 2000 }`（二选一）
  > effort 取值：`xhigh | high | medium | low | minimal | none`
  > 另支持 `reasoning.exclude`、`reasoning.enabled`；响应返回 `reasoning_details`
- 预设约束：`openai/gpt-4o-mini`、`anthropic/claude-3.5-sonnet` 上游非推理模型，实际请求 `unsupported-by-model`。
- 来源：https://openrouter.ai/docs/guides/reasoning-tokens

### 4.2 siliconflow（硅基流动）— `documented`

- 原句：
  > "Maximum Chain-of-Thought Length (thinking_budget): The number of tokens the model uses for internal reasoning."
  > OpenAI 示例：`extra_body={"enable_thinking": true, "thinking_budget": 1024}`
  > "If the number of tokens generated during the 'thinking phase' reaches the thinking_budget, the Qwen3 series reasoning model, which natively supports this parameter, will forcibly stop the chain-of-thought reasoning. Other reasoning models might continue to output the thinking content."
  > 返回参数：`reasoning_content` 与 `content` 同级。
- 预设约束：`deepseek-ai/DeepSeek-V3`（非思考）、`DeepSeek-R1`（恒定思考、无开关）、两个 Qwen3-Instruct 模型（`enable_thinking` 可用）。
- 来源：https://docs.siliconflow.cn/cn/userguide/capabilities/reasoning

---

## 5. C 组（中转 / 自定义）

| 供应商 | 官方口径 | 来源 |
| --- | --- | --- |
| api2d | "API2D 的接口和 OpenAI 官方严格一致，所以并不直接支持额外功能"；支持 `/v1/chat/completions`、`/claude/v1/messages` 等转发 | https://www.api2d.com/doc/doc 、https://api2d.com/doc |
| closeai | "参数与使用方式全部同 OpenAI"；平台做 ChatCompletion↔Response / Anthropic / Gemini 协议转换；推理模型建议改用 Responses 接口 | https://doc.closeai-asia.com/tutorial/api/openai.html 、https://doc.closeai-asia.com/ |
| ohmygpt | 统一 OpenAI 兼容端点路由（`https://api.ohmygpt.com/v1` + `/messages` Anthropic 端点）；模型库直接沿用上游 effort 描述（如 "configurable reasoning effort (none to xhigh)"） | https://docs.ohmygpt.com/docs/api 、https://www.ohmygpt.com/models |
| custom | 自定义 base_url，能力完全取决于上游；项目仅提供 `custom-model` 占位预设 | 仓库 `config.py`（`PROVIDER_MODEL_PRESETS["custom"]`） |

判定：四者均为 `transparent`，不自定义思考参数语义；实际能力随上游模型。

---

## 6. D 组（本地）与未收录项

### 6.1 ollama — API `documented`，产品判定 `unsupported`

- 官方 API：
  > `think`：boolean 或 `"low" / "medium" / "high" / "max"`（"with `max` requesting the highest thinking level"）
  > 响应 `message.thinking` 承载思考轨迹。
- 官方能力页（https://docs.ollama.com/capabilities/thinking）：
  > "Most models accept booleans (true / false) or levels (low, medium, high, max)… GPT-OSS instead expects one of low, medium, or high."
- 本项目产品决策：**本地不开放思考展示 → 记为 `unsupported`**（能力存在，产品层不启用）。
- 预设模型：`qwen3.5:4b`、`qwen3:4b`（思考能力可用）、`phi4-mini`、`gemma3:4b`、`qwen2.5-coder:3b`。
- 来源：https://docs.ollama.com/capabilities/thinking 、https://docs.ollama.com/api/chat 、https://github.com/ollama/ollama/blob/main/docs/api.md

### 6.2 `local` — 未收录

- `local` **不在** `PROVIDER_MODEL_PRESETS` 的 19 个 key 中（仅在 `ModelProviderConfig.validate()` 的本地回环地址白名单与 `jsonl_server.py` 相关逻辑中作为名字出现），故不计入总表。
- 如后续纳入，判定口径与 `ollama` 相同：`unsupported`（产品决策）。

---

## 7. 未收录 / 未取证清单（如实记录）

| 项 | 情况 | 影响 |
| --- | --- | --- |
| `platform.openai.com` / `developers.openai.com` 直接抓取 | HTTP 403（部分路径可抓，`/api/docs/guides/reasoning` 经检索片段取证） | openai 行 confidence 仍为 documented（官方域名原文片段） |
| `docs.claude.com` / `docs.anthropic.com` 直接抓取 | 返回地域屏蔽页 | anthropic 行改用 `platform.claude.com` 官方域名，仍为 documented |
| `docs.volcengine.com/docs/82379/1449737` | JS 渲染，需启用 JavaScript | doubao 行证据来自官方域名索引片段，标注取证方式 |
| `help.aliyun.com/zh/model-studio/thinking` | 404 | 改用 `qwen-api-via-openai-chat-completions`、`deep-thinking`、`batch-inference` 三页取证 |
| `openrouter.ai/docs/features/reasoning` | 404 | 改用 `/docs/guides/reasoning-tokens` |
| `docs.ollama.com/thinking` | 404 | 改用 `/capabilities/thinking` |
| baichuan 思考参数 | 官方文档无该参数 | 判 `unsupported-by-model`，非 `unknown`（官方文档全量章节可见且无此参数） |
| yi 思考参数 | 官方平台仅两个模型、无该参数 | 判 `unsupported-by-model` |
| api2d / closeai / ohmygpt 自有思考参数 | 官方文档均声明与上游一致，未定义自有参数 | 判 `transparent`；已记录检索到的官方文档 URL |
| 第三方聚合类文档（如 aihubmix 统一推理参数、AI SDK reasoning） | 仅作交叉印证，不作为判定依据 | 未用于任何行的 confidence=documented |

---

## 8. 过程摘要（访问/检索到的官方来源，URL 去重，抓取日期均为 2026-09-26）

**A 组**

1. https://api-docs.deepseek.com/zh-cn/api/create-chat-completion
2. http://api-docs.deepseek.com/
3. https://developers.openai.com/api/docs/guides/reasoning
4. https://platform.openai.com/docs/guides/reasoning
5. https://platform.claude.com/docs/en/build-with-claude/extended-thinking
6. https://docs.anthropic.com/en/docs/build-with-claude/adaptive-thinking
7. https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions
8. https://help.aliyun.com/zh/model-studio/deep-thinking
9. https://help.aliyun.com/zh/model-studio/batch-inference
10. https://docs.bigmodel.cn/cn/guide/start/concept-param
11. https://docs.bigmodel.cn/cn/guide/capabilities/thinking
12. https://platform.kimi.com/docs/guide/use-thinking-models
13. https://platform.minimaxi.com/docs/api-reference/text-chat-openai
14. https://platform.minimaxi.com/docs/api-reference/text-post
15. https://platform.minimaxi.com/docs/llms.txt
16. https://docs.volcengine.com/docs/82379/1449737
17. https://cloud.tencent.com/document/product/1729/111006
18. https://cloud.tencent.com/document/product/1729/111007
19. https://cloud.tencent.com/document/api/1729/105701
20. https://www.tencentcloud.com/zh/document/product/1300/82345
21. https://platform.stepfun.com/docs/zh/guides/developer/reasoning
22. https://platform.baichuan-ai.com/docs
23. https://baichuan-ai.com/home
24. https://platform.lingyiwanwu.com/docs
25. http://platform.lingyiwanwu.com/

**B 组**

26. https://openrouter.ai/docs/guides/reasoning-tokens
27. https://docs.siliconflow.cn/cn/userguide/capabilities/reasoning

**C 组**

28. https://www.api2d.com/doc/doc
29. https://api2d.com/doc
30. https://doc.closeai-asia.com/tutorial/api/openai.html
31. https://doc.closeai-asia.com/
32. https://docs.ohmygpt.com/docs/api
33. https://www.ohmygpt.com/models

**D 组**

34. https://docs.ollama.com/capabilities/thinking
35. https://docs.ollama.com/api/chat
36. https://github.com/ollama/ollama/blob/main/docs/api.md

**仓库内依据**

37. `src/ai_pr_review/config.py:355` — `PROVIDER_MODEL_PRESETS`（19 个 key 与预设模型清单）

---

## 9. 验证自查

- [x] 总表 **19 行**，与 `PROVIDER_MODEL_PRESETS` 的 19 个 key 一一对应（anthropic、openai、ollama、deepseek、qwen、siliconflow、moonshot、zhipu、baichuan、minimax、stepfun、doubao、hunyuan、yi、openrouter、api2d、closeai、ohmygpt、custom）。
- [x] 每行 `confidence=documented` 或 `transparent` 均给出可点击官方 URL（custom 除外，已注明"无官方文档"并指向仓库定义）。
- [x] `unsupported-by-model` 行（baichuan、yi）给出官方文档来源，说明"官方文档可见且无该参数"。
- [x] `local` 未计入 19 行，在 §6.2 单列说明。
- [x] 未收录项（OpenAI/Anthropic/火山方舟抓取受限、404 路径、第三方文档）在 §7 如实记录。
- [x] 所有证据抓取日期统一为 2026-09-26。
- [x] 只写入本文件 `docs/reasoning-specs-research.md`，未改动代码、未做 git 操作、未访问凭据。
