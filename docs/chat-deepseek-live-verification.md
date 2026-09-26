# Chat 真实链路验收（DeepSeek 云端 · 四档思考强度）

> 脚本：`scripts/verify_deepseek_live.py`（可复跑）· 执行：主控（codex）
> 密钥：只从 `DEEPSEEK_API_KEY` 环境变量读取，**从不打印、不落盘、不进本报告**。
> 配套：本地链路验收见 `docs/chat-live-verification.md`；stub 契约验收见
> `docs/chat-contract-verification.md`；独立探测见 `docs/reasoning-effort-probe.md`。

---

## 1. 方法

走**产品自己的链路**：`JsonlBackend` + 真实 DeepSeek provider（`create_model_provider`），
通过产品 `/think` 命令切换档位，每档开一个干净会话（并清除 A2 的会话落盘，避免
历史污染对比），提示词为长链推理题（三箱标签问题），单轮超时 300s、`max_tokens=2048`。

```bash
DEEPSEEK_API_KEY=... python scripts/verify_deepseek_live.py
```

每次运行 5 次调用（1 次探活 + 4 档），探活失败仅有"模型不存在"类错误才会
回退 `deepseek-chat`。

## 2. 真实结果（第三次运行，`call_count=5`，总耗时 59.9s）

| 档位 | 耗时 | **reasoning 字符** | 答案字符 | completion tokens | warning |
|---|---|---|---|---|---|
| `off` | 4.47s | **0** | 1494 | 898 | null |
| `low` | 11.88s | **2669** | 1049 | 2451 | null |
| `high` | 11.94s | **2891** | 1214 | 2542 | null |
| `max` | 21.73s | **11736** | 1041 | 4448 | null |

要点：

- **off 真正关闭**：reasoning = 0 字符，答案照常返回（1494 字符）；
- **档位单调**：2669 < 2891 < 11736；耗时同样单调（4.5s → 11.9s → 11.9s → 21.7s）；
- **答案全部非空**——档位预算预留（low/high/max 分别 +4000/+8000/+12000）在真实链路上
  生效，未出现"思考吃满预算 → 空答案"；
- 第二次运行（同为长链题）复核：1551 < 5232 < 10078，结论一致。

## 3. 六条断言（全绿）

| # | 断言 | 结果 |
|---|---|---|
| a | off 档 reasoning<50 且答案非空 | ✅ |
| b | low < high < max（reasoning 字符严格递增） | ✅ |
| c | 四档答案均非空 | ✅ |
| d | reasoning 文本不出现在正文 delta 累积中 | ✅ |
| e | `finished.reasoning` 与 `reasoning_delta` 累积交叉一致 | ✅ |
| f | usage 三键齐全且 `prompt_tokens > 0` | ✅（真实 usage：154/档） |

对比本地 Ollama（`docs/chat-live-verification.md`）：云端返回**真实 usage**（154 恒定，
会话清理生效），本地端点 usage 全 0 只能估算。

## 4. 与独立探测（`reasoning-effort-probe.md`）的对照

| 维度 | 独立探测（裸 API 脚本） | 本次（产品链路） |
|---|---|---|
| 调用路径 | 直接 POST 官方端点 | `JsonlBackend` + provider + `/think` |
| 样本 | 每档 3 次（均值） | 每档 1 次（本报告）+ 复跑一次 |
| low/high/max 均值 | 2624 / 4509 / 6834 | 2669 / 2891 / 11736（单次抽样） |
| off | 0（3/3） | 0（单次） |

两条路径都确认档位有效；数量级差异来自题目与单次抽样（探测脚本已用 3 次均值消除
噪声，本验收的目标是"产品链路真的把参数传下去并拿到结果"）。

## 5. 脚本修正记录（首跑失败 → 二次通过）

首版（由 codex 编写，超时未收尾）有三个缺陷，主控修复后跑通：

1. **未创建 session** 就发 `chat.send`（`Session not found`）——补 `_create_session()`，
   probe 与四档各开干净会话；
2. **错误分类误判**：`"Session not found"` 含 `"not found"`，被 `_probe_failed_for_model`
   当成"模型不存在"并静默换模型——先排除 `session` 关键词再判 404/模型缺失；
3. **提示词与历史污染**：改用长链推理题（简单题下 low/high 差异被随机性淹没），
   并在每档前清除 `chat_session.json`（否则 prompt_tokens 逐档递增 211→256→303）。

## 6. 结论

- **C6（思考档位）在真实云端链路上端到端有效**：`/think off` 真正关闭、`low/high/max`
  单调增强、预算预留保证答案非空；
- 契约 v1 的 reasoning 隔离（`assistant.reasoning_delta` 与 `finished.reasoning`
  双通道、不进正文）在真实链路上成立；
- 真实 usage 可用于云端上下文占比提示；本地（Ollama）仍走估算（见本地验收报告）。

## 7. 复跑

```bash
DEEPSEEK_API_KEY=... python scripts/verify_deepseek_live.py     # 约 60s，5 次调用
```

退出码：0 = 六条断言全过；1 = 有断言失败（输出内部 inconsistency 列表）；
2 = 环境不可用（key 缺失）。报告数字请以 stdout 末尾的 JSON summary 为准。
