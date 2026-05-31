# PR 工作流指南

本项目采用“小而专一”的 Pull Request 工作方式。目标是让 `main` 分支始终保持可运行，同时让每次改动都容易审查、容易回滚、容易定位问题。

## 规则

- 所有新功能、修复和文档更新都通过 PR 合入。
- 每个 PR 只聚焦一个明确目标：一个功能、一个修复或一组相关文档变更。
- 大任务必须拆成多个可以独立审查和合并的小 PR。
- PR 标题和描述必须与实际代码改动一致。
- 不要提交空的 PR 描述。
- 如果新增了第三方依赖，必须同步更新 `README.md`。
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

## PR 描述模板

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
- 如有新增依赖，说明 README 中的对应更新。

## 原创性说明

本 PR 为本项目内新增实现，未复用外部代码。
```

## 建议的 PR 拆分方式

- `fix:` 保持行为稳定的缺陷修复。
- `feat:` 每个 PR 只做一个用户可感知功能。
- `docs:` 仅文档改动。
- `test:` 聚焦测试覆盖与验证补充。
- `chore:` 不改变行为的仓库维护事项。

## 提交前验证清单

在创建 PR 之前，先运行最小相关测试，再根据改动范围扩大验证。

常用命令：

```bash
python -m pytest tests/test_cli.py
python -m pytest tests/test_result_store.py
python -m pytest
```

同时检查：

- `git status --short`
- `git diff --stat`
- 暂存区中没有密钥、token 或本地配置文件。
- PR 描述与实际 diff 保持一致。
