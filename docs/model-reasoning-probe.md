# 思考档位探测工具（scripts/probe_model_reasoning.py）

> 任务来源：`.agent-bus/tasks/opencode-probe-tooling-d.json`。
> 脚本由 opencode（MiMo-V2.6-Flash Free）实现；执行中途调度器判定卡住并 release，
> 文档与实测由主控（codex）收尾——脚本内容与下方真实输出均经过复核。
> 相关：`docs/reasoning-effort-probe.md`（DeepSeek 首轮实测）、
> `docs/reasoning-effort-matrix.md`（供应商思考控制对照）。

---

## 1. 为什么要有这个工具

第一版实测把"DeepSeek 思考档位**有效**"判成了"无效"（复盘见
`reasoning-effort-probe.md` §"第一版为什么判错了"）。三个设计缺陷：

1. **没有对照组**——只看"不同档位有没有差异"。若端点收下参数后原样忽略，
   只要档间噪声够大，也能被误读成"有效"；反过来，题目太简单时真差异会被噪声淹没。
2. **预算不足**——`max_tokens=900` 时高档位思考吃满额度被截断，高档反而"显得更短"。
3. **样本太少、只看均值**——每档 2 次，`high` 两次差 2.4 倍；没有单调性/效应量检查。

这个脚本把三条教训固化成规则：**以后每接一个供应商或端点，先跑它，再决定 UI 是否开放思考档位。**

---

## 2. 四条判定规则

| 规则 | 内容 | 是否参与结论 |
|---|---|---|
| **R1 off**（对照） | 关闭开关（如 DeepSeek `thinking=disabled`、Ollama `think=false`）后 reasoning 必须为 **0**；3 次全 0 才 PASS | ✅ 投票 |
| **R2 mono**（档位） | 低→高均值**严格递增**，且 ① 效应量 `最高/最低 ≥ 1.5`，② 信号（首尾差）**大于**任意档内极差 | ✅ 投票 |
| **R3 budget**（预算告警） | completion 顶满 `max_tokens` 或答案低于门槛（默认 50 字符）→ 说明思考挤占预算，产品必须按档位预留 | ❌ 只告警 |
| **R4 verdict**（投票） | 由 R1/R2 的三态（PASS/FAIL/INCONCLUSIVE）投票出结论与 scope | 产出 |

`scope` 与产品动作：

| verdict | scope | 产品动作 |
|---|---|---|
| SUPPORTED | `levels` | 开放关闭 + 全部档位 |
| SUPPORTED | `toggle-only` | 只暴露关闭开关，不暴露档位 |
| SUPPORTED | `off-only` | 开放关闭；档位判 INCONCLUSIVE（加大 `--trials` 复测） |
| SUPPORTED | `levels-no-off` | 开放档位，但不承诺"关闭思考" |
| NOT-SUPPORTED | `none` | **置灰档位**并说明原因（端点收下但忽略） |
| INCONCLUSIVE | `uncertain` | 证据不足按不开放处理，复测后再定 |

---

## 3. 用法

```bash
# DeepSeek（密钥只从环境变量读，绝不接受命令行明文）
DEEPSEEK_API_KEY=... python scripts/probe_model_reasoning.py --provider deepseek --model deepseek-flash

# 本机 Ollama（OpenAI 兼容端点）
python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b

# 追加 Ollama 原生 /api/chat 对照（证明"端点差异"存在）
python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b --also-native
```

关键参数：

- `--trials`（默认 3）：主问题每档调用次数，**< 3 强制 INCONCLUSIVE**；
- `--max-tokens`（默认 2000，**必须 ≥ 2000**）：预算太小会让高档位思考被截断；
- `--levels low,high,max` / `--effort-param` / `--off-json`：覆盖预设，接新供应商用；
- `--key-env NAME`：指定密钥所在环境变量（默认按 provider 预设）；
- `--json`：机器可读输出（CI/报告用）。

脚本行为：每次调用打印一行，失败/超时不抛栈而是标记该档 `ERROR`；
最后输出 R1/R2/R3 结论表 + `verdict/scope/notes`。

---

## 4. 真实运行示例：本机 Ollama `qwen3.5:4b`

命令（2026-09-26，本机服务 `http://127.0.0.1:11434/v1`）：

```bash
python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b --trials 3 --json
```

16 次调用全部成功（`calls=16/16`）：

| 档位 | reasoning 均值 / 极差（字符） | completion tokens | 答案字符 |
|---|---|---|---|
| `think=false` | 7107 / 425 | 2000（3/3 顶满） | 0 |
| `reasoning_effort=low` | 7063 / 232 | 2000（3/3 顶满） | 0 |
| `reasoning_effort=medium` | 7467 / 240 | 2000（3/3 顶满） | 0 |
| `reasoning_effort=high` | 7215 / 274 | 2000（3/3 顶满） | 0 |

规则输出：

- **R1 FAIL**：关闭参数被忽略（`think=false` 档 reasoning 均值 7107，应为 0）；
- **R2 FAIL**：均值非严格递增（7063 → 7467 → 7215），效应量 ≈ 1.02；
- **R3 HIT**：12/12 次 completion 顶满 `max_tokens=2000`，12/12 次答案字符低于门槛。

**结论：`NOT-SUPPORTED / none`。**

产品含义（已落到 Chat 改造）：

1. 本地（OpenAI 兼容端点）的思考档位**置灰**，并说明"该端点会忽略 `reasoning_effort`"；
2. 本地模型必须**预留思考预算**（本机 4B 模型在 2000 tokens 预算下思考吃满、
   答案为空）——否则用户会看到空白回复。

端点差异的对照证据：同一模型走 Ollama **原生** `/api/chat` 时 `think=false`
实测有效（thinking 12159 → 0 字符、耗时 78s → 2.2s）。所以结论必须绑定
"供应商 + 端点"，不能只绑定模型名。

---

## 5. "能设 ≠ 有效"判定原则

1. **端点收下参数 ≠ 参数生效**：只有 reasoning 长度（或行为）出现可复现的、
   单调的差异才算生效；否则一律按"忽略"处理。
2. **必须有对照组**：没有"关闭"档位的供应商（如 OpenAI 推理系）R1 只能给
   INCONCLUSIVE，此时即便档位单调，产品也只能开放档位、不能承诺关闭。
3. **预算要先给足**：`--max-tokens < 2000` 直接拒绝运行——低预算会把"被截断"
   伪装成"档位差异"。
4. **样本与噪声**：每档 ≥3 次，信号必须盖过档内极差；否则 INCONCLUSIVE。
5. **保守默认**：证据不足（INCONCLUSIVE）时**不开放**档位，UI 置灰并提示可复测。

---

## 6. 已知局限

- 只测 reasoning **长度/存在性**，不测思考质量与最终答案正确率；
- 题目固定（一道长链推理题 + 一道 `1+1` 对照题），跨模型比较时题目一致但只有中文；
- 结论有时间性：模型升级、端点改版、中转站换实现都可能改变结果——重新跑一次即可复核；
- 本地小模型 R3 告警高发：`max_tokens` 固定时思考越长答案越短，
  产品侧必须按档位动态预留（见 `docs/chat-experience-plan.md` 组 C 的 C6）。
