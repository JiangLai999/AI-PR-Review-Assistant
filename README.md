# AI PR Review 助手

一个面向 GitHub Pull Request 的 AI 辅助代码审查 CLI 工具。

当前仓库的重点是本地命令行工作流：拉取 PR 数据、过滤不适合审查的文件、为每个变更文件构建上下文、调用大模型生成结构化 finding，并把结果输出到终端、Markdown、JSON 或 GitHub PR 评论，同时把运行结果保存到本地 SQLite 历史库。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 项目状态

文档按当前仓库代码状态维护，下面明确区分三类能力：

- 已实现并接入主流程：直接可从 CLI 使用。
- 已实现但需要额外配置：代码已接入，但默认环境不一定自动启用。
- 计划中：README 只作为 roadmap，不代表功能已经可用。

## 已实现并接入主流程

- GitHub PR URL 解析与 PR 数据拉取。
- 基于 `PyGithub` 获取 PR 元数据、diff、文件列表和文件内容。
- 文件过滤管道：支持默认排除规则、纯删除过滤、大文件过滤、`force_include` 白名单。
- 文件级上下文构建：包含 diff、本地上下文窗口、imports/functions/classes 等结构化信息。
- Prompt 组装：包含基础规则、语言专项检查和 JSON Schema 输出约束。
- AI 审查执行：逐文件调用模型，返回结构化 `ReviewResult`。
- 成本估算与预算限制：在 AI 客户端内部做单次运行和 24h 窗口检查。
- 后处理：置信度阈值过滤和 finding 去重。
- CLI 输出：支持终端、Markdown、JSON。
- GitHub PR 评论发布：`--publish-comment` 使用专用评论模板渲染后发布。
- 交互式配置命令：`pr-review config`、`pr-review config show`、`pr-review config test`。
- 本地历史结果持久化：主流程会保存到 SQLite，可通过 `pr-review history`、`pr-review stats` 查询。

## 已实现但需要额外配置

- `tree-sitter` 上下文增强。
当前 `ContextBuilder` 的逻辑是“优先尝试 tree-sitter，失败后退回 regex”。仓库没有把 `tree-sitter` 作为默认安装依赖，也没有提供 grammar 安装流程，因此默认运行时通常会落到 `regex` 解析模式。

- 多模型 provider 预设。
仓库内置了 `anthropic`、`openai`、`deepseek`、`qwen`、`openrouter`、`api2d`、`closeai`、`ohmygpt`、`custom` 等 provider 预设，但是否可直接使用取决于相应 API Key、模型名和 base URL 配置。

## 计划中

- FastAPI / Web 应用形态。
- React 前端与实时进度展示。
- 增量 Review、更多模型路由策略、更多外部集成。

这些方向在仓库内有讨论文档，但不属于当前可运行的交付物。

## 当前工作流

```text
pr-review <PR URL>
  -> PRFetcher 拉取 PR 与文件内容
  -> FilterPipeline 过滤文件
  -> ContextBuilder 为每个文件构建上下文
  -> PromptAssembler 生成审查提示词
  -> AIClient 调用模型返回结构化结果
  -> PostProcessor 过滤和去重
  -> ResultStore 持久化运行结果
  -> ReportRenderer 输出终端 / Markdown / JSON / GitHub comment
```

## 快速开始

### 推荐安装：PyPI

CLI 工具最推荐使用 `pipx` 安装。它会自动创建隔离环境，并把 `pr-review` 命令暴露到 PATH。

```bash
pipx install ai-pr-review
```

如果你已经在自己的虚拟环境里，也可以使用：

```bash
pip install ai-pr-review
```

### GitHub 源安装

适合需要最新主分支代码、还没发布到 PyPI 的修复版本：

```bash
 pipx install "git+https://github.com/JiangLai999/AI-PR-Review-.git"
```

### 一行命令安装

Linux / macOS，默认从 PyPI 安装：

```bash
 curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-/main/install.sh | sh
```

Linux / macOS，强制从 GitHub 安装：

```bash
 curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-/main/install.sh | INSTALL_SOURCE=github GITHUB_REPOSITORY=JiangLai999/AI-PR-Review- sh
```

Windows PowerShell，默认从 PyPI 安装：

```powershell
 irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-/main/install.ps1 | iex
```

