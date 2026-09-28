# PR 工作流指南

本项目采用"小而专一"的 Pull Request 工作方式。目标是让 `main` 分支始终保持可运行，同时让每次改动都容易审查、容易回滚、容易定位问题。

## 规则

- 所有新功能、修复和文档更新都通过 PR 合入。
- 每个 PR 只聚焦一个明确目标：一个功能、一个修复或一组相关文档变更。
- 大任务必须拆成多个可以独立审查和合并的小 PR。
- PR 标题和描述必须与实际代码改动一致，不要提交空描述。
- 如果新增了第三方依赖，必须同步更新 `README.md` 与 `pyproject.toml`。
- 如果复用了历史代码或外部片段，需要在 PR 描述中明确来源。
- 每次合并后都要确保 `main` 仍可运行。

## 推荐分支流程

开始开发前：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/small-focused-change
```

实现并验证完成后：

```bash
git status
git diff
git add <intended-files>
git commit -m "feat: describe one focused change"
git push -u origin feat/small-focused-change
```

然后向 `main` 发起 Pull Request。

## 提交前验证清单

提交前至少跑完这四条，与 CI 门禁完全一致：

```bash
pytest
black --check src tests
isort --check-only src tests
mypy src
```

- 只想先跑相关模块时用 `pytest tests/test_cli.py` 这类窄范围命令，但**合并前必须至少跑一次全量** `pytest`。
- `black` 与 `isort` 的版本在 `pyproject.toml` 的 `dev` 依赖里钉死（`24.10.0` / `5.13.2`）；本地版本不一致会得出与 CI 不同的结论。
- Windows 工作区是 CRLF：新增行若写成 LF，`black` / `isort` 会判红。改完请用钉死版本复检，而不是仓库里的新版工具。

同时检查：

- `git status --short` 与 `git diff --stat` 里没有多余文件。
- 暂存区中没有密钥、token 或本地私有配置（`.ai_pr_review/config.local.json` 一类）。
- PR 描述与实际 diff 保持一致。

## CI 门禁

`.github/workflows/ci.yml` 的四个 job 全部通过才合并：

1. `test-and-quality`：Python 3.12 与 3.13 双版本跑 `pytest`、`black --check src tests`、`isort --check-only src tests`、`mypy src`。
2. `build`：`windows-latest` 上执行 `python -m build`，并断言产物标签是 `py3-none-win_amd64`（`tui_static` 含 Windows x64 专用产物，钩子失效会产出错标的 `py3-none-any` wheel）。
3. `frontend`：Node 22 下三个会红的自测脚本（`web/tools/markdown-lite-check.mjs`、`web/tools/finding-links-check.mjs`、`web/tools/plan-rationale-check.mjs`）加 i18n 审计、`npx tsc --noEmit`、`npm run build`，最后校验 `src/ai_pr_review/web_static` 与 `web/` 源码同步。
4. `tui`：Bun 下执行 `bun run typecheck` 与 `bun test src`。

## PR 描述模板

`.github/pull_request_template.md` 固定四段：Summary / Why / Validation / Notes；创建 PR 时把 `Validation` 的四条勾上。需要写得更完整时用下面的结构：

```md
## 功能描述

说明本 PR 新增、修改或修复了什么，以及它解决的问题。

## 使用方式

示例：`pr-review ...`

## 实现思路

- 简要说明核心实现逻辑。
- 说明关键技术选择。
- 如复用了历史代码或外部片段，注明来源。

## 测试方式

示例：`python -m pytest tests/test_cli.py -k "focused_keyword"`

## 依赖说明

- 是否新增第三方依赖：否
- 如有新增依赖，说明 `README.md` 中的对应更新。

## 原创性说明

本 PR 为本项目内新增实现，未复用外部代码。
```

## 建议的 PR 拆分方式

- `fix:` 保持行为稳定的缺陷修复。
- `feat:` 每个 PR 只做一个用户可感知功能。
- `docs:` 仅文档改动。
- `test:` 聚焦测试覆盖与验证补充。
- `chore:` 不改变行为的仓库维护事项。
