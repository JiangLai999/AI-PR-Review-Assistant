# 模型能力信息源评估（能否省掉实测）

日期：2026-09-26 · 脚本：`_p5_verify/p6proto/probe_model_metadata_sources.py`、
`probe_models_dev_reasoning_options.py`

## 结论

**能省掉大部分实测，但不能完全免除。** 推荐流程：

```
① models.dev 拉能力表（自动、免费、覆盖 223 个供应商 / 5000+ 模型）
        ↓ 拿到：reasoning_options（参数类型 + 取值）、limit（上下文/输出）、价格
② 官方文档校验关键供应商（如 DeepSeek 的 thinking_mode 映射表）
        ↓ 权威，但需逐个查
③ 实测只在两种场合做：
   · 两个来源冲突时（MiMo 就是例子）
   · 某供应商上线前的抽验（确认信息与真实行为一致）
```

## 三个信息源的实测对比

### 1. models.dev ⭐ 首选

`https://models.dev/api.json` —— MiMo-Code 自己也在用它（其日志里有 `service=models.dev`）。

**模型级字段**（关键的两个）：

```json
"reasoning": true,
"reasoning_options": [
  {"type": "toggle"},
  {"type": "effort", "values": ["low", "high", "max"]}
],
"limit": {"context": 1000000, "output": 393216}
```

`reasoning_options` 的 `type` 正是三套参数模型：**`toggle`（开关）/ `effort`（档位）/
`budget_tokens`（预算，带 `min`）**，且 `effort` 直接给出取值列表。

**覆盖**：223 个 provider、5452 个 `reasoning=true` 的模型。

**它同时解决了另一个需求**：`limit.context` / `limit.output` 正是"模型规格进配置助手"
（方案 B1）所需的默认值。

### 2. OpenRouter /api/v1/models

每个模型带 `supported_parameters`，例如：

```json
["frequency_penalty", "include_reasoning", "max_tokens", "reasoning",
 "reasoning_effort", "structured_outputs", "temperature", "tools", "top_p"]
```

326 个模型带 `reasoning_effort`。**能回答"支持哪个参数名"，但不给取值。**
适合作交叉验证（尤其是 OpenAI 兼容生态）。

### 3. LiteLLM model_prices_and_context_window.json

1855 个条目带 `supports_reasoning`（其中 1683 为 true），个别条目还有
`output_cost_per_reasoning_token`。**只有布尔**，粒度最粗，但价格信息全。

## 已验证的一致性

DeepSeek 在 models.dev 里的描述与本机实测**完全吻合**：

| 来源 | `effort` 取值 | 开关 | 结论 |
|---|---|---|---|
| models.dev | `low/high/max` | `toggle` | — |
| 官方文档（guides/thinking_mode） | `low/high/max`（+ 兼容映射 minimal/medium/…） | `thinking.enabled/disabled` | — |
| **本机实测** | disabled(0) < low(2.6k) < high(4.5k) < max(6.8k) | 关闭后 reasoning=0 | **三者一致** ✅ |

## 已知的信息源局限（所以仍要抽验）

| 局限 | 实例 |
|---|---|
| **可能与 CLI/上层不一致** | models.dev 说 `mimo-v2.6-pro` 只有 `toggle`，而 MiMo **CLI** 提供 `--variant high\|max\|minimal` |
| **不区分端点** | models.dev 不含"同一参数在不同端点是否生效"的信息（Ollama 的 `think` 在原生端点有效、在 OpenAI 兼容端点被忽略） |
| **可能滞后** | 新模型/新参数上线后需要时间同步（`last_updated` 字段可用于判断新鲜度） |

## 落地方式（写入方案 B2）

```text
同步源优先级：models.dev（主） → OpenRouter（交叉） → 官方文档（校验）
缓存：按 provider + 小时级 TTL
冲突处理：不自动二选一，标记 needs_verification，在配置助手提示用户，
         并提供探测脚本一键实测（probe_reasoning_effort.py 可直接复用）
拿不到即如实标注 unknown：绝不套用别家的取值
```

**收益**：

1. "思考档位"不再需要为每个供应商预先实测——**从能力表直接生成 UI**（只暴露该模型真实支持的档位）；
2. 上下文长度 / 最大输出**自动带默认值**（B1），用户可覆盖（B3）；
3. 实测从"每个供应商都要做"降级为"**冲突时 + 上线前抽验**"。
