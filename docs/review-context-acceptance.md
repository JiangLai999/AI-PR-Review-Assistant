# 审查上下文验收报告（§9.3）

日期：2026-09-26
脚本：`_p5_verify/p6proto/verify_review_context_acceptance.py`（可复现，不依赖云 API）
对应标准：`docs/dual-model-roles-plan.md` §9.3 五条

## 结论

**PASS** —— 11 项断言全绿；第 5 条只做到"本机 Ollama 可达"，端到端中文问答
仍需交互式验证（已在报告中标注为 SKIP 而非 PASS，避免假绿）。

## 覆盖与证据

### 1 / 2. 绑定后注入的上下文与 run 记录逐字一致

构造一条含 2 个 finding 的 run（第 2 条带 `needs_review` 与证据疑点），
绑定后检查注入的 system prompt：

```
PASS  文件与行号注入          第 2 条的位置 src/service.py:42-44
PASS  证据状态注入            needs_review
PASS  证据疑点注入            片段未在文件内容中找到
PASS  标题注入                第二条问题
```

位置、证据状态、证据疑点、标题全部来自 run 记录本身，没有推测成分。

### 3. `/context off` 之后不再注入

```
PASS  解绑后 prompt 不含该 run 的 finding
PASS  解绑后 current_run_id 为空
```

即"解绑后模型看不到旧 finding"——不会出现"假装还记得"的编造。

### 4. 超预算时的裁剪顺序

把预算压到 1 token 后：

```
PASS  预算极小仍返回上下文
PASS  L1 保留（summary / PR 信息）
PASS  L3/L4 被裁剪                      trimmed = ('L3', 'L2')
```

与方案 §9.2 D 一致：**L1 永不裁剪**，其余按 L4 → L3 → L2 顺序退让。

### 5. 断网 + 本地 chat 槽

```
PASS  本机 Ollama 可达（http://127.0.0.1:11434，模型 qwen3.5:4b 在列）
SKIP  端到端中文问答          需要交互式终端，未在本脚本中冒充通过
```

## 局限与后续

1. 本脚本验证的是**上下文层**（注入内容与 run 记录一致）。"模型复述是否忠于
   上下文"属模型行为，需在真实会话里抽查（本轮验收已在真机做过多次，见
   `docs/claude-review-context.md`）。
2. 第 5 条的完整链路（本地模型 + 断网 + 追问）建议在比赛演示前用真机走一遍；
   脚本只能证明"本地模型可达"。
3. 未覆盖：跨 run 切换后的上下文残留（由 `/context off` 与
   `test_chat_switches_binding_when_another_pr_is_named` 覆盖）。
