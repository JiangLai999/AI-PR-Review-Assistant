# TUI 配置助手收尾（mimo-wizard-followup）

> 任务：`.agent-bus/tasks/mimo-wizard-followup.json`
> 上游未决项：`docs/mimo-config-wizard-ui.md` §6.1-§6.3 + `docs/claude-backend-followup.md` §4 的预算来源
> 执行说明：**mimo 在实现完成后被平台限流中断**（长时间无输出触发调度器 stall 终止；
> 代码已全部落盘）。本文件的验证与收尾由主控完成。

---

## 1. 四项交付

| # | 未决项 | 实现 | 关键点 |
|---|---|---|---|
| 1 | **custom_endpoint 载荷污染**（§6.1：cloud/local 流程预填值会把载荷 `provider_name` 改成 custom） | **dirty 标记**：新增 `customDirty` signal，预填表单时复位；**只有用户实际改动过**才提交 custom_endpoint 字段 | 比"仅 isCustom 才提交"更精确——自定义流程里预填但未改也不会误提交 |
| 2 | **api_key 可清空**（§6.2） | 新纯函数 `interpretApiKeyInput(raw)`：`"-"` → `""`（**清空**）；空串 → `undefined`（不动）；其它 → trim 值 | 页脚提示：`type - in API Key to clear`（中英双语）；输入 `-` 时行内提示"（将清空）" |
| 3 | **`validateSpecInput` 接线**（§6.3） | 规格屏 `context_window`/`max_output` 的输入校验接入 `validateSpecInput(inputValue(), bounds, uiLanguage())`，越界/非整数给出内联提示 | 后端仍有最终校验（前端只是先行提示） |
| 4 | **`budget_source` 展示** | 规格屏新增一行 `formatBudgetSource(budget, source, lang)`；`runtime.chat_context_budget_source` 已接入 `RuntimeSnapshot` 类型 | 缺字段不显示（兼容旧后端）；文案含来源枚举（config/model_spec/fallback） |

实现文件：`frontend/tui/src/app.tsx`（+131）、`format.ts`（+31）、`protocol.ts`（+19）、
`setup-routing.ts`（+32，含 `interpretApiKeyInput`）、`setup-routing.test.ts`（+102 测试）。

## 2. 验证（主控复跑）

```text
cd frontend/tui
bun run typecheck                   → exit 0
bun test src                        → 176 pass / 0 fail（872 expect；较上轮 +5）
scripts/manual-route-wizard-check.tsx → 111 PASS / 0 FAIL
scripts/manual-chat-markdown-check.tsx → 75 PASS / 0 FAIL
```

## 3. 未决项（如实记录）

1. **manual 帧断言未补**：任务原要求为上述四项补 manual 断言；mimo 中断前只补了
   `setup-routing.test.ts` 的单测（覆盖 `interpretApiKeyInput` 的三态与规格字段构造）。
   渲染层（`-` 提示行、budget_source 行）目前由既有 manual 帧间接覆盖（全绿），
   **专项帧断言留待后续补**（不阻塞功能）。
2. `needs_verification` 的一键实测（点击后真实触发目录核对）仍未做（上游 §6.4）。
3. 与 §6 其它项一致：cloud/local 流程的 custom_endpoint 表单在用户未改动时不会提交，
   但**表单本身仍会预填**（只读预填，不写载荷）——若产品希望彻底隐藏该表单，另开任务。
