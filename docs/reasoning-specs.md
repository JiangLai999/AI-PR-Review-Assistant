# 供应商思考参数实现说明（reasoning specs）

日期：2026-09-26 · 任务：`claude-reasoning-specs-impl`（数据源任务：`opencode-reasoning-research`）
数据源：**`docs/reasoning-specs-research.md`**（19 家供应商官方文档调研，抓取日期 2026-09-26，
含来源 URL 与 confidence）· 实现：`src/ai_pr_review/services/reasoning_specs.py`

一句话：**"思考档位"不再对所有云端供应商统一发 `reasoning_effort`**——每家按官方文档的
参数形态映射（effort / budget / variant / switch），查不到官方参数的供应商**不注入 + `/think` 置灰**，
中转/自定义端点**透传**并如实提示"是否生效取决于上游"。

---

## 1. 落点

| 位置 | 职责 |
| --- | --- |
| `src/ai_pr_review/services/reasoning_specs.py` | **唯一数据源**：19 家 + 本地 `local` 的规格表、`build_reasoning_params()`、`reasoning_support()` |
| `src/ai_pr_review/config.py:CHAT_REASONING_TOKEN_BUDGETS` | 档位 → 思考 token 预算（`low 4000 / high 8000 / max 12000`），预留与预算型供应商共用一份数字 |
| `src/ai_pr_review/services/model_capabilities.py` | `ModelCapabilityProfile.reasoning_form` 属性转读规格表（审查链路可见同一份数据，不抄第二份） |
| `src/ai_pr_review/backend/jsonl_server.py` | `_chat` 注入（`_apply_reasoning_params`）、`/think` 三态（`_think_result`） |
| `tests/test_reasoning_specs.py` | 表驱动断言：19 家（+local）× 四档映射、unknown 兜底、Anthropic 预算约束、transparent 行为 |
| `tests/test_jsonl_backend.py` | 落地断言：wire 级注入（stub `urlopen` 读请求体）、`/think` 三态、置灰不写偏好 |

调研文档与旧代码不一致时**以调研文档为准**，差异见 §5。

---

## 2. 规格总表（实现口径）

`off/low/high/max` 是 UI 与配置里的统一四档；下表是每档**实际注入请求体**的参数
（`{}` = 该档不注入任何参数）。"依据 URL"与 confidence 原样取自调研文档。

| 供应商 | 形态 | off | low | high | max | 依据 URL | confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | budget | `thinking:{type:disabled}` | `thinking:{type:enabled,budget_tokens:4000}` | 同左 8000 | 同左 12000 | platform.claude.com/docs/en/build-with-claude/extended-thinking | documented |
| openai | effort | `reasoning_effort:none` | `low` | `high` | `max` | developers.openai.com/api/docs/guides/reasoning | documented |
| deepseek | switch | `thinking:{type:disabled}` | `thinking:{type:enabled}`+`reasoning_effort:low` | 同左 `high` | 同左 `max` | api-docs.deepseek.com/ | documented |
| qwen | switch | `enable_thinking:false` | `enable_thinking:true`+`thinking_budget:4000` | 同左 8000 | 同左 12000 | help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions | documented |
| zhipu | variant | `thinking:{type:disabled}` | `thinking:{type:enabled}`+`reasoning_effort:low` | 同左 `high` | 同左 `max` | docs.bigmodel.cn/cn/guide/start/concept-param | documented |
| moonshot | switch | `thinking:{type:disabled}` | `reasoning_effort:low` | `high` | `max` | platform.kimi.com/docs/guide/use-thinking-models | documented |
| minimax | variant | `thinking:{type:disabled}` | `thinking:{type:adaptive}` | 同左 | 同左 | platform.minimaxi.com/docs/api-reference/text-chat-openai | documented |
| doubao | switch | `thinking:{type:disabled}` | `reasoning_effort:low` | `high` | `max` | docs.volcengine.com/docs/82379/1449737 | documented |
| hunyuan | variant | **不注入**（官方未给关闭方式） | `reasoning_effort:low` | `high` | `high`（就近映射） | cloud.tencent.com/document/product/1729/111006 | documented |
| stepfun | effort | **不注入**（官方：off = 不传） | `reasoning_effort:low` | `high` | `high`（就近映射） | platform.stepfun.com/docs/zh/guides/developer/reasoning | documented |
| baichuan | unsupported | — | — | — | — | platform.baichuan-ai.com/docs | unsupported-by-model |
| yi | unsupported | — | — | — | — | platform.lingyiwanwu.com/docs | unsupported-by-model |
| openrouter | effort | `reasoning:{effort:none}` | `{effort:low}` | `{effort:high}` | `{effort:xhigh}` | openrouter.ai/docs/guides/reasoning-tokens | documented |
| siliconflow | switch | `enable_thinking:false` | `enable_thinking:true`+`thinking_budget:4000` | 同左 8000 | 同左 12000 | docs.siliconflow.cn/cn/userguide/capabilities/reasoning | documented |
| ollama | switch | **不注入**（产品决策置灰） | — | — | — | docs.ollama.com/capabilities/thinking | product-decision |
| local（不在预设表内） | switch | **不注入**（同上） | — | — | — | 同上 | product-decision |
| api2d | transparent | `reasoning_effort:none` | `low` | `high` | `max` | www.api2d.com/doc/doc | transparent |
| closeai | transparent | 同上 | 同上 | 同上 | 同上 | doc.closeai-asia.com/tutorial/api/openai.html | transparent |
| ohmygpt | transparent | 同上 | 同上 | 同上 | 同上 | docs.ohmygpt.com/docs/api | transparent |
| custom | transparent | 同上 | 同上 | 同上 | 同上 | （无官方文档，见 `config.PROVIDER_MODEL_PRESETS["custom"]`） | transparent |

