# 各供应商"思考强度"能力对照矩阵

日期：2026-09-26 · 依据：官方文档 + 本机实测（脚本见 `_p5_verify/p6proto/`）

> **状态（2026-09-26 更新）**：本文档 §"统一设计"起曾被当作**设计稿**；
> 现在**已按官方文档实现**——19 家供应商的参数形态、四档映射、来源 URL 与 confidence
> 见 **`docs/reasoning-specs-research.md`**（调研）与 **`docs/reasoning-specs.md`**（实现口径），
> 代码落点 `src/ai_pr_review/services/reasoning_specs.py`。两处不一致时以后者为准：
> 下表的 "MiMo" 不在 `PROVIDER_MODEL_PRESETS` 的 19 家里，OpenAI/Anthropic 的档位与
> 预算取值也以实现文档的总表为准。

## 一句话结论

**不是一个道理**。各家的思考控制分成**四种参数模型**，且**同一家里不同模型也可能不同**：

| 参数模型 | 代表 | 形态 |
|---|---|---|
| **枚举档位** | DeepSeek、OpenAI 推理系 | `reasoning_effort: low/high/max`（取值**各家不同**） |
| **思考预算** | Anthropic | `thinking: {type: enabled, budget_tokens: N}` |
| **变体名** | MiMo | `variant: minimal/high/max` |
| **开关** | Ollama（原生） | `think: true/false` |

再叠加两个坑：**① 参数在不同端点效果不同**（Ollama 的 OpenAI 兼容端点忽略 `think`）；
**② 同一供应商里非推理模型根本不支持**（`deepseek-chat` 无思考，`deepseek-flash`/`reasoner` 有）。

## 实测/文档对照表

| 供应商 | 参数与取值 | 证据来源 | 状态 |
|---|---|---|---|
| **DeepSeek**（flash / reasoner） | `reasoning_effort: low\|high\|max`（默认 high）<br>`thinking: {type: enabled\|disabled}` | 官方 guides/thinking_mode + **本机实测**：disabled(0) < low(2.6k) < high(4.5k) < max(6.8k) | ✅ **已验证** |
| **DeepSeek**（chat 等非推理） | 无 | 实测：`reasoning_len=0` | ❌ 不支持 |
| **Ollama（本机 qwen3.5:4b）· 原生 `/api/chat`** | `think: true\|false` | **本机实测**：`think=false` 时 thinking 12,159→0 字符、耗时 78s→2.2s | ✅ 原生有效 |
| **Ollama · OpenAI 兼容端点（我们当前路径）** | 忽略 `think` 与 `reasoning_effort` | **本机实测**：两种取值下 reasoning 均 ~1.8k，无差异 | ❌ **当前路径不可用** |
| **OpenAI 推理系**（o 系列等） | `reasoning_effort: low\|medium\|high`（**多一个 medium**） | 官方文档 | ⚠️ 待实测（需 key） |
| **Anthropic**（Claude） | `thinking: {type: enabled, budget_tokens: N}`（预算制，非档位） | 官方文档 | ⚠️ 待实测（需 key） |
| **MiMo** | `variant: minimal\|high\|max` | 官方 CLI 帮助（`--variant`） | ⚠️ 待实测 |
| **第三方中转站** | 取决于上游；可能透传、可能忽略 | 不可知 | ❌ 默认按"不支持"处理 |

## 统一设计：UI 四档 → 各供应商映射（**已实现**，数据源见 `docs/reasoning-specs.md`）

UI 与配置只暴露**统一四档** `off / low / high / max`，由后端按 provider 映射
（实现：`services/reasoning_specs.py:build_reasoning_params()`；下表是设计期草表，
19 家的最终口径见 `docs/reasoning-specs.md` §2）：

| 统一档位 | DeepSeek | OpenAI 推理系 | Anthropic | MiMo | Ollama(原生) | 其它/未知 |
|---|---|---|---|---|---|---|
| `off` | `thinking: disabled` | — | `thinking: disabled` | — | `think: false` | 置灰 |
| `low` | `reasoning_effort: low` | `low` | `budget_tokens: 2000` | `variant: minimal` | — | 置灰 |
| `high`（默认） | `reasoning_effort: high` | `medium` | `budget_tokens: 16000` | `variant: high` | `think: true` | 置灰 |
| `max` | `reasoning_effort: max` | `high` | `budget_tokens: 64000` | `variant: max` | — | 置灰 |

**映射原则**：档位数少于四档的供应商，就近映射（如 OpenAI 无 `max` → 用 `high`），
并在 UI 上**如实显示"该模型最高 high"**，不假装有 max。

## 两条硬性实现要求

### 1. 必须预留思考预算（本机 Ollama 与 DeepSeek 都踩到了）

| 供应商 | 现象 |
|---|---|
| DeepSeek（`max_tokens=2000`, `effort=max`） | completion 顶满 2000，**答案 0~142 字符** |
| Ollama（OpenAI 端点, `max_tokens=600`） | reasoning ~1.8k，**答案恒为 0** |

→ `max_tokens = answer_budget + reasoning_budget(effort)`；
关掉思考时（`off`）不预留。

### 2. "能设"≠"有效"，必须实测后才开放

| 反例 | 说明 |
|---|---|
| Ollama 的 OpenAI 兼容端点 | 参数**被收下但忽略**（不报错） |
| DeepSeek 的 `minimal` / `medium` / `xhigh` / `ultra` | 属**兼容映射**（minimal→low），不是独立档位 |

→ 每个 provider/模型组合在开放档位前，必须跑同款实测：
**对照组（off vs on）+ 足够预算 + 每档 ≥3 次 + 单调性检查**。
现成脚本：`probe_reasoning_effort.py`（DeepSeek 版）、`probe_ollama_reasoning.py`（Ollama 版）。

> **实现口径（2026-09-26）**：用户明确"不用真机测试"后，本次按**官方文档**落地映射
> （数据源 `docs/reasoning-specs-research.md`），因此"有效性"标注的是**文档级**证据：
> - `documented`：官方文档写明参数（仍可能有版本/模型差异，逐条记在 `model_caveat`）；
> - `transparent`：C 组中转端点无自有参数，透传 `reasoning_effort`，`/think` 明确提示
>   "是否生效取决于上游"；
> - 未收录/官方无该参数：**不注入**并置灰，不编造。
> 真机复测清单与脚本仍建议在放开新供应商前跑一遍（尤其 qwen/zhipu 需按模型族取样）。

## 附：本机 Ollama 的额外结论

- `qwen3.5:4b` **确实是推理模型**（原生端点一次输出 12k 字符 thinking）；
- 但**当前走 OpenAI 兼容端点时无法控制它**，且默认思考会吃掉整个预算（`max_tokens=600` 时答案恒为 0）；
- 因此本地模型的档位支持**要么改用原生端点，要么在 UI 上置灰并说明原因**——**已定：置灰**
  （2026-09-26 用户裁定"本地不开放思考展示"，产品决策而非端点限制）；`/think` 在本地返回
  `state:"unsupported"` + 原因，`_chat` 仍发 `reasoning_effort:"none"` 快速模式兜底 + 预留思考量
  （实现见 `docs/reasoning-specs.md` §4）。
