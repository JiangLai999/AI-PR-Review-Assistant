# PR Workflow Guide

This project uses small, single-purpose pull requests. The goal is to keep the
main branch runnable at all times and make every change easy to review.

## Rules

- Build new features through pull requests.
- Keep each PR focused on one feature, fix, or documentation change.
- Split large work into multiple independent PRs.
- Keep PR titles and descriptions aligned with the actual code changes.
- Do not submit empty PR descriptions.
- List any newly introduced third-party dependency in `README.md`.
- Mention reused code sources in the PR description when applicable.
- Verify that `main` remains runnable after each merge.

## Recommended Branch Flow

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/small-focused-change
```

After implementation and verification:

```bash
git status
git diff
git add <intended-files>
git commit -m "feat: describe one focused change"
git push -u origin feat/small-focused-change
```

Open a pull request against `main`.

## PR Description Template

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

## Suggested PR Split For Upcoming Work

- `fix:` bug fixes that keep behavior stable.
- `feat:` one user-facing feature per PR.
- `docs:` documentation-only updates.
- `test:` focused test coverage changes.
- `chore:` repository maintenance that does not change behavior.

## Verification Checklist

Before creating a PR, run the narrowest relevant test first, then a broader
check when the change touches shared behavior.

Common commands:

```bash
python -m pytest tests/test_cli.py
python -m pytest tests/test_result_store.py
python -m pytest
```

Also check:

- `git status --short`
- `git diff --stat`
- No secrets or local config files are staged.
- PR description matches the actual diff.
