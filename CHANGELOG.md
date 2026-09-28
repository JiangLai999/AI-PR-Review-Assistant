# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Added

- Review planner producing a transparent `ReviewPlan` (risk level, categories,
  priority files, strategies, cross-file requirement).
- Evidence validation for every finding (file, line range, changed-line check,
  code-snippet match) with `valid` / `needs_review` / `invalid` status.
- Python AST analyzer with syntax-level rules: mutable default arguments, bare
  `except`, `is` comparison against literals, unclosed resources, unsafe
  deserialization, `subprocess` with `shell=True`, disabled TLS verification,
  weak hash algorithms, and exceptions re-raised without `from`.
- Additional line-level rules: unsafe `yaml.load`, `verify=False`, hard-coded
  credential constants, and debug mode enabled in source.
- Cross-file symbol index and interface-impact analysis: signature comparison
  against the PR base revision plus external caller resolution.
- Real tree-sitter integration for Python, JavaScript and TypeScript behind the
  optional `ast` extra, with automatic regex fallback when unavailable.
- Benchmark subsystem (`pr-review benchmark`) with a curated known-defect case
  library and precision / recall / F1 / false-positive-rate / line-accuracy
  metrics.
- Productised local web workbench with risk overview, progress indicator,
  filterable findings list, evidence badges, human feedback buttons, review
  history, and report loading.
- New HTTP endpoints: `/api/history`, `/api/report`, `/api/feedback`.
- Finding feedback persistence (accepted / rejected / fixed / needs_review).
- Concurrent-safe AI budget reservation.

### Changed

- Finding merge deduplicates results that line-level and AST rules both report.
- CLI history and stats commands backed by SQLite result storage.
- GitHub comment rendering and publish flow for PR reviews.
- Website documentation hub with GSAP animations (`website/`).
- Chat workspace with ASCII-art UI, welcome message, and timestamp support.

### Fixed

- `ResultStore.save_result` failed on every call: the `metadata_json` column was
  missing from the schema and the INSERT placeholder count did not match the
  value tuple. Existing databases are migrated in place.
- CLI test doubles now use the real `FilterPipelineResult` type, which restored
  the full test suite.
- Pagination index in PR file fetching (0-based vs 1-based).
- Import ordering and black formatting for CI compliance.

### 2026-09-21 → 2026-09-28（P5–P7 轮：149 个提交按轮汇总）

#### Added

- 多会话与上下文压缩：`/sessions`、`/rename`、Alt+S 切换、按 token 计量的 `/compact`
  （保留最近 10 轮原文）、上下文压力提示；会话支持自动命名与重开续聊。
- 思考档位：chat 与 review 双通道 `/think`，按官方文档为 20 家 provider 写入 thinking
  参数（`services/reasoning_specs.py`），状态栏展示档位、思考内容可展开、回复底部带耗时与 token 指标。
- 模型目录：`models.dev` 驱动的模型规格（上下文窗口 / 输出上限）接入配置助手，支持自定义端点。
- Chat 与审查打通：`/context` 绑定某次 run、L3 覆盖全部 finding、仓库结构上下文注入。
- Web 工作台 Phase 2/3/3b：设置页对齐 CLI 六阶段、审查追问面板、全站中英双语；
  `web/tools/` 三道自测门禁（Markdown 渲染 / finding 链接 / 规划依据本地化）。
- 防漂移守卫：`tests/test_doc_links.py`（文档断链零容忍 + >200 条绊线）、
  `tests/test_website_docs.py`（官网标签页来源必须存在）。

#### Changed

- CI 扩到四个 job：Python 3.12/3.13 测试与门禁、Windows wheel 构建（拒绝错标的
  `py3-none-any`）、Node 前端（含 `web_static` 同步校验）、Bun TUI。
- `black==24.10.0` / `isort==5.13.2` 钉进 `dev` 依赖并全量格式化；本地必须用 pin 版本，
  否则会得到与 CI 相反的假红。
- local / remote 两个槽位共享 `CostLedger` 账本（刻意不共享 `CostController`），
  单次与 24 小时预算不再被按槽位数稀释。

#### Fixed

- hybrid 三处「看起来在跑、实际失效」的成本与路由缺陷：预算字段读错对象、
  逐文件新建客户端、复杂度评估被全局 findings 污染。
- Web 跨站守卫回 415 时未读请求体就关闭连接，触发 RST，客户端拿到
  `ConnectionAbortedError` 而不是 415 JSON。
- TUI 配置助手返回键失效、`/sessions` 首次不出列表、每次打开都新建会话。
- 25 条文档路径断链；`docs/PR_WORKFLOW.md` 被删除却仍在官网展示（幽灵文档）。
- 删除 11 处确认无引用的死代码（净 −135 行），并保留 1 条被误判的 Pydantic
  `@model_serializer` 钩子。

## [0.1.0] - 2026-05-30

### Added

- Initial CLI review workflow for GitHub Pull Requests.
- PR fetching, filtering, context building, prompt assembly, AI review, and report rendering.
- Test coverage for core services and CLI behavior.
