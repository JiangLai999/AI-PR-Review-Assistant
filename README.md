# AI PR Review Assistant

> 证据优先的 GitHub Pull Request 智能审查工作台 · CLI / OpenTUI / 本地 Web

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/JiangLai999/AI-PR-Review-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/JiangLai999/AI-PR-Review-Assistant/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/Coverage-87%25-green.svg)]()

🌐 **[项目官网（静态展示）](https://jianglai999.github.io/AI-PR-Review-Assistant-web/)** | 📖 **[完整文档](docs/PROJECT_DESIGN.md)** | 💡 **[创新点](docs/INNOVATION.md)**

🎬 **视频演示：** [【AI pr review 代码审查智能体】 · 哔哩哔哩](https://www.bilibili.com/video/BV1v9VZ6bE2G/?share_source=copy_web&vd_source=96df5919ae9bf8f3dc432bc3085a328f)

---

## 项目简介

AI PR Review Assistant 是一个基于 AI 的代码审查工具，通过智能分析 GitHub Pull Request 变更，自动发现潜在问题，帮助开发者提升代码审查效率与质量。

### 核心特性

- 🤖 **多模型支持** — 支持 18+ 模型供应商（OpenAI、Anthropic、DeepSeek、Qwen 等）
- 🧭 **智能审查规划** — 根据 PR 意图、风险关键词和文件变更动态生成审查计划
- ✅ **证据验证** — 校验 finding 的文件、行号、Diff 关联和代码片段，标记可信度状态
- 🔍 **规则 + AI 分析** — 将确定性安全规则与 AI 推理结果合并，支持跨文件影响信号
- 🎯 **智能过滤** — 自动跳过测试、文档、配置等不相关文件
- 📊 **结构化输出** — 终端彩色、Markdown、JSON、GitHub PR 评论
- 💰 **成本控制** — 单次运行和 24 小时窗口双重预算限制
- 💬 **聊天工作区** — 交互式终端聊天，支持斜杠命令
- 📦 **一键安装** — pipx / pip / curl 多种安装方式

---

## 零密钥体验（推荐先试）

```bash
pr-review doctor
pr-review demo --case sql-injection   # 内置样例：过滤、规划、静态规则、证据校验
pr-review serve                      # 本地启动 Web 工作台
```

在浏览器打开 `http://127.0.0.1:8787/`，于概览页运行离线 Demo。**这一步不需要 GitHub Token 或模型 API Key**；离线 Demo 不调用模型或 GitHub，也不会写入正式审查历史。上方官网链接只是静态展示站点，不是托管的审查后端。

要审查真实 PR，请先用下方配置助手填入**自己的** GitHub 与模型凭据，再输入 PR URL；CLI 与 Web 是同一审查能力的两种入口，不必对同一个 PR 重复审查。

---

## 项目截图

以下是实际运行界面截图（共 22 张；示例 PR 与审查记录仅用于展示交互，不代表基准准确率）。点击图片可查看原始分辨率。Web 设置页中的凭据局部信息已遮盖。

### 本地 Web 工作台

| 概览与演示入口 | 审查工作台 |
|:---:|:---:|
| [![Web 工作台概览](docs/screenshots/web-overview.png)](docs/screenshots/web-overview.png) | [![Web 审查工作台](docs/screenshots/web-review-workbench.png)](docs/screenshots/web-review-workbench.png) |

<details>
<summary>展开其余 Web 工作台截图（报告 / Finding / 历史 / 追问 / 设置 / 准确率 / 接口）</summary>

#### 审查报告与 Finding

![Web 审查报告](docs/screenshots/web-review-report.png)

![Web Finding 详情](docs/screenshots/web-finding-detail.png)

#### 历史、追问与统计

![Web 历史审查列表](docs/screenshots/web-history.png)

![Web 历史审查报告](docs/screenshots/web-history-report.png)

![Web 历史审查追问](docs/screenshots/web-review-followup.png)

![Web 准确率页面](docs/screenshots/web-benchmark.png)

#### 配置与接口

![Web 设置页（凭据局部信息已遮盖）](docs/screenshots/web-settings-redacted.png)

![Web 接口页面](docs/screenshots/web-api.png)

</details>

### OpenTUI 终端工作台

| 启动首页 | 审查工作台 |
|:---:|:---:|
| [![OpenTUI 首页](docs/screenshots/tui-home.jpg)](docs/screenshots/tui-home.jpg) | [![OpenTUI 审查工作台](docs/screenshots/tui-review-workbench.jpg)](docs/screenshots/tui-review-workbench.jpg) |

<details>
<summary>展开其余 OpenTUI 截图（会话 / Finding / Chat / 设置 / 发布评论）</summary>

#### 会话与审查发现

![OpenTUI 会话列表](docs/screenshots/tui-sessions.jpg)

![OpenTUI Findings 列表](docs/screenshots/tui-findings-list.jpg)

![OpenTUI Finding 详情](docs/screenshots/tui-finding-detail.jpg)

#### Chat 与模型配置

![OpenTUI Chat 对话](docs/screenshots/tui-chat.jpg)

![OpenTUI 审查报告对话分析](docs/screenshots/tui-review-chat.jpg)

![OpenTUI 配置运行模式](docs/screenshots/tui-setup-mode.jpg)

![OpenTUI 设置确认页](docs/screenshots/tui-setup-summary.jpg)

#### GitHub 发布

![OpenTUI 发布评论预览](docs/screenshots/tui-publish-preview.jpg)

![OpenTUI 发布成功](docs/screenshots/tui-publish-success.jpg)

![GitHub 评论展示](docs/screenshots/github-review-comment.png)

</details>

---

## 快速开始

### 安装

> ⚠️ 注意：PyPI 上的 `ai-pr-review` 是同名的其他项目，请从 GitHub 安装本项目。

```bash
# 方式 1：从 GitHub 安装（推荐）
pip install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"

# 方式 2：一行命令安装（Linux/macOS）
curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh

# 方式 3：一行命令安装（Windows PowerShell）
irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex

# 方式 4：从源码安装
git clone https://github.com/JiangLai999/AI-PR-Review-Assistant.git
cd AI-PR-Review-Assistant
pip install -e .

# 可选：启用 tree-sitter 语法级上下文（Python / JS / TS）
pip install -e ".[ast]"
```

### 配置

```bash
# 启动交互式配置向导
pr-review config

# 快速配置
pr-review config --quick

# 查看当前配置
pr-review config show

# 测试配置有效性
pr-review config test

# 检查供应商健康状态（--probe 会真实发起一次最小请求）
pr-review config health
pr-review config health --probe

# 发现可用模型并设为默认
pr-review config models
pr-review config models --set-first

# 切换默认模型
pr-review config model --name "模型名称"

# 查看或修改个人偏好
pr-review preferences
pr-review preferences --review-reasoning-effort high

# 预览审查计划（不调用 AI）
pr-review plan https://github.com/owner/repo/pull/123
```

### 使用

```bash
# 审查 PR
pr-review https://github.com/owner/repo/pull/123

# 指定模型审查
pr-review https://github.com/owner/repo/pull/123 --model gpt-4

# 输出为 Markdown 文件
pr-review https://github.com/owner/repo/pull/123 --format markdown --output report.md

# 发布为 GitHub PR 评论
pr-review https://github.com/owner/repo/pull/123 --publish-comment

# 干运行（不调用 AI）
pr-review https://github.com/owner/repo/pull/123 --dry-run

# 查看历史记录
pr-review history
pr-review history --json
pr-review history --table

# 查看统计信息
pr-review stats

# 记录人工反馈（用于误报/修复追踪）
pr-review feedback <run-id> <finding-id> --status accepted --note "确认问题"

# 离线演示规划、规则检查和证据验证
pr-review demo

# 输出比赛现场推荐演示路径
pr-review showcase
pr-review showcase --json-output

# 启动本地 Web 工作台
pr-review serve

# 体检当前环境（配置 / Token / 模型 / 存储 / Web 资产）
pr-review doctor

# 输出规划流水线耗时，排查慢在哪一步
pr-review trace https://github.com/owner/repo/pull/123

# 检查本地 Ollama 模型
pr-review local-model check

# 导出或解释历史 Run
pr-review export-run <run-id> --format markdown --output review.md
pr-review explain <run-id>
```

完整的命令、参数与退出行为见 [`docs/API.md`](docs/API.md)。

---

## 系统架构与审查流水线

CLI、OpenTUI 与本地 Web 工作台共用 Python 审查内核；项目官网是**静态展示入口**，不是托管的审查服务。下图为当前架构的可视化示意。

### 系统架构

![AI PR Review Assistant 当前系统架构：三种本地入口、共享审查内核、模型与规则分析、证据校验和结果存储](docs/assets/p2/project-architecture.png)

### PR 审查流程

![PR 审查流程：获取变更、过滤、上下文、规划、规则与模型分析、证据校验、报告和历史](docs/assets/p2/review-pipeline.png)

> 两张图使用 `gpt-image-2.5-sunburst` 生成，依据当前源码整理；具体步骤、边界与实现以源码和下方文字流程为准。

<details>
<summary>展开精确流程（文字版）</summary>

```text
真实 PR：GitHub PR URL
  → 获取变更 → 文件过滤 → 构建上下文 → 生成审查计划
  → 静态规则 / AST / 跨文件分析  ┐
  → AI 模型审查（可配置本地/云端、成本预算）┘ → 汇总 Findings
  → 文件 / 行号 / 代码片段证据校验 → 后处理
  → 终端、Markdown、JSON 或 GitHub 评论；SQLite 历史与人工反馈

离线 Demo：内置样例 → 文件过滤 → 审查规划 → 静态规则 → 证据校验
  （不调用 GitHub、不调用模型、不写入正式审查历史）
```

</details>

---

## Chat 工作区

```bash
# 进入聊天模式
pr-review chat

# 单条消息
pr-review chat --message "帮我总结这个 PR 的审查重点"

# 临时切换模型
pr-review chat --model "gpt-4" --message "你好"
```

### 斜杠命令

`pr-review chat` 默认打开 TUI（OpenTUI 交互界面）；缺少 Bun / OpenTUI 时自动回退到纯文本 CLI。
两套界面的命令集合并不完全相同，下表按界面标注可用范围（完整说明见 [docs/chat-features.md](docs/chat-features.md)）：

| 命令 | 说明 | 可用界面 |
|------|------|----------|
| `/help` | 显示当前界面的帮助信息 | TUI · CLI |
| `/status` | 显示运行状态 | TUI · CLI |
| `/model <ID>` | 查看或切换模型（`/model status` 检查连通性） | TUI · CLI |
| `/review <URL>` | 执行 PR 审查 | TUI · CLI |
| `/history [数量或 Run ID]` | 查看历史；CLI 列审查 Run，TUI 还支持 `/history --chat` 与 `/history <run_id>` | TUI · CLI |
| `/compact [指令]` | 压缩会话历史 | TUI · CLI |
| `/new` | 新建会话（旧会话保留，可在 `/sessions` 切回） | TUI · CLI |
| `/setup` | 打开配置助手（快捷键 `Ctrl+P`） | 仅 TUI |
| `/think off/low/high/max/auto` | 设置思考档位（本地端点置灰） | 仅 TUI |
| `/context [run_id]` | 查看 / 切换 / 解除审查上下文绑定（`/context off` 解绑） | 仅 TUI |
| `/cancel` | 取消当前对话或审查 | 仅 TUI |
| `/retry` | 重试上一次审查（快捷键 `Ctrl+R`） | 仅 TUI |
| `/report` | 查看当前审查报告（Markdown） | 仅 TUI |
| `/export json/markdown [路径]` | 导出当前报告 | 仅 TUI |
| `/explain <run_id>` | 解释该 Run 的问题与证据，不调用模型 | 仅 TUI |
| `/feedback <run_id> <finding_id> <status>` | 记录 Finding 反馈 | 仅 TUI |
| `/publish [run_id] [--confirm]` | 先预览、确认后再发布审查评论到 GitHub | 仅 TUI |
| `/demo [case_key]` | 运行离线演示用例（`/demo list` 列出全部） | 仅 TUI |
| `/showcase` | 查看参赛演示路径，不改变项目状态 | 仅 TUI |
| `/workbench` | 展开 / 收起审查工作台（快捷键 `Alt+W`） | 仅 TUI |
| `/sessions` | 打开会话列表（快捷键 `Alt+S`） | 仅 TUI |
| `/rename <新标题>` | 重命名当前会话 | 仅 TUI |
| `/usage` | 显示消息 / 字符统计 | 仅 CLI |
| `/stats` | 查看审查统计（Run 数、PR 数、Findings、成本） | 仅 CLI |
| `/config` | 显示当前会话配置（JSON） | 仅 CLI |
| `/session` | 显示当前 chat 会话信息（JSON） | 仅 CLI |
| `/restore` | 恢复上一次保存的会话记录 | 仅 CLI |
| `/clear` | 清空当前会话历史（含已保存记录） | 仅 CLI |
| `/exit` | 退出聊天（也接受 `exit` / `quit` / `q`） | 仅 CLI |

Chat 快捷键：`Ctrl+C` 在存在选区时复制到剪贴板；无选区时第一次提示、1.5 秒内再按一次退出；运行中按 `Ctrl+C` 取消当前任务。输入框内可用 `Ctrl+A` 全选。

Findings 详情：`Ctrl+O` 打开；没有 findings 时会提示先执行 `/review` 或 `/history <run_id>`。列表模式下 `↑↓` 选择、`←→` 翻页、`Ctrl/Alt+↑↓` 或 `PgUp/PgDn` 滚动详情；按 `Tab` 可把焦点切到详情，再用 `↑↓ / PgUp / PgDn / Home / End` 阅读完整问题、建议、证据和代码片段。

审查工作区（P5）：`Ctrl+F` 打开 Findings 筛选浮层，输入关键词实时过滤，`Tab` 切换严重级别、`Shift+Tab` 切换证据状态、`Ctrl+S` 切换排序，`Enter` 应用、`Esc` 清除并关闭。`Alt+P` 进入发布流程：先显示目标仓库、PR 编号、问题数与截断后的评论正文，只有再按一次 `Enter` 才会真正调用 GitHub API 发帖，`Esc` 取消且不写入任何内容。`Alt+D` 或 `/demo` 打开离线演示面板（不调用模型、不联网），`/showcase` 打开参赛演示路径。

Chat 内配置助手（`Ctrl+P` / `/setup`）为六段式：运行模式 → 模型服务与连接 → API Key / 本地模型 → 模型 → GitHub Token → 界面与输出偏好 → 确认保存。保存写入最高优先级私有配置，云端切换会保留远程槽与已保存 Key。

---

## 配置文件

配置文件位置：

- Windows：`%APPDATA%\ai-pr-review\config.json`（兼容旧版 `~/.ai_pr_review/config.json`）
- macOS / Linux：`~/.ai_pr_review/config.json`

项目级配置位于仓库根目录的 `.ai_pr_review/config.json`，私有覆盖配置位于 `.ai_pr_review/config.local.json`。

```json
{
  "provider": {
    "name": "custom",
    "display_name": "Custom Endpoint",
    "api_key": "sk-xxx",
    "base_url": "https://api.example.com/v1",
    "api_format": "openai",
    "default_model": "model-name"
  },
  "github_token": "ghp_xxx",
  "preferences": {
    "output_format": "terminal",
    "language": "zh-CN"
  },
  "ai_client": {
    "max_cost_per_run": 5.0,
    "max_cost_per_24h": 50.0
  }
}
```

### 配置加载与覆盖规则

配置文件按以下顺序加载，后加载的文件覆盖同名字段：

1. 用户级配置
2. 项目级配置 `.ai_pr_review/config.json`
3. 项目本地配置 `.ai_pr_review/config.local.json`

随后应用 `AI_PR_REVIEW_*` 和 `GITHUB_TOKEN` 环境变量覆盖。`--config <path>` 用于指定用户级配置文件路径，不会绕过环境变量覆盖。

> `hybrid_strategy`、`ui_language`、`chat_layout` 等属于个人偏好：在项目内通过 Chat / `pr-review config` 保存时，会写入最高优先级的 `.ai_pr_review/config.local.json`（私有且默认忽略），不会被项目共享的 `config.json` 重新覆盖。`pr-review config init` 生成的共享模板只包含 Provider 默认值，不再写个人偏好。

---

## 支持的模型供应商

| 供应商 | API 格式 | 说明 |
|--------|----------|------|
| OpenAI | openai | GPT 系列模型 |
| Anthropic | anthropic | Claude 系列模型 |
| DeepSeek | openai | DeepSeek 系列模型 |
| Qwen | openai | 通义千问系列 |
| SiliconFlow | openai | 硅基流动 |
| Moonshot | openai | 月之暗面 |
| Zhipu | openai | 智谱 AI |
| Baichuan | openai | 百川智能 |
| Minimax | openai | MiniMax |
| Stepfun | openai | 阶跃星辰 |
| Doubao | openai | 豆包 |
| Hunyuan | openai | 混元 |
| Yi | openai | 零一万物 |
| OpenRouter | openai | 多模型代理 |
| API2D | openai | 第三方代理 |
| CloseAI | openai | 第三方代理 |
| OhMyGPT | openai | 第三方代理 |
| Custom | openai | 自定义端点 |

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12+ | 主语言 |
| Click | CLI 框架 |
| Rich | 终端 UI |
| Pydantic | 数据验证 |
| PyGithub | GitHub API |
| Anthropic SDK | AI 模型调用 |
| AST 增强上下文 | Tree-sitter（可选，`pip install -e ".[ast]"`）→ 正则提取 → Diff 上下文降级 |
| Python AST 规则 | 标准库 `ast`，用于可变默认参数、裸异常等语法级检查 |
| SQLite | 本地存储 |
| React 18 + TypeScript | Web 工作台界面 |
| Vite 6 | 前端构建（产物随包分发） |
| GSAP | 官网展示页动画 |

> Web 工作台的前端构建产物已随包提交在 `src/ai_pr_review/web_static/`，
> 因此 `pip install` 之后**无需 Node** 即可用 `pr-review serve` 打开完整界面。
> 只有修改前端源码时才需要 Node。

---

## 项目结构

```
AI-PR-Review-Assistant/
├── src/ai_pr_review/
│   ├── cli.py                    # CLI 入口
│   ├── config.py                 # 配置管理
│   ├── config_wizard.py          # 配置向导
│   ├── chat_commands.py          # 聊天命令
│   ├── chat_runtime.py           # 聊天引擎
│   ├── web_server.py             # 本地 Web 服务端（标准库）
│   ├── web_static/               # Web 工作台构建产物（随包分发，无需 Node）
│   ├── models/
│   │   ├── pr_data.py            # PR 数据模型
│   │   └── review_plan.py        # 审查计划 / 证据 / 接口变更模型
│   ├── benchmark/                # 基准测试体系
│   │   ├── cases.py              # 已知缺陷样例库
│   │   ├── models.py             # 指标与报告模型
│   │   └── runner.py             # 评测执行器
│   ├── services/
│   │   ├── pr_fetcher.py         # PR 获取
│   │   ├── filter_pipeline.py    # 文件过滤
│   │   ├── context_builder.py    # 上下文构建（三级降级）
│   │   ├── prompt_assembler.py   # Prompt 组装
│   │   ├── ai_client.py          # AI 调用
│   │   ├── post_processor.py     # 后处理
│   │   ├── report_renderer.py    # 报告渲染
│   │   ├── result_store.py       # 结果存储
│   │   ├── review_orchestrator.py# 编排层
│   │   ├── cost_controller.py    # 成本控制
│   │   ├── agent/
│   │   │   └── planner.py        # 确定性审查规划
│   │   ├── analyzers/
│   │   │   ├── static_analyzer.py      # 逐行安全规则
│   │   │   ├── python_ast_analyzer.py  # Python AST 规则
│   │   │   ├── symbol_index.py         # 跨文件符号索引
│   │   │   ├── cross_file_interface.py # 接口影响分析
│   │   │   ├── cross_file_analyzer.py  # 轻量关系信号
│   │   │   └── finding_merge.py        # 结果去重合并
│   │   ├── evidence/
│   │   │   └── finding_validator.py    # 证据校验
│   │   └── model_providers/      # 多供应商适配
│   └── utils/
│       └── github_url_parser.py  # URL 解析
├── tests/                        # 测试套件
├── docs/                         # 文档
│   ├── PROJECT_DESIGN.md         # 项目设计书
│   ├── INNOVATION.md             # 创新点文档
│   ├── API.md                    # API 文档
│   └── RELEASE.md                # 发布说明
├── website/                      # 前端展示页面（官网，纯静态）
│   ├── index.html
│   ├── css/style.css
│   └── js/main.js
├── web/                          # Web 工作台前端源码（React + Vite）
│   ├── src/
│   │   ├── api/                  # 接口客户端与类型契约
│   │   ├── components/           # 组件与设计体系
│   │   ├── pages/                # 概览 / 审查 / 历史 / 准确率 / 接口
│   │   └── styles/               # DSH 设计令牌与组件样式
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── pyproject.toml                # 包配置
├── README.md                     # 本文件
├── CHANGELOG.md                  # 变更日志
├── CONTRIBUTING.md               # 贡献指南
└── LICENSE                       # MIT 许可证
```

---

## 智能审查增强

完整审查现在会生成透明的 `ReviewPlan`，并在模型结果之后执行：

- 静态安全规则检查（动态执行、HTML 注入、硬编码凭证、SQL 插值等）
- Python AST 规则（可变默认参数、裸 except、`is` 字面量比较、未关闭资源、
  危险反序列化、`shell=True`、关闭 TLS 校验、弱哈希、异常链丢失等）
- Finding 证据验证（文件、行号、变更行、代码片段）
- 跨文件符号级接口影响分析（签名对比 + 外部调用方定位）
- 并发安全的 AI 预算预留
- SQLite 中的 Finding 人工反馈记录

可以先使用 `pr-review plan <PR_URL>` 查看审查范围，再执行完整审查。

### Web 工作台

```bash
pr-review serve            # 默认 http://127.0.0.1:8787
```

界面包含 6 个视图：

| 视图 | 内容 |
|------|------|
| **概览** | 产品定位、审查流水线八步、关键能力、实时统计数据、基准准确率 |
| **审查工作台** | PR 链接输入、计划/完整审查、风险总览指标、审查计划、证据校验、文件过滤、跨文件接口影响、可筛选 Findings、人工反馈、原始 JSON |
| **历史审查** | 运行记录表、聚合统计、按运行 ID 载入完整报告 |
| **准确率** | 三种策略对比、混淆矩阵、逐样例指标 |
| **接口** | HTTP 接口与 CLI 命令参考、运行边界说明（完整契约见 [`docs/API.md`](docs/API.md)） |
| **设置** | Provider / 模型 / Token 配置、连通性探测 |

Web 工作台共暴露 **18 条 API + 静态资源**，逐条契约、错误码与 curl 示例见 [`docs/API.md`](docs/API.md)。

前端为 React + Vite 应用，**构建产物随包分发**，因此普通用户无需 Node：

```bash
# 仅修改前端源码时才需要
cd web && npm install && npm run build   # 输出到 src/ai_pr_review/web_static/
```

### 三级上下文降级

```
Level 1: tree-sitter 语法树（需安装可选依赖 ".[ast]"）
Level 2: 正则提取
Level 3: 仅 diff 上下文
```

未安装 tree-sitter 时自动降级到正则，不影响运行。

### 基准测试

内置已知缺陷样例库，用于量化分析策略并防止规则退化：

```bash
pr-review benchmark                  # 默认 combined 策略
pr-review benchmark --strategy all   # 横向比较 static / ast / combined
pr-review benchmark --json-output    # 完整 JSON 明细
```

当前样例库（4 个样例、12 处已知缺陷、1 个对照组）在 `combined` 策略下的
实测结果为 Precision 1.00 / Recall 1.00 / Line accuracy 1.00。

> 这是**精选回归样例集**的成绩，用于保证规则不退化、误报不增加，
> 不等同于在真实 PR 上的泛化准确率。

## 测试与质量

```bash
# 运行测试
pytest

# 代码格式化检查
black --check src tests

# 导入排序检查
isort --check-only src tests

# 类型检查
mypy src
```

### 测试覆盖率

下表是 2026-09-28 在本机按第二列命令实测的结果；**CI 是最终口径**，徽章与 CI 输出为准。

| 层 | 命令 | 实测结果 |
|----|------|----------|
| Python 全量 | `pytest`（默认带 `--cov`） | **1514 passed + 1 xfailed**（1515 collected），语句覆盖率 **87%**（12,947 statements / 1,677 miss） |
| 类型检查 | `mypy src` | clean（89 source files） |
| 格式门禁 | `black --check src tests` / `isort --check-only src tests`（pin `24.10.0` / `5.13.2`） | 138 files clean |
| TUI（OpenTUI） | `bun test src` | 222 pass / 0 fail（13 files / 1101 断言） |
| Web 自测门禁 | `node tools/markdown-lite-check.mjs` 等三道 | 118 断言 ALL PASS（53 + 45 + 20） |
| 文档 / 官网守卫 | `pytest tests/test_doc_links.py tests/test_website_docs.py` | 6 passed + 1 xfailed |

> 历史上这里有一张按模块手写的用例数表（合计 270），它早已与实际套件脱节、容易误导，已删除；
> 需要更细的口径请直接看 CI 里 `pytest` 的输出与 `pytest --cov` 的逐文件表。

---

## 合规、原创性与许可

- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) —— 第三方组件、字体与随包捆绑产物的
  许可总表（含版本、许可证、上游链接、证据来源），以及二进制 / 一体化分发注意事项。
- [`docs/COMPLIANCE_AND_ORIGINALITY.md`](docs/COMPLIANCE_AND_ORIGINALITY.md) —— 原创性与团队权属声明：
  团队主导与 AI 辅助的边界、参考项目边界、团队权属边界、第三方权利归属、AI 生成内容说明与提交前密钥清理清单。

提交前可运行 `python scripts/check_submission_hygiene.py`，检查提交包是否夹带本地凭据、
`.gitignore` 是否覆盖敏感模式，以及上述两份合规文档是否齐备。

> **第三方商标声明**：本项目在文档、界面与代码中提及 GitHub、Python、OpenAI、Anthropic、Claude、
> DeepSeek、Qwen、GLM、MiMo、OpenCode、OpenTUI、GSAP 等名称，**仅用于识别与说明**，
> **不表示任何合作、赞助、授权或背书**。上述名称的商标权归各自所有者所有，本项目不主张
> 任何第三方商标，也不主张任何第三方组件的所有权。