Windows PowerShell，强制从 GitHub 安装：

```powershell
 $env:INSTALL_SOURCE='github'; $env:GITHUB_REPOSITORY='JiangLai999/AI-PR-Review-'; irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-/main/install.ps1 | iex
```

安装完成后：

```bash
pr-review --help
pr-review config
```

### 从源码安装

```bash
 git clone https://github.com/JiangLai999/AI-PR-Review-.git
 cd AI-PR-Review-
pip install -e .
```

开发环境：

```bash
pip install -e .[dev]
```

### 配置优先级

`pr-review` 现在支持分层配置，推荐优先使用“项目配置 + 本地私有覆盖 + 环境变量”的组合，而不是把所有敏感信息都写进全局配置文件。

默认加载顺序如下，后者覆盖前者：

1. 用户级配置文件
2. 项目级 `.ai_pr_review/config.json`
3. 项目本地私有配置 `.ai_pr_review/config.local.json`
4. 环境变量
5. 命令行 `--config <path>` 指定的显式配置文件

可以通过 `pr-review config show` 查看当前解析后的配置以及实际使用的配置来源。

### 必需环境变量

至少需要：

- `GITHUB_TOKEN`：用于访问 GitHub PR 数据。
- 一个模型供应商 API Key：默认 provider 是 `anthropic`，如果切换 provider，则使用对应环境变量。

常见 provider 对应的环境变量：

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `OPENROUTER_API_KEY`
- `DASHSCOPE_API_KEY`
- `SILICONFLOW_API_KEY`
- `MOONSHOT_API_KEY`
- `ZHIPUAI_API_KEY`
- `BAICHUAN_API_KEY`
- `MINIMAX_API_KEY`
- `STEPFUN_API_KEY`
- `ARK_API_KEY`
- `HUNYUAN_API_KEY`
- `YI_API_KEY`
- `MODEL_PROVIDER_API_KEY`：`custom` provider 使用

也支持这些通用覆盖变量：

- `AI_PR_REVIEW_CONFIG`
- `AI_PR_REVIEW_PROVIDER`
- `AI_PR_REVIEW_MODEL`
- `AI_PR_REVIEW_API_KEY`
- `AI_PR_REVIEW_BASE_URL`
- `AI_PR_REVIEW_API_FORMAT`

示例：

```bash
export GITHUB_TOKEN="your_github_token"
export ANTHROPIC_API_KEY="your_anthropic_api_key"
```

`custom` provider 示例：

```bash
export GITHUB_TOKEN="your_github_token"
export MODEL_PROVIDER_API_KEY="your_custom_api_key"
export AI_PR_REVIEW_PROVIDER="custom"
export AI_PR_REVIEW_MODEL="mimo v2.5pro"
export AI_PR_REVIEW_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
```

### 配置模型供应商

项目默认 provider 是 `anthropic`，也可以通过交互式命令写入配置：

```bash
pr-review config --quick
pr-review config show
pr-review config test
```

如果是在仓库内初始化团队共享配置，推荐使用：

```bash
# 生成 .ai_pr_review/config.json、config.local.json.example，并更新 .gitignore
pr-review config init --provider deepseek

# 国内聚合模型示例
pr-review config init --provider siliconflow

# 自定义 OpenAI 兼容服务示例
pr-review config init \
  --provider custom \
  --model "mimo v2.5pro" \
  --base-url "https://token-plan-cn.xiaomimimo.com/v1" \
  --api-format openai
```

`config init` 默认不会把 API Key 写入项目配置文件。它会生成 `.ai_pr_review/config.local.json.example`，并把 `.ai_pr_review/config.local.json` 加入 `.gitignore`。

交互式向导第一步会询问界面语言、聊天布局和模型回复语言。当前支持中文和英文，后续也可以通过 `pr-review preferences` 调整。

交互式向导会在最后明确询问是否保存 API Key。默认选择“是”，这样完成配置后可以直接运行审查命令。

如果你不希望 API Key 写入配置文件，可以显式使用：

```bash
pr-review config --quick --no-save-key
```

选择不保存时，后续运行必须通过环境变量提供 API Key，例如 `DEEPSEEK_API_KEY`、`MODEL_PROVIDER_API_KEY` 或 `AI_PR_REVIEW_API_KEY`。

