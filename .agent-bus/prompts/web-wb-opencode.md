你是本项目的协作 agent（opencode）。这是一次**方案商讨**（不是写代码）：主控已决定下一阶段开发 Web 审查工作台，
需要你独立审读代码后给出你的方案与优先级意见。**只读源码，只写你自己的提案文档。**

## 项目
根目录：C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant
目标：为 **Web 审查工作台**（`web/` 前端 + `src/ai_pr_review/web_server.py` / `web_jobs.py` / `web_config.py`）
制定下一阶段开发方案。CLI 审查工作台已收口（含 6 阶段配置助手、中英双语、模型槽位/规格/中转站配置），Web 侧要对齐。

## 主控已完成的审计（供你核对，不要凭印象；发现遗漏请指出并给 file:line）
- 前端 `web/src/`：`App.tsx`（侧边栏＋hash 路由 6 页＋服务/凭证健康条＋每页 ErrorBoundary）、
  `api/client.ts`（15 个 fetch）、`api/types.ts`；`pages/`：Overview(16K)/Review(30.8K)/History(9K)/Benchmark(12.6K)/Api(7.2K)/Settings(17.5K)；
  `components/`：ReviewPanels/FindingCard/DemoPanel/HeroKnot/ParticleBackground(21K)/ui/ErrorBoundary；
  `styles/tokens.css`(11.6K)＋`components.css`(57K)。
- `pages/SettingsPage.tsx` 当前可编辑：Provider、Base URL、模型、API 格式、API Key（掩码）＋6 个数值项
  （max_tokens、timeout_seconds、review_concurrency、cross_file_max_files、max_cost_per_run、max_cost_per_24h）＋2 个开关
  （enable_static_analysis、enable_cross_file_review）；凭证健康走 `/api/credentials`。
- 后端 `web_config.py`：`ConfigView` / `apply_config_update`；`web_server.py` 的 `POST /api/config`。
- `pages/ApiPage.tsx` 目前只文档化 7 个端点（health/plan/review/history/report/feedback/benchmark），
  而服务端实际有 16 条（另有 meta/credentials/config/demo.cases/demo.run/jobs/jobs{id}/jobs{id}/events(SSE)/cancel）。
- 构建：`web/vite.config.ts` base=`/static/`、outDir=`src/ai_pr_review/web_static`；dev 5173 代理 `/api`→8787；
  `web/tools/*.mjs` 9 个 Playwright 脚本（整页/切片截图、逐页可见性审计、布局探测、空白溯源）。
- CI：`.github/workflows/ci.yml` 只跑 pytest/black/isort/mypy + `python -m build`；**不构建 `web/`**（也不构建 `frontend/tui`）。

## 已知缺口（主控列的 7 条，可质疑、可补、可重排）
1. 无法发布评论到 GitHub（CLI 有 `pr-review publish`）
2. 报告无导出/复制（CLI 有 `export-run`）
3. **设置页**比 CLI 助手少一半（UI 语言/输出格式/自动发评论/chat 布局/工作台模式/仓库上下文/审查思考档位）
4. **ApiPage 只文档化 7/16 端点**
5. 无 **i18n**（CLI 已中英双语）
6. 无"审查结果问答/会话"
7. **CI 不构建前端**

## 你的重点方向（其余方向也要在优先级里表态）
**配置面与前端工程：把 Web 设置页对齐 CLI 助手的 6 阶段 + ApiPage 补全 + i18n + CI 构建**
1. 读 `src/ai_pr_review/config.py`（`AppConfig` / `preferences` 全字段 / `CHAT_*` / `REVIEW_*` 常量）、
   `src/ai_pr_review/web_config.py`（现有 `ConfigView` 暴露了哪些字段、`apply_config_update` 支持哪些键）、
   `frontend/tui/src/app.tsx` 的 `SetupWizardDialog`（6 阶段都有哪些屏、每屏写什么键）。
2. 产出一张**字段对照表**：CLI 助手能配的字段 vs Web 设置页现状 vs 后端是否已支持 → 缺哪些、该怎么补
   （控件类型：下拉/数字/开关/文本；校验；保存载荷；是否需要新 API）。
3. ApiPage：给出补全 16 端点的信息结构（方法/路径/入参/出参/示例/错误码），并指出文档应与
   `web_server.py` 的路由表保持同步的机制建议（避免再次漂移）。
4. i18n：给出最小可行方案（词典文件 + `useLang()` + 语言开关 + 与 `preferences.ui_language` 打通），
   说明改造面（哪些文件、约多少处文案）与风险。
5. CI：给出在 `.github/workflows/ci.yml` 中加 `web` 构建与 typecheck 的具体步骤（Node 版本、缓存、命令），
   以及前端产物是否需要校验"源码构建结果 == 已提交产物"。

## 交付物（只写这一个文件；其它文件一律只读）
`docs/DEV_RECORD.md`，包含：
1. **现状核对**（file:line）＋**主控审计遗漏项**（若有）
2. **字段对照表** + **实现方案**（设置页/ApiPage/i18n/CI 各自的改动点与顺序）
3. **风险与坑**（来自代码证据：`apply_config_update` 的限制、保存键掩码语义、`ui_language` 生效链路等）
4. **优先级建议**：7 条缺口排序；"只做 3 件"选哪 3 件、为什么；每条工作量 S/M/L
5. **验收方式**：可执行命令与断言

## 约束
- 只写 `docs/DEV_RECORD.md`；**禁止修改任何源码、配置、其它文档**；禁止 git 操作；
- 禁止读取/输出任何凭据；结论必须给 `文件:行号`；不确定写"未确认"。

完成后按总线报告：
`python scripts/agent_bridge.py report web-wb-opencode --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + 结论要点>" --blocker "<未决项，没有写无>"`
