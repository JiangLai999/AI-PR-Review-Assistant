# 参赛现场演示脚本

> 最后更新：2026-09-28 · 状态：参赛材料  
> 目标时长：3 分钟  
> 主路线：Web 工作台 + CLI 备援

## 0. 开场（10 秒）

一句话定位：

> AI PR Review Assistant 不是只调用一次模型，而是把 PR 审查变成一条包含规划、规则、证据验证、跨文件分析和历史复盘的本地工作流。

强调：

- 代码和审查结果默认保存在本机；
- 支持离线演示；
- 真实 PR 可以接入 GitHub 和 DeepSeek；
- 三个入口共用同一套审查内核：CLI（`pr-review`）、OpenTUI Chat（`pr-review chat`）、Web 工作台（`pr-review serve`）。

## 1. 离线 Demo（30 秒）

Web 路线：

1. 打开 `http://127.0.0.1:8787/static/`；
2. 点击概览页的“运行离线演示”；
3. 选择 `sql-injection`；
4. 展示风险等级、Finding、证据有效状态。

CLI 备援：

```bash
pr-review demo --list-cases
pr-review showcase
pr-review demo --case sql-injection
```

讲解重点：

- 不需要 GitHub Token；
- 不需要模型 API Key；
- 规则命中可以定位到真实文件和变更行；
- 证据状态是 `valid`。

## 2. 审查计划（30 秒）

```bash
pr-review plan <PR_URL>
```

或在 Web 审查工作台点击“生成审查计划”。

展示：

- 风险等级；
- 风险类别；
- 优先文件；
- 审查策略；
- 是否需要跨文件分析；
- 预计审查范围。

强调：

> 计划阶段不调用模型，可以先确认范围，再决定是否消耗模型成本。

## 3. 完整审查（40 秒）

```bash
pr-review <PR_URL> --verbose
```

或在 Web 点击“开始完整审查”。

展示：

1. 获取 PR 数据；
2. 过滤变更文件；
3. 构建代码上下文；
4. 静态 / AST 分析；
5. AI 结构化审查；
6. 证据校验；
7. 跨文件影响；
8. 写入历史记录。

## 4. 可信度与反馈（35 秒）

展示一个 Finding：

- 严重度；
- 文件和行号；
- 规则 / AST / AI 来源；
- 置信度；
- 证据状态；
- 代码片段；
- 人工反馈按钮。

证据状态与人工反馈是两件事，分别展示：

```text
证据状态：valid / needs_review / invalid / unverified
人工反馈：accepted / rejected / fixed / needs_review
```

强调：

> 系统不要求用户盲信模型，而是让用户看到结论是否真的落在当前 PR 的变更上。

## 5. 历史复盘与准确率（25 秒）

```bash
pr-review history
pr-review benchmark --strategy combined
```

Web 路线：

- 打开历史审查；
- 打开本次报告；
- 查看成本、耗时和反馈；
- 打开准确率页面。

说明 Benchmark 边界：

> 这是精选回归样例集成绩，用来防止规则退化和误报增加，不等同于真实 PR 泛化准确率。

## 6. 现场故障备援

### Web 服务未启动

```bash
pr-review serve
```

页面会显示“本地服务未连接”，点击“重新连接”。

### 没有 GitHub Token 或模型 Key

切换到离线 Demo，不影响主流程展示。

### 模型不可用或超时

切换到离线 Demo，并展示已准备好的 Benchmark 结果。

### Web 页面异常

使用 CLI 备援：

```bash
pr-review doctor
pr-review demo --case tls-disabled
pr-review demo --case clean-change
```

## 7. 备选桥段：Chat 工作区（时间允许时 30 秒）

```bash
pr-review chat          # 默认 OpenTUI；缺少 Bun / OpenTUI 时自动回退纯文本 CLI
```

在 Chat 中输入：

```text
/review https://github.com/owner/repo/pull/123   直接发起审查并绑定结果
/think high                                      思考档位（本地端点会置灰）
/history                                         审查历史；/history --chat 看对话
/context                                         查看或解除审查上下文绑定
Ctrl+O                                           打开 Findings 详情
```

讲解重点：

- Chat 不是孤立聊天：绑定审查结果后可继续追问 Finding、证据与修复建议；
- 会话可切换 / 重命名（`/sessions`、`/rename`），上下文可压缩（`/compact`）；
- 完整命令与界面差异见 `docs/chat-features.md`（TUI 与纯文本 CLI 的命令集合不同，文档已标注）。

## 8. 结束语（10 秒）

> AI PR Review Assistant 的重点不是让模型替代工程师，而是把模型、规则、证据和人工反馈组织成一个可以验证、可以复盘、可以落地的审查系统。
