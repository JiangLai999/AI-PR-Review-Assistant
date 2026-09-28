# DeepSeek 思考强度实测报告（v2 · 修正版）

日期：2026-09-26 · 脚本：`_p5_verify/p6proto/probe_reasoning_effort.py`
模型：`deepseek-flash`（官方 API）· 官方文档：`api-docs.deepseek.com/zh-cn/guides/thinking_mode`

---

## 结论（先说）

**DeepSeek 支持思考强度控制，且实测呈明确单调关系。**

| 档位 | reasoning 字符（3 次） | 均值 | 说明 |
|---|---|---|---|
| `{"thinking": {"type": "disabled"}}` | **0 / 0 / 0** | **0** | 关闭思考，生效确定 |
| `reasoning_effort: "low"` | 3073 / 1870 / 2929 | **2624** | 有效 |
| `reasoning_effort: "high"`（默认） | 5335 / 6043 / 2150 | **4509** | 有效 |
| `reasoning_effort: "max"` | **6293 / 7165 / 7043** | **6834** | 有效且最稳定 |

**`disabled(0) < low(2.6k) < high(4.5k) < max(6.8k)`** —— 档位真实起作用。

## 官方文档要点（guides/thinking_mode）

OpenAI 格式下的控制参数：

```text
思考开关： {"thinking": {"type": "enabled|disabled"}}
思考强度： {"reasoning_effort": "low|high|max"}
```

- 思考模式**默认开启**，`effort` **默认 `high`**
- 兼容映射：`minimal→low`、`medium→high`、`xhigh→high`、`ultra→max`
  （所以"minimal 与 low 无差别"是设计使然，不是失效）
- 思考模式下 **`temperature` / `presence_penalty` / `frequency_penalty` 不生效**
  （设了不报错，但也不起作用）；`top_p` 仅在思考模式下生效

## ⚠️ 实测发现的第二个坑：思考会吃掉 token 预算

| 档位 | completion tokens | 答案字符数 |
|---|---|---|
| `max` #1 / #2 / #3 | 2000 / 2000 / 2000（**全部顶满**） | **142 / 0 / 88** |
| `low` #1 / #3 | 2000 / 2000（顶满） | **0 / 0** |
| `disabled` #1 | 1261 | 2110（正常作答） |

`max_tokens = 2000` 时，reasoning 自己就能占满额度，**答案被挤成空字符串**。

**实现要求**：`max_tokens` 必须**按 effort 预留思考开销**（例如
`max_tokens = answer_budget + reasoning_budget(effort)`），否则用户会看到空回复。

## 第一版为什么判错了（保留教训）

第一版实测结论是"DeepSeek 忽略该参数"，**错的**，原因三条：

1. **题目太简单**（中学数学题）→ 思考长度本就随机，档位差异被噪声淹没；
2. **`max_tokens=900`** → 高档位思考被截断，反而显得"更短"；
3. **每档只跑 2 次** → 样本不足（`high` 两次就差 2.4 倍）。

修正版换成需要长链推理的题（三箱标签问题）、`max_tokens=2000`、每档 3 次，
并加入 `thinking: disabled` 作为对照，结论立刻清晰。

**教训**：验证"参数是否生效"必须有**对照组**（关闭 vs 开启）与**足够预算**，
不能只靠"不同取值有没有差异"。

## 对方案 C6 的影响

原 C6 被第一版结论误导，改成了"能力驱动、DeepSeek 不开放"——**这个改动作废**。
正确设计：

| 档位 | 参数 |
|---|---|
| `off` | `{"thinking": {"type": "disabled"}}` |
| `low` / `high`（默认） / `max` | `{"reasoning_effort": "..."}` |

- 只暴露文档认可的三个有效值（`low/high/max`）+ 关闭；
- 请求时**预留思考预算**（见上）；
- 其它供应商（MiMo `variant`、OpenAI 推理系）按同一套"**先实测再开放**"的规矩接入；
  本脚本可直接扩展为它们的验收用例。