供应商名的比对口径：小写 + 去空白。**未收录的名字**（含拼错、用户自建名）一律
`form="unknown"`、态 `unsupported`、不注入任何参数。

### 2.1 预算字段的官方约束（`_clamp_budget`）

- **Anthropic**（调研 §3.1 原句）：`budget_tokens` ≥ 1024 且 **< `max_tokens`**。
- **qwen**：`thinking_budget` 1–32768（本表只用 4000/8000/12000，远在区间内）。
- 收敛顺序：先夹官方区间（含 `< max_tokens`）→ 放不下则**整档不注入**（不发会被 400 拒收的值）
  → 再按"回答额度"软收敛（`min(档位预算, max_tokens - ai_client.max_tokens)`），
  软收敛会跌破官方下限时**以官方下限为准**（Anthropic 1024 / qwen 1）。
- `_chat` 调用时传入的是**最终的** `max_tokens`（已过 `_chat_max_tokens` 的规格封顶），
  所以 Anthropic 永远不会收到 `budget_tokens ≥ max_tokens`。

---

## 3. `/think` 三态

`/think`（不带参数 = 查询，带参数 = 设置）返回体在契约 v1 的 `kind`/`state`/`effort`
三键之外新增了 `form` / `doc_url` / `reason` / `model_caveat`（**新键只增不改**，
`effort` 键在任何态下都存在）；三态语义：

| state | 何时 | 行为 | 文案 |
| --- | --- | --- | --- |
| `set` | 官方参数形态明确（A/B 组里有参数的 11 家） | 写入 `preferences.chat_reasoning_effort` 并落盘 | "思考档位已设置为 {level}。" |
| `transparent` | C 组（api2d / closeai / ohmygpt / custom） | 同样写入并落盘 | "…（已按 OpenAI 兼容透传 reasoning_effort；是否生效取决于上游服务）。" |
| `unsupported` | 官方无该参数（baichuan / yi）、本地产品决策（ollama / local）、未收录 | **不写偏好**、不注入参数 | `reason` 给出原因，`doc_url` 给出官方依据 |

前端字段语义见 `frontend/tui/src/protocol.ts:parseThinkCommandResult`（读 `state`/`effort`，
`unsupported` 时优先显示 `reason`）——**未改前端**，`effort` 键保持存在（查询与置灰时回显当前值）。

> 已知前端缺口（本次不动前端）：TUI 只区分 `unsupported` 与"其它"，因此 `transparent`
> 态在界面上仍渲染成档位行（"思考档位：高"），"是否生效取决于上游"只在
> `result.text` / `result.reason` 里，等前端排期消费。

---

## 4. `_chat` 注入路径

1. **本地（ollama/local）先行短路**：产品决策置灰，不按档位映射，恒发
   `reasoning_effort: "none"` 快速模式兜底 + 预留 `high` 档思考量（思考型本地模型会吃满
   `max_tokens` 导致答案为空，见 `docs/model-reasoning-probe.md` R1–R3）。
2. **`auto` 不碰参数**（现状保持，任何供应商都不注入）。
3. 其余档位查表注入，拆到两条**既有**通道（不新增 provider 接口）：
   - `reasoning_effort` / `think` → `stream_chat(**kwargs)`（OpenAI 兼容 provider 的
     白名单键，`services/model_providers/openai.py:164`）；
   - 其余请求体顶层参数（`thinking` / `enable_thinking` / `thinking_budget` / `reasoning`）
     → **本次请求**的 provider 配置 `extra_params`（OpenAI 兼容 provider 的
     `{**self.config.extra_params}` 与 Anthropic provider 的
     `messages.create(**self.config.extra_params)` 都会并进请求体）。写的是
     `ProviderConfig.to_model_provider()` 每轮新建的临时对象，**不影响落盘配置**。