更推荐的实践是：

1. 把团队共享配置放进项目根目录下的 `.ai_pr_review/config.json`
2. 把个人私有覆盖放进 `.ai_pr_review/config.local.json`
3. 把 API Key 放进环境变量

示例项目配置：

```json
{
  "provider": {
    "name": "custom",
    "display_name": "Custom Endpoint",
    "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
    "api_format": "openai",
    "models": {
      "mimo v2.5pro": {
        "name": "mimo v2.5pro",
        "context_window": 32768,
        "max_output": 4096
      }
    },
    "default_model": "mimo v2.5pro"
  },
  "preferences": {
    "output_format": "terminal",
    "language": "zh-CN",
    "auto_publish_comment": false
  }
}
```

如果要针对单次命令使用自定义配置文件，也可以：

```bash
pr-review --config ./.ai_pr_review/config.local.json config show
pr-review --config ./custom-config.json https://github.com/owner/repo/pull/123
```

当前内置预设包括：`anthropic`、`openai`、`deepseek`、`qwen`、`siliconflow`、`moonshot`、`zhipu`、`baichuan`、`minimax`、`stepfun`、`doubao`、`hunyuan`、`yi`、`openrouter`、`api2d`、`closeai`、`ohmygpt`、`custom`。

### 使用

```bash
# 基本用法
pr-review https://github.com/owner/repo/pull/123

# 指定模型
pr-review https://github.com/owner/repo/pull/123 --model claude-sonnet-4-20250514

# 输出 Markdown 报告
pr-review https://github.com/owner/repo/pull/123 --format markdown --output report.md

# 输出 JSON 报告
pr-review https://github.com/owner/repo/pull/123 --format json --output report.json

# 仅抓取 PR 元数据
pr-review https://github.com/owner/repo/pull/123 --only-fetch

# 仅执行过滤并查看原因
pr-review https://github.com/owner/repo/pull/123 --only-filter --show-filter-reasons

# 发布评论到 GitHub PR
pr-review https://github.com/owner/repo/pull/123 --publish-comment --format markdown

# 查看历史记录与统计
pr-review history --limit 20
pr-review stats

# 使用自定义配置路径
pr-review --config ./.ai_pr_review/config.local.json config show

# 初始化项目级模型配置
pr-review config init --provider siliconflow

# 调整界面语言、模型回复语言和聊天布局
pr-review preferences --ui-language zh-CN --response-language zh-CN --chat-layout compact

# 进入轻量终端聊天框
pr-review chat

# 单次发送一条聊天消息
pr-review chat --message "帮我总结这个项目的审查重点"

# 如果服务商提示模型不支持，持久切换模型 ID
pr-review config model --name "服务商实际支持的模型ID"

# 尝试从当前 base_url + api_key 自动发现模型列表
pr-review config models

# 自动把远端返回的第一个模型设置为默认模型
pr-review config models --set-first

# 仅本次聊天临时切换模型 ID
pr-review chat --model "服务商实际支持的模型ID" --message "你好"

# custom provider 通过环境变量运行
MODEL_PROVIDER_API_KEY="your_custom_api_key" \
AI_PR_REVIEW_PROVIDER="custom" \
AI_PR_REVIEW_MODEL="mimo v2.5pro" \
AI_PR_REVIEW_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1" \
pr-review https://github.com/owner/repo/pull/123
```

## CLI 命令

### `pr-review <PR_URL>`

主审查命令支持以下选项：

- `--model`：覆盖当前配置的模型名。
- `--format [terminal|markdown|json]`：设置输出格式。
- `--output <path>`：把报告写入文件。
- `--publish-comment`：把 GitHub 评论格式的报告发布到 PR 评论区。
- `--verbose`：显示逐文件进度。
- `--dry-run`：抓取并过滤文件，但不调用模型。
- `--only-fetch`：只抓取 PR 元数据。
- `--only-filter`：只抓取和过滤文件。
- `--show-filter-reasons`：在 `--only-filter` 或 `--dry-run` 模式下输出过滤原因。

### 其他命令

