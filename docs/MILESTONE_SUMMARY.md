# Milestone Summary

## Stage 1: Stability

- 修复 API Key 保存和配置持久化问题
- 修复 SQLite 连接生命周期问题
- 修复 CI 中的 black / isort / mypy 问题

## Stage 2: Explainability

- 增强过滤后无可审查文件时的 summary 解释
- 为 Markdown / JSON 报告增加过滤摘要

## Stage 3: Chat Workspace

- 新增 `pr-review chat`
- 支持 slash commands
- 支持 `/review`、`/history`、`/stats`
- 支持 chat 会话持久化与恢复
- 支持 `/session` 与历史表格展示

## Stage 4: Provider Diagnostics

- 新增 `config health`
- 新增 `config models`
- 新增 provider connectivity probe
- 增强模型发现失败时的 fallback 提示

## Stage 5: Modularization

- 抽出 provider diagnostics helpers
- 抽出 config helpers / wizard helpers / diagnostics helpers
- 抽出 chat session / chat command / chat runtime helpers
- 抽出 review command helpers 与 review entry
- 抽出 workspace / config entry helpers

## Current State

- 主流程可用
- 配置与诊断可用
- chat workspace 可用
- CI 已恢复
- 项目已进入展示和交付收口阶段
