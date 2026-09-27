你是本项目的协作 agent（claude）。**Phase 3 前端任务**：给 Web 工作台加「对这次审查追问」的面板。

## 背景
后端由主控接线 + opencode 提供服务层；接口契约已冻结：

```
POST /api/chat  { "run_id": "<可选>", "text": "<问题>" }
200 { "reply", "model", "usage"|null,
      "context_meta": { "bound_run"|null, "token_estimate"|null, "sections": [...], "truncated": bool, "note": "" } }
400 { "error", "code": "invalid_request" }       // text 缺失
404 { "error", "code": "not_found" }             // run_id 查不到
415 { "error" }                                  // 跨站守卫（正常路径不会遇到）
502 { "error", "code": "chat_failed" }
503 { "error", "code": "missing_api_key" }
```

## 要做的事（write_scope 内）
1. `web/src/api/types.ts`：加 `ChatResponse` / `ChatContextMeta` 类型。
2. `web/src/api/client.ts`：加 `chat(runId, text)`（POST `/api/chat`）。
3. 新建 `web/src/components/AskPanel.tsx`：
   - props：`{ runId?: string; language?: string }`；
   - UI：标题「追问这次审查」+ 只读提示（绑定的 run 前 8 位 + `token_estimate` 有就显示"约 N tokens 上下文"）+
     一个单行输入 + 「追问」按钮 + 回答区（多轮，保留本次会话内的历史，**不做持久化**）；
   - 状态：`idle / asking / answered / failed`；asking 时禁用输入与按钮并显示 Spinner；
   - 无 `runId` 时：输入可用但提示"未绑定审查记录，将按普通对话回答"（后端也支持无 run 的纯对话）；
   - 错误映射（用 `client.ts` 抛出的 `ApiError.status`）：503 → 引导去设置页配 Key / 切本地模型；
     404 → "该审查记录已不存在"；502 → 显示后端 message；其它 → 通用文案 + 原始 message；
   - 回答区用等宽/保留换行渲染（不要引入 Markdown 依赖）；
   - 键盘：`Enter` 提交、`Shift+Enter` 不适用（单行输入），提交后输入框清空并保持焦点；
   - `truncated=true` 时在回答上方显示 `note` 警告条。
4. 挂载：`web/src/pages/ReviewPage.tsx`（有 `result.run.id` 时）与 `web/src/pages/HistoryPage.tsx`
   （打开某条报告、`report.run_id` 存在时）各渲染一个 `<AskPanel runId=... />`，放在你 Phase 1 那个
   `ReportActions` 附近，保持视觉一致。
5. `web/src/styles/components.css`：补 `ask-panel` 相关样式（沿用 design tokens；危险/警告色用既有语义变量）。
6. `docs/claude-web-ask-panel.md`：组件契约、状态机、错误映射表、改动点 file:line、验证与未决项。

## 约束
- 只写：`web/src/components/AskPanel.tsx`、`web/src/api/types.ts`、`web/src/api/client.ts`、
  `web/src/pages/ReviewPage.tsx`、`web/src/pages/HistoryPage.tsx`、`web/src/styles/components.css`、
  `docs/claude-web-ask-panel.md`；
- 禁止改 `src/ai_pr_review/**`；禁止 git；禁止读取/输出凭据；不新增第三方依赖；
- **禁止 `npm run build`**（主控统一重建）；允许 `npm run typecheck`。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
```
并用你既有那套离线自证（Playwright + `page.route` 打桩，脚本放 `.pytest_claude/claude/`）证明：
1. 无 `runId` → 显示"普通对话"提示且可提交；
2. 提交时 body 恰好是 `{run_id, text}`；
3. 503 → 显示"去配置模型"的引导文案；502 → 显示后端 message；404 → "记录不存在"；
4. `truncated=true` → 出现 note 警告条；多轮追问时历史保留。

完成后按总线报告：
`python scripts/agent_bridge.py report p3-ask-panel --agent claude --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 四条自证结论>" --blocker "<未决项，没有写无>"`
