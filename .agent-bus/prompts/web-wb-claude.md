你是本项目的协作 agent（claude）。这是一次**方案商讨**（不是写代码）：主控已决定下一阶段开发 Web 审查工作台，
需要你独立审读代码后给出你的方案与优先级意见。**只读源码，只写你自己的提案文档。**

## 项目
根目录：C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant
目标：为 **Web 审查工作台**（`web/` 前端 + `src/ai_pr_review/web_server.py` / `web_jobs.py` / `web_config.py`）
制定下一阶段开发方案。CLI 审查工作台（`frontend/tui/src`、`src/ai_pr_review/cli.py`）已收口，Web 侧要对齐并闭环。

## 主控已完成的审计（供你核对，不要凭印象；发现遗漏请在文档里指出并给 file:line）
- 前端 `web/src/`：`App.tsx` 侧边栏 + hash 路由 6 页（overview/review/history/benchmark/api/settings）、
  `api/client.ts`（15 个 fetch 封装）、`api/types.ts`（与后端契约）；`pages/ReviewPage.tsx`(30.8KB) 是核心：
  计划模式=同步 `POST /api/plan`；完整审查= `POST /api/review {async_job:true}` 拿 job → SSE `/api/jobs/{id}/events`
  ＋ 轮询兜底 ＋ `POST /api/jobs/{id}/cancel`（真取消）；结果区＝证据四态摘要、严重度/证据筛选、
  `FindingCard`/`PlanCard`/`FilterCard`/`ValidationCard`/`InterfaceImpactCard`。
- 后端：`web_server.py`（`BaseHTTPRequestHandler` 手写路由、SSE 写出、静态托管＋SPA fallback、body 限额）、
  `web_jobs.py`（`ReviewJob`/`ReviewJobManager`：threading+queue，取消在文件边界生效）、`web_config.py`（设置页读写）。
- API 16 条：GET `health/meta/history/report/benchmark/credentials/config/demo.cases/demo.run/jobs/jobs{id}/jobs{id}/events(SSE)`；
  POST `plan/review(+async_job)/jobs{id}/cancel/feedback/config`。
- 测试与工具：`tests/test_web_server.py`（13 个测试类）、`web/tools/*.mjs` 9 个 Playwright 脚本（截图/可见性审计/布局探测）、
  `web/.shots/` 40+ 张多视口截图；构建 `vite` → `src/ai_pr_review/web_static`（base=`/static/`）。

## 已知缺口（主控列的 7 条，可质疑、可补、可重排）
1. 无法**发布评论到 GitHub**（CLI 有 `pr-review publish`、TUI `/publish`）
2. 报告**无导出/复制**（CLI 有 `export-run`、TUI `/report`）
3. **设置页**比 CLI 助手少一半（缺 UI 语言/输出格式/自动发评论/chat 布局/工作台模式/仓库上下文/审查思考档位）
4. **ApiPage 只文档化 7/16 端点**（jobs/SSE、cancel、credentials、config、meta、demo 全缺）
5. 无 **i18n**（CLI 已中英双语）
6. 无"**审查结果问答/会话**"（CLI 有 chat+会话+仓库结构注入）
7. **CI 不构建前端**（`vite build` 不在 workflow，产物靠本地构建提交）

## 你的重点方向（其余方向也要在优先级里表态）
**端到端闭环：Web 端"发布审查评论到 GitHub" + "报告导出/复制"**
1. 读 `src/ai_pr_review/services/publish_service.py`、`frontend/tui/src/app.tsx` 的 `/publish` 与 `publishOpen` 流程、
   `src/ai_pr_review/web_server.py` 现有 POST 路由，弄清 CLI 侧发布评论的**载荷构造（含冻结格式/北京时间/统计尾注）**
   与幂等/去重策略。
2. 给出 Web 方案：接口契约（`POST /api/publish` 的入参/出参/错误码）、前端交互（按钮位置、二次确认、
   成功后可点击的评论链接、失败回退）、权限与安全（token 缺失、无权、限流、重复发布、dry-run）、
   与 `web_jobs.py` 任务化的取舍（同步 or 异步）。
3. 报告导出：给出 `/api/report` 的导出形态（Markdown 文本 vs 下载响应头 vs 前端生成）、
   与 CLI `export-run` 的产物一致性、复制到剪贴板的交互。
4. 测试点：`tests/test_web_server.py` 需要新增哪些用例（列到用例名级别）。

## 交付物（只写这一个文件；其它文件一律只读）
`docs/web-workbench-proposal-claude.md`，包含：
1. **现状核对**：你实际读到的关键位置（file:line）＋你对现状的判断＋**主控审计遗漏项**（若有）
2. **实现方案**：上述重点方向的接口契约 / 数据结构 / 组件与函数级改动 / 错误与降级 / 安全 / 测试点
3. **风险与坑**：必须来自代码证据（例如 `web_server.py` 的 SSE/线程模型、`publish_service` 的哪些假设在 Web 下不成立）
4. **优先级建议**：对 7 条缺口排序；"如果只做 3 件"选哪 3 件、为什么；每条给工作量估计 S/M/L
5. **验收方式**：可执行的命令与断言

## 约束
- 只写 `docs/web-workbench-proposal-claude.md`；**禁止修改任何源码、配置、其它文档**；禁止 git 操作；
- 禁止读取/输出任何凭据（token / API key / 会话日志）；
- 所有结论必须给 `文件:行号` 证据；不确定就写"未确认"。

完成后按总线报告：
`python scripts/agent_bridge.py report web-wb-claude --agent claude --status completed --summary "<一句话>" --evidence "<你读过的文件:行号 + 结论要点>" --blocker "<未决项，没有写无>"`
