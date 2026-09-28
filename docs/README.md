# 文档目录 · Documentation Index

`docs/` 下的文件按**用途**分两类。想快速了解项目请看第一类；想了解"这些功能是怎么一步步做出来的"请看第二类。

## 一、产品文档（对外）

| 文档 | 内容 |
| --- | --- |
| `docs/PROJECT_DESIGN.md` | 项目设计书：架构、模块划分、数据流、关键设计取舍 |
| `docs/API.md` | CLI 命令、参数、输出格式、退出行为与 Web 工作台 HTTP 接口 |
| `docs/INNOVATION.md` | 创新点说明：证据优先、混合路由、上下文降级等差异化能力 |
| `docs/RELEASE.md` | 发布、分发与版本管理流程 |
| `docs/PR_WORKFLOW.md` | Pull Request 流程、分支建议、模板与验证清单 |
| `docs/P5_CLI_ACCEPTANCE_2026-09-24.md` | CLI / OpenTUI 验收记录（含真实终端手测结论） |
| `docs/chat-features.md` | Chat 工作台功能手册（命令、思考档位、上下文与成本） |
| `docs/session-and-compaction-guide.md` | 多会话与上下文压缩操作指南 |
| `docs/SUBMISSION_PACKAGE_PLAN.md` | 参赛提交材料清单与执行状态 |
| `docs/COMPETITION_DEMO_SCRIPT.md` | 现场演示脚本（3 分钟主路径） |

## 二、过程记录（对内 / 复盘）

| 文档 | 内容 |
| --- | --- |
| `docs/DEV_RECORD.md` | **项目开发过程记录**：2026-05-30 → 2026-09-28 的完整时间线、各阶段目标与交付、关键工程决策、踩坑与修复、质量数据快照，以及合并前 96 份过程文档的索引 |

> 2026-09-28 之前，过程记录是 96 份分散的协作任务单、交付报告、审计与验收矩阵（`mimo-*` / `claude-*` / `codex-*` / `opencode-*` 等）。为了让仓库不至于被过程文档淹没，它们已在
> `chore(docs): 合并过程文档为一份开发记录` 中**合并进 `docs/DEV_RECORD.md` 并从工作区移除**；
> 原始逐篇内容仍可在该提交之前的 git 历史中检出（`git show <commit>:docs/<文件名>`）。

## 三、怎么找东西

- 想装起来用：根目录 `README.md` → `docs/API.md`
- 想评审技术方案：`docs/PROJECT_DESIGN.md` + `docs/INNOVATION.md`
- 想知道某功能为什么这么设计、踩过哪些坑：`docs/DEV_RECORD.md`
- 想看验收口径与复跑命令：`docs/DEV_RECORD.md` §5 + `docs/P5_CLI_ACCEPTANCE_2026-09-24.md`
