你是本项目的协作 agent（claude）。这是**实现任务**（写代码）：给 Web 审查工作台做 Phase 1 的**前端**——
发布审查评论到 GitHub + 报告导出/复制的 UI。后端由主控（codex）**并行**实现，接口契约下面已冻结，你按它写前端即可。

## 背景（已定稿）
主控已批准你的提案 `docs/web-workbench-proposal-claude.md` 的 Phase 1 设计（①发布 + ②导出，成对做）。
Phase 0 的跨站守卫由主控在 `web_server.py` 落地（写端点要求 `Content-Type: application/json` +
同源；否则 415）。你**不要**改后端。

## 冻结的接口契约（主控并行实现，按此写前端）
1. `POST /api/publish`，JSON body：`{ "run_id": "<id>", "confirm": true|false }`
   返回 200：
   ```json
   {
     "status": "preview" | "published" | "already_published",
     "comment_body": "<完整 Markdown 评论正文>",
     "comment_chars": 572,
     "requires_confirmation": true,
     "comment_url": "",              // published 时非空，可直接打开
     "comment_id": "",               // 可能为空
     "message": "<人话状态/警告>"      // 可空
   }
   ```
   错误：400（run_id 缺失/非法）、404（run 不存在）、409（该 run 没有 PR 链接）、415（跨站/非 JSON）、
   502（GitHub 侧失败，`{"error": "..."}`）、503（未配置 GitHub Token）。
2. `GET /api/report/export?run_id=<id>&format=markdown|json`
   - `format=markdown` → `Content-Type: text/markdown; charset=utf-8` +
     `Content-Disposition: attachment; filename="pr<N>-<run8>.md"`，正文就是评论同款 Markdown（真相源 `ReportRenderer.render_markdown`）。
   - `format=json` → `application/json`，含 `run/review/plan/validation/interface_impacts/feedback`。

## 要做的事（write_scope 内）
1. `web/src/api/types.ts`：加 `PublishResponse`（字段同上）、`ReportExportFormat`。
2. `web/src/api/client.ts`：加 `publish(runId, confirm)`、`exportReportUrl(runId, format)`（返回 URL 供 `<a download>` 用）。
   - 注意 `request()` 目前强制 `content-type: application/json`，保持不变。
3. 新建 `web/src/components/ReportActions.tsx`：
   - **预览优先**：第一次点击只能拿 preview（`confirm:false`），把 `comment_body` 渲染成只读预览区
     （复用现有 Markdown 渲染方式；若现有页面是纯文本，就按纯文本 + 等宽字体，别引入新依赖）；
   - **二次确认**：预览区里出现「确认发布到 GitHub PR」按钮（危险色），点击才 `confirm:true`；
   - **五态**：idle / previewing / previewed / publishing / published（+ 失败态带可读原因，401/403/404/409/415/502/503 尽量区分文案，拿不准就给通用文案 + 原始 message）；
   - **幂等提示**：返回 `already_published` 时提示"已发布过，本次又发了一条"并给出 `comment_url`；
   - **复制**：`navigator.clipboard.writeText(comment_body)`，失败时回退（隐藏 textarea + `document.execCommand('copy')`），成功后 2 秒内显示"已复制"；
   - **下载**：`<a href=exportReportUrl(runId,'markdown') download>`；JSON 选项同样给一个；
   - 无 `run_id`（计划模式结果没有 run）时整个组件渲染禁用态 + 说明"先生成一次完整审查再发布"。
4. `web/src/pages/ReviewPage.tsx`：完整审查成功（有 `job.run_id` / `result.run.id`）后渲染 `<ReportActions runId=... />`；
   计划模式结果不渲染或渲染禁用态（二选一，说明理由）。
5. `web/src/pages/HistoryPage.tsx`：打开某条历史报告（`/api/report` 成功后）渲染同一个 `<ReportActions runId=... />`。
6. `web/src/styles/components.css`：给上述组件补样式（沿用现有 design tokens，别写死颜色；危险动作按钮用现有 danger 语义类）。
7. `docs/claude-web-report-actions.md`：改动点（file:line）、五态与错误映射表、验证命令与数字、未决项。

## 约束
- **只写 write_scope 里的文件**；禁止改 `src/ai_pr_review/**`（后端是主控的）、禁止改 `ApiPage.tsx`（另一 agent 的）、禁止 git 操作；
- **禁止运行 `npm run build`**（`web_static/` 由主控在整合时统一重建）；允许 `npm run typecheck`；
- 禁止读取/输出任何凭据；不确定就写"未确认"；
- 不新增第三方依赖。

## 验证（必须真跑并报数字）
```bash
cd web && npm run typecheck      # 期望 exit 0
```
另外用你已有的 `web/tools/*.mjs`（Playwright）或纯逻辑断言，自证以下两点（写进文档）：
1. `confirm:false` 的调用序列里**没有**任何 `confirm:true`（预览不会误发）；
2. 失败响应能落到可读文案（用 stub fetch 断言 status→文案映射）。

完成后按总线报告：
`python scripts/agent_bridge.py report web-p1-frontend --agent claude --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 自证断言结论>" --blocker "<未决项，没有写无>"`