4. **预留只给真的会思考的供应商**：`CHAT_REASONING_TOKEN_BUDGETS[level]` 参与
   `_chat_max_tokens`（再受模型规格 `max_output` 封顶）；置灰的供应商不预留。

wire 级证据：`tests/test_jsonl_backend.py::test_chat_injects_deepseek_reasoning_params_at_the_wire`
（真 provider + stub `urlopen`，直接断言请求体里的 `thinking` / `reasoning_effort` / `max_tokens`）。

---

## 5. 与调研文档/旧代码的差异与取舍（如实记录）

1. **deepseek `max` 是兼容映射**：官方 effort 枚举为 low/medium/high，`max` 不在其中。
   保留是因为本机实测有单调性（`docs/reasoning-effort-probe.md`：disabled 0 < low 2624
   < high 4509 < max 6834）——属既有行为，不是按文档编造的新参数。
2. **qwen / siliconflow 走预算通道**：官方对 qwen 同时提供 `reasoning_effort` 与
   `thinking_budget`，但 qwen3.8 系**两者不可同传**（调研 §3.4）。四档统一用
   `thinking_budget` 表达，避免踩互斥；官方 effort 枚举（max→xhigh 等）记录在表里但不下发。
3. **hunyuan / stepfun 的 off 不注入**：两家官方都没有"关闭思考"的参数（stepfun 的官方口径
   就是 off = 不传），因此 off 档不发任何参数，而不是编一个 `thinking:disabled`。
   `max` 就近映射为 `high`（官方只有三档），未假装有独立 max。
4. **minimax 无档位**：开启态只有 `adaptive`（省略即默认），low/high/max 三档都映射到它；
   `disabled` 仅 M3 可关（M2.x 关不掉）。
5. **anthropic 只实现 extended thinking**：预设模型是 Claude 4.x（在支持范围内）。
   4.6 起 `thinking:{type:enabled,budget_tokens}` 弃用、4.7+ 会 400（调研 §3.1）——迁移目标是
   `thinking:{type:"adaptive"}` + `output_config:{effort}`，**待有 4.7+ 预设时再改**（未实现）。
6. **模型层面的差异不参与判定**：预设模型可能是非思考模型（`gpt-4o-mini` / `glm-4-*` /
   `moonshot-v1-*` / `hunyuan-turbos-latest` 等）。档位判定按**供应商**（官方文档口径），
   模型层面的提示放在 `model_caveat` 字段与调研文档里，**不假装模型也支持**。
7. **本地是产品决策不是端点限制**：ollama 官方 `think` 参数有文档（能力存在），
   置灰是 2026-09-26 用户裁定"本地不开放思考展示"；`reason` 文案与置灰行为保持改造前一致。
8. **未覆盖的边界（如实记录）**：C 组若把 `api_format` 设成 `anthropic`（自定义端点走
   Anthropic 协议），`reasoning_effort` 只会进 kwargs，而 Anthropic provider 不转发该键
   （它只发 `messages.create(**extra_params)` 里的参数）——此时"透传"实际不到达请求体。
   按调研口径 C 组不编造自有参数，故**不为其注入 Anthropic 风格 `thinking`**；如需支持，
   应先确认上游协议再单开任务（`/think` 已用 `transparent` + "取决于上游"如实提示，不谎报生效）。

---

## 6. 验证

```bash
# 表驱动：19 家（+local）× 四档、unknown 兜底、Anthropic 预算约束、transparent
python -m pytest -q --no-cov tests/test_reasoning_specs.py
# 落地：wire 级注入（stub urlopen 读请求体）+ /think 三态 + 置灰不写偏好
python -m pytest -q --no-cov tests/test_jsonl_backend.py
# 全量
python -m pytest -q --no-cov
```

本次交付的实测数字与命令见 `.agent-bus` 报告（`claude-reasoning-specs-impl`）；
`docs/verification-matrix.md` 的 C6 行已同步为"已按官方文档实现，数据源见本文档"。

**未做**（用户已明确"不做真机验证"）：没有对任何云端供应商发真实请求；
所有断言都是"表 + 请求体"级别的，官方文档与真实端点行为之间仍可能有落差
（例如中转站声称透传但实际改写参数）。
