你是本项目的协作 agent（mimo）。这是一次**方案商讨**（不是写代码）：主控已决定下一阶段开发 Web 审查工作台，
需要你独立审读代码后给出你的方案与优先级意见。**只读源码，只写你自己的提案文档。**

## 项目
根目录：C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant
目标：为 **Web 审查工作台**（`web/` 前端 + `src/ai_pr_review/web_server.py` / `web_jobs.py` / `web_config.py`）
制定下一阶段开发方案。

## 主控已完成的审计（供你核对，不要凭印象；发现遗漏请指出并给 file:line）
- 前端 `web/src/`：`App.tsx`（侧边栏＋hash 路由：overview/review/history/benchmark/api/settings）、
  `pages/ReviewPage.tsx`(30.8K) 是核心（计划=同步 `/api/plan`；完整审查=异步 job + SSE `/api/jobs/{id}/events` + 轮询兜底 + `/cancel`），
  结果区有证据四态、严重度/证据筛选、FindingCard/PlanCard/FilterCard/ValidationCard/InterfaceImpactCard；
  `components/` 含 `HeroKnot`（Hero 视觉）、`ParticleBackground`(21K)（粒子背景）；`styles/components.css` 57K。
- 后端：`web_server.py`（手写路由 + SSE + 静态托管）、`web_jobs.py`（线程 + queue，取消在文件边界生效）、`web_config.py`。
- CLI 侧已有能力：`pr-review chat`（TUI 会话聊天）、`jsonl_server.py` 的 `chat.send` / `session.*` / `/context`（把审查 run 绑定进对话）、
  仓库结构注入（`_repo_files_for_chat` + PR 变更清单 + 目录树，见 `docs/claude-repo-structure-context.md`）、
  思考档位（`/think`）、压缩（`/compact`）。
- 测试：`tests/test_web_server.py`（13 个测试类）、`tests/test_jsonl_backend.py`；`web/.shots/` 40+ 张多视口截图；
  `web/tools/*.mjs` 9 个 Playwright 脚本（截图/可见性审计/布局探测/参考站对照）。

## 已知缺口（主控列的 7 条，可质疑、可补、可重排）
1. 无法发布评论到 GitHub　2. 报告无导出/复制　3. 设置页比 CLI 助手少一半　4. ApiPage 只文档化 7/16 端点
5. 无 i18n　6. **无"审查结果问答/会话"**　7. CI 不构建前端

## 你的重点方向（其余方向也要在优先级里表态）
**A. 审查结果问答（把 CLI 的 chat 搬到 Web）可行性与最小实现**
1. 读 `src/ai_pr_review/backend/jsonl_server.py` 的 `chat.send`、`_review_context_for_chat`（或等价函数）、
   `/context` 绑定、仓库结构注入三段（`_repo_files_for_chat`、PR 变更清单、目录树），
   判断这些逻辑能否被 Web 复用（是否依赖 TUI 的 session 文件 / 进程内状态 / 事件流）。
2. 给出 Web 端最小可行方案：是新增 `POST /api/chat`（无状态、每次带 run_id + 用户问题）还是引入会话存储？
   给接口契约、上下文装配方式（复用哪个函数、注入哪些段、预算怎么算）、SSE 流式返回的取舍、
   降级（未绑定 run / 无模型 Key / 超预算）。
3. 明确**不建议做**的部分（说明理由），避免范围膨胀。

**B. 工作台 UX / 视觉一致性（基于代码与截图）**
1. 读 `web/src/styles/tokens.css`＋`components.css` 的令牌与布局，和 `web/.shots/` 的多视口截图（1440/1280/900/390），
   列出**具体**的可用性问题（至少 5 条：例如首屏信息密度、长报告滚动、Finding 详情层级、移动端可用性、
   空/错/加载态一致性、键盘可达性/焦点管理），每条给 `文件:行号` 或截图文件名。
2. 给出改进清单（每条：现象 → 改法 → 影响文件 → 验证方式），并按"性价比"排序。

## 交付物（只写这一个文件；其它文件一律只读）
`docs/web-workbench-proposal-mimo.md`，包含：
1. **现状核对**（file:line）＋**主控审计遗漏项**（若有）
2. **A 方案**（接口契约/上下文装配/降级/测试点）＋**B 改进清单**（现象→改法→文件→验证）
3. **风险与坑**（来自代码证据：jsonl_server 的进程内状态、SSE 与线程模型、token 预算等）
4. **优先级建议**：7 条缺口排序；"只做 3 件"选哪 3 件、为什么；每条工作量 S/M/L
5. **验收方式**：可执行命令与断言

## 约束
- 只写 `docs/web-workbench-proposal-mimo.md`；**禁止修改任何源码、配置、其它文档**；禁止 git 操作；
- 禁止读取/输出任何凭据；结论必须给 `文件:行号`；不确定写"未确认"。

完成后按总线报告：
`python scripts/agent_bridge.py report web-wb-mimo --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + 结论要点>" --blocker "<未决项，没有写无>"`