- `pr-review config`：交互式配置 provider。
- `pr-review config init`：生成项目级配置模板和本地私有配置示例。
- `pr-review config model --name <model>`：快速切换当前配置的默认模型名。
- `pr-review config models`：通过当前 `base_url` 和 API Key 调用 OpenAI 兼容 `/models` 接口发现可用模型。
- `pr-review config show`：输出当前解析后的配置和配置来源。
- `pr-review config test`：校验当前解析后的配置是否合法。
- `pr-review preferences`：查看或调整界面语言、模型回复语言、聊天布局和默认输出格式。
- `pr-review chat`：使用当前模型配置进入轻量终端聊天框。
- `pr-review history`：查看 SQLite 中的历史运行。
- `pr-review stats`：查看历史统计信息。

全局选项：

- `--config <path>`：显式指定本次命令使用的配置文件路径。

更完整的发布与分发说明见 `docs/RELEASE.md`。

## 输出说明

当前主流程会输出：

- 审查摘要 `summary`
- 结构化 findings 列表
- 严重级别统计
- 终端文本、Markdown、JSON 或 GitHub PR 评论
- 本地持久化运行记录

finding 结构包含：

- `severity`
- `category`
- `file`
- `line_start` / `line_end`
- `title`
- `problem`
- `suggestion`
- `confidence`
- `code_snippet`

## 技术栈

### 当前实际使用

- Python 3.12
- click：CLI 框架
- PyGithub：GitHub API 访问
- pydantic：数据模型与校验
- rich：终端输出
- anthropic：默认 provider 对接依赖
- sqlite3：本地结果持久化

### 代码中已支持但不代表默认使用

- 多模型 provider 适配层：Anthropic、OpenAI 兼容接口及若干预设供应商
- tree-sitter：仅作为可选尝试路径，不在默认依赖中

### 当前未使用

- FastAPI
- React
- PostgreSQL
- WebSocket / SSE

这些技术此前更接近规划，而不是当前仓库的实际依赖或运行形态。

## 代码结构

```text
src/ai_pr_review/
  cli.py                      # CLI 入口与主流程编排
  config.py                   # 配置加载与 provider 预设
  models/pr_data.py           # PR 数据模型
  services/
    pr_fetcher.py             # GitHub PR 获取
    filter_pipeline.py        # 文件过滤
    context_builder.py        # 上下文构建
    prompt_assembler.py       # Prompt 与输出 schema
    ai_client.py              # 模型调用与成本控制
    post_processor.py         # finding 后处理
    report_renderer.py        # 终端 / Markdown / JSON / comment 渲染
    result_store.py           # SQLite 存储层
    review_orchestrator.py    # 主流程编排与结果持久化
```

## 测试与质量检查

```bash
pytest
black --check src tests
isort --check-only src tests
mypy src
```

仓库当前已经覆盖的重点包括：

- CLI 行为
- PR Fetcher
- Filter Pipeline
- Context Builder
- Prompt Assembler
- AI Client
- Post Processor
- Cost Controller
- Report Renderer
- Result Store
- Review Orchestrator

## 发布

- 包元数据见 `pyproject.toml`
- 发布步骤见 `docs/RELEASE.md`
- 辅助脚本见 `scripts/release.sh`
- CI/CD 工作流位于 `.github/workflows/`

## Roadmap

### 近期可落地方向

- 为 tree-sitter 增加真实可安装的 grammar 依赖与启用文档。
- 增加更清晰的运行日志和失败诊断信息。
- 改进历史记录查询和结果检索体验。

### 中期方向

- 支持更灵活的批量审查和配置文件管理。
- 细化模型路由和成本控制策略。
- 改进上下文切片策略，减少逐文件串行审查的延迟。

### 远期方向

- Web 服务形态。
- GitHub App / 更深度的 CI 集成。
- 增量 Review 与反馈闭环。

## 相关文档

- `docs/API.md`
- `docs/RELEASE.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `TRILATERAL_NEGOTIATION.md`
- `DEVELOPMENT_PLAN.md`
- `FINAL_DEVELOPMENT_PLAN.md`
- `OPTIMIZATION_PLAN.md`

这些文档主要记录接口说明、发布流程、协作规范和设计讨论，不应被视为“当前功能均已实现”的证明。

## 贡献

欢迎提交 issue 或 PR。提交前请优先遵循一个原则：

- 只写仓库当前真实可验证的能力。
- 对“代码存在但需要额外配置”的功能单独标注。
- 对规划项明确写成 roadmap，而不是已完成。
