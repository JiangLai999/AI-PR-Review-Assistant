你是本项目的协作 agent（claude）。**Phase 2 前端任务**：把 Web 设置页从"只有模型服务"补成
**对齐 CLI 助手 6 阶段**的完整配置面（`ui_language` / `output_format` / `chat_layout` /
`workbench_mode` / `repo_context` / `review_reasoning_effort` 六项）。

## 背景与契约（后端由 opencode 并行实现，字段名已冻结）
`GET /api/config`（`ConfigView.to_dict()`）将新增（**不改既有键**）：

```json
{
  "preferences": { "ui_language": "...", "output_format": "...", "chat_layout": "...", "workbench_mode": "...", "repo_context": "...", "review_reasoning_effort": "..." },
  "options": {
    "ui_languages": [{"value","label"}], "output_formats": [...], "chat_layouts": [...],
    "workbench_modes": [...], "repo_contexts": [...], "review_efforts": [...],
    "numeric_ranges": {"max_tokens": {"min","max","step"}, "timeout_seconds": {...}, "review_concurrency": {...},
                       "cross_file_max_files": {...}, "max_cost_per_run": {...}, "max_cost_per_24h": {...}}
  },
  "runtime_profile": "cloud"
}
```
保存走既有 `POST /api/config`；这 6 个键**已在后端白名单**里（未知键会 400，所以你只能提交白名单键）。
真实设置页载荷形状（**不要改**）：`{provider_name, base_url, model, api_format, persist_secrets, validate, ...numbers, ...flags, [api_key], [github_token]}`。

## 要做的事（write_scope 内）
1. `web/src/api/types.ts`：`ConfigView` 增加 `preferences` / `options` / `runtime_profile` 三个字段的类型
   （`OptionItem = {value: string; label: string}`；`numeric_ranges` 用 `Record<string, {min?: number; max?: number; step?: number}>`）。
2. `web/src/pages/SettingsPage.tsx`：
   - 新增**分组**（沿用现有 Card/Section 风格）：把现有"模型服务/凭证/成本与并发"与新增的
     「界面与输出」（ui_language、output_format、chat_layout、workbench_mode）+
     「审查偏好」（repo_context、review_reasoning_effort）分成 4 组，
     并在每组标题旁标注对应 CLI 助手的阶段号（例如 `界面与输出 · CLI 助手 4/6`）；
   - 6 个控件都用 `<select>`，选项来自 `config.options.*`，初值来自 `config.preferences.*`；
     后端缺字段时（旧后端）该组显示"当前后端不支持这一项"并禁用，**不要崩**；
   - 数值输入用 `options.numeric_ranges` 渲染 `min/max/step`（拿不到就退回现状）；
   - 保存时把 6 个键**一并提交**（即 `payload.ui_language = ...` 等），并在成功后用返回的 `config` 重新 hydrate；
   - 保存失败时（后端 400 带 `ok:false` + `message`）显示 message，不要假装成功；
   - **不要**提交 `auto_publish_comment` / `response_language`（后端刻意不给 Web，提交会 400）。
3. `docs/claude-web-settings-parity.md`：CLI 6 阶段 ↔ Web 分组/控件的对照表、改动点 file:line、
   验证命令与数字、未决项（例如 i18n 全站化留到 Phase 3）。

## 约束
- 只写：`web/src/pages/SettingsPage.tsx`、`web/src/api/types.ts`、`docs/claude-web-settings-parity.md`；
- 禁止改 `src/ai_pr_review/**`（后端是 opencode/主控的）、`web/src/styles/components.css`（mimo 的）、
  `web/src/api/client.ts`（接口形状没变，不需要动）、禁止 git；禁止读取/输出凭据；
- **禁止 `npm run build`**（主控统一重建）；允许 `npm run typecheck`。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
```
另外用你上轮那套自证方式（Playwright 或纯逻辑断言，脚本放 `.pytest_claude/claude/`）证明：
1. 6 个控件渲染且初值来自 `preferences`；
2. 点击保存时提交的 payload **恰好**包含这 6 个键（用 stub fetch 捕获）；
3. 后端回 400 `ok:false` 时页面显示 message 且不显示"保存成功"。

完成后按总线报告：
`python scripts/agent_bridge.py report p2-settings-ui --agent claude --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 三条自证结论>" --blocker "<未决项，没有写无>"`
