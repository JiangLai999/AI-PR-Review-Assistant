# 全项目验收矩阵（verification matrix）

> 用途：给评委/协作者**一眼看清**每个功能点在哪、怎么验的、证据是什么、哪些还没验。
> 产出方式：只读审计（阅读提交、交付报告、测试与帧证据后人工核对），不改任何源码/测试。
> 日期：2026-09-26 · 审计基线：当前工作区 HEAD（含 `2a8cc2b`/`13b8a08` 及之后的未提交 TUI 配置助手改动）。
> 状态口径：**✅ 已验证** / **⚠️ 部分验证** / **❌ 未验证** / **🔄 进行中**（当前仅 TUI 配置助手侧）。
> 原则：写"未验证"不丢人，虚报才是事故。凡证据不足一律降级标注。

---

## 1. 主矩阵

### 组 A · 上下文管理（后端，claude 主责）

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| A1 | 仓库文件按 finding 行号取窗口（`line_start ± 80`，锚点截断，诚实标注） | `src/ai_pr_review/backend/jsonl_server.py:2310`（`_collect_repo_files`）、`:2388`（`_finding_window`）、`:2442`（`_fit_lines`）、`:2490`（`_excerpt_note`） | 离线实测脚本 + pytest 用例 | `a26e88f`；`tests/test_jsonl_backend.py:5239`（窗口覆盖 237 行等 4 条）；交付报告 `docs/claude-chat-context-a.md` §1/§4 [A][B][C] | ✅ 已验证 |
| A2 | 会话落盘（`chat_session.json`，重启可续，`/new` 清空） | `src/ai_pr_review/chat_session.py:13,22,58,64`；`jsonl_server.py:2837`（`_restore_session_messages`）、`:2853`（`_persist_session`） | pytest 往返用例 | `a26e88f`；`tests/test_jsonl_backend.py:5385`（落盘字段集/恢复/绑定不恢复）；脚本 [D][E] | ✅ 已验证 |
| A3 | 历史窗口 80 条 + 裁剪明示 + `chat_context_budget` 可配 | `jsonl_server.py:291`（`CHAT_HISTORY_MESSAGE_LIMIT=80`）、`:2761`（`_trim_history`）、`:2055`（`_chat_context_budget`） | pytest + 离线实测 | `a26e88f`；`test_jsonl_backend.py`（80 条窗口/后缀提示/预算 1200 回退 8000）；脚本 [F][G] | ✅ 已验证 |
| A4 | 上下文超额 tips（`warning:"over_budget"` + 前端 zh/en 文案） | 后端 `jsonl_server.py`（`finished.warning`，`fa04897`）；前端 `frontend/tui/src/app.tsx:423,4915` | 契约 stub + manual 帧 | `fa04897`+`1c1a829`；`tests/test_chat_contract_events.py` 10 条；帧 `frame-over-budget-tip-en.txt`、`frame-contract-120x30.txt` | ✅ 已验证 |
| A5 | 上下文长度提示（优先 usage，缺失估算）`上下文 12% · 2.4k/20k` | 后端 `jsonl_server.py:2772`（`_chat_usage_payload`）；前端 `app.tsx:433`（`ContextUsageLine`）、`format.ts:70`（`formatContextUsage`） | 契约 stub + manual 帧 | `fa04897`+`1c1a829`；契约测试含 `context` **六键**（2026-09-26 扩展 `budget_source`）；帧 `frame-contract-120x30.txt`/`frame-contract-209x51.txt` | ✅ 已验证 |
| A6 | `/compact`（保留最近 10 轮原文 → 摘要替换；失败原历史不动） | `jsonl_server.py:292`（`CHAT_COMPACT_KEPT_TURNS=10`）、`:2897`（`_compact_chat_history`） | pytest 成功/失败两路径 + 契约 | `fa04897`；`test_jsonl_backend.py:5969`；契约 `test_contract_compact_*`（shape + failure） | ✅ 已验证 |
| A7 | `/history` 三模式（对话消息 / `--runs` / `<run_id>` 绑定） | `jsonl_server.py:2864`（`_chat_history_payload`）、命令分发 ~`:4011` 区 | pytest 三分支 + 契约 | `fa04897`；契约 `test_contract_history_*` 三条；`84b739e` 收尾修复（`effort` 字段） | ✅ 已验证 |

### 组 B · 模型配置（Codex 主责 + 后端收尾 + TUI 侧）

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| B1 | 模型规格字段与目录服务层（models.dev 归一化） | `src/ai_pr_review/services/model_catalog.py:25`（`PROVIDER_KEY_MAP`）、`:130`（`ModelCatalog`）、`:150`（`fetch`）、`:256`（`lookup`）、`:260`（`reasoning_summary`） | pytest（stub `urlopen`，不联网） | `3a0a694`；`tests/test_model_catalog.py` 15 passed；`docs/codex-model-catalog.md` | ✅ 已验证 |
| B2 | 目录接进配置助手（打开即取数、三出口同键、断网回退） | `jsonl_server.py:1110`（`_ensure_model_catalog`）、`:1042`（`_active_spec_block`）、`:1046`（`_model_spec_options`）；`config.py:659`（`resolve_model_spec`） | pytest（含事件循环不阻塞/失败回退/三出口一致） | `6a87fad`；`docs/claude-b2b3-impl.md` §1（22+1 条用例）；`docs/codex-model-catalog.md` | ✅ 已验证（后端） |
| B2-TUI | 配置助手 UI：规格屏 + source 徽标 + 可编辑 + needs_verification | `frontend/tui/src/app.tsx`、`setup-routing.ts`、`protocol.ts`（工作区未提交改动） | manual 帧断言 + `bun test` | 任务 `claude-config-wizard-fix`（**claimed，进行中**）；上游 `mimo-config-wizard-ui` 为 **blocked**（11 条 manual 回归） | 🔄 进行中 |
| B3 | 中转站逐项自定义（base_url/api_key/模型名/上下文/输出；custom 不套官方预设） | `config.py:522`（`from_model_provider(spec_overrides=...)`）、`:586`（`set_model_spec`） | pytest（落盘回显/不套预设/非法整单失败） | `6a87fad`；`docs/claude-b2b3-impl.md` §1.1 决策 5/7；`docs/claude-backend-followup.md` | ✅ 已验证（后端） |
| B-收尾 1 | 测试归位（C/D 组回 `test_config.py`/`test_cli.py`） | `tests/test_config.py:706,742`；`tests/test_cli.py:2628,2661,2740` | pytest 位置核对 + 数字对比 | `2a8cc2b`；`docs/claude-backend-followup.md` §1（456→466） | ✅ 已验证 |
| B-收尾 2 | `max_tokens` 跟随 `max_output`（只改 chat；本地/不可信例外） | `jsonl_server.py:1991`（`_chat_max_output`）、`:2059`（`_chat_max_tokens`） | pytest + 手工探针（8 种边界） | `2a8cc2b`；`docs/claude-backend-followup.md` §2/§5 表 #8 | ✅ 已验证 |
| B-收尾 3 | `config import` 未知键过滤（共用 `filter_dataclass_payload`） | `config.py:1300`（`filter_dataclass_payload`）；`config_entry.py:124` | pytest（导入含未来键 exit 0） | `2a8cc2b`；`docs/claude-backend-followup.md` §3 | ✅ 已验证 |
| B-收尾 4 | chat 预算与 `model_spec.context_window` 联动（三来源） | `jsonl_server.py:2011`（`_chat_context_budget_plan`）、`:302`（来源注释）、`:875`（`chat_context_budget_source`） | pytest + 手工探针（config/model_spec/fallback 三态） | `2a8cc2b`；`docs/claude-backend-followup.md` §4/§5 表 #7/#9 | ⚠️ 部分验证 |
| B-收尾 4b | `budget_source` 在 TUI `/context` 展示 | **无前端消费方**（`rg budget_source frontend/` 为空） | — | 后端已输出（`jsonl_server.py:2552,2580,2597`）；`docs/claude-backend-followup.md` §6.1/§6.5 明确记录未做 | ❌ 未验证 |

### 组 C · 渲染与交互（TUI，mimo 主责）

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| C1 | 表格按渲染宽度分档（窄 content/0 · 宽 full/0） | `frontend/tui/src/app.tsx:179`（`chatTableOptions`） | manual 帧断言（120×30 / 209×51） | `357e10f`+`bd1d358`（宽档 padding 改 0）；帧 `frame-table-120x30.txt`（宽 36）、`frame-table-209x51.txt`（宽 132）；`docs/mimo-chat-render-c.md` §1、`docs/mimo-chat-render-c3.md` §3 | ✅ 已验证 |
| C2 | 长代码块折叠（>15 行 + 角标 `▸ 展开（共 M 行）`） | `format.ts:219`（`CODE_FOLD_LINE_THRESHOLD=15`）、`:266`（`foldMarkdownCodeBlocks`）；`app.tsx:452`（`FoldableMarkdownBlock`） | manual 帧 + 纯函数单测 | `357e10f`；帧 `frame-code-fold-collapsed.txt`/`frame-code-fold-expanded.txt`；`format.test.ts` 8 条 | ✅ 已验证 |
| C2b | 角标可点击（`onMouseDown` 翻转）+ `Alt+L` 键盘保留 | `format.ts:327`（`splitFoldableMarkdown`）；`app.tsx:3793`（`toggleCodeFoldAt`） | manual 断言（G 组 7 条） | `bd1d358`；`docs/mimo-chat-render-c3.md` §1 | ✅ 已验证 |
| C3 | 流式动画（光标循环 + 等待 spinner + teardown） | `format.ts:121`（`cursorFrame`）、`:126`（`spinnerFrame`） | manual 帧（契约帧含流式态） | `1c1a829`；`docs/mimo-chat-frontend-c1.md` §2 | ✅ 已验证 |
| C4 | 回复耗时 `· 3.2s`（字段缺失不显示） | `format.ts:47`（`formatDurationSeconds`）；`app.tsx:413` | manual 帧（120×30/209×51） | `fa04897`+`1c1a829`；帧 `frame-contract-120x30.txt`（C4 耗时可见） | ✅ 已验证 |
| C5 | 思考内容独立展示（`ThinkingBlock`，落定折叠） | `app.tsx:369`（`ThinkingBlock`）；`protocol.ts:113`（`parseReasoningDelta`） | 契约隔离断言 + manual 帧 | `fa04897`+`1c1a829`；`test_contract_event_sequence_is_legal_and_reasoning_is_isolated`；帧 `frame-thinking-collapsed.txt` | ✅ 已验证 |
| C5b | 用户消息样式（橙色条 + `›` 前缀 + 深色底） | `app.tsx:4856-4869`（user 分支） | manual 断言（H 组 9 条） | `bd1d358`；帧 `frame-user-message-120x30.txt`/`frame-user-message-209x51.txt` | ✅ 已验证 |
| C5c | 宽屏表格紧凑化（`cellPadding` 1→0） | `app.tsx:179`（`chatTableOptions` 宽档） | manual 断言（I 组 3 条：行间无空行） | `bd1d358`；帧 `frame-table-209x51.txt` | ✅ 已验证 |
| C6 | 思考强度可选（`/think off\|low\|high\|max\|auto` + 档位预算预留 + 本地置灰） | `jsonl_server.py:2114`（`_chat_reasoning_effort`）、`:2755-2790`（预算与请求参数）、`:4115`（`/think` 分发）、`:2126`（`_apply_reasoning_params`）、`:2149`（`_think_result`）；`config.py:747`（`CHAT_REASONING_TOKEN_BUDGETS`）、`:962`（`normalize_chat_reasoning_effort`） | 契约 stub + **DeepSeek 真机** + 本地置灰用例 | `fa04897`；DeepSeek `c398808`（6/6）；本地 `7a5acae`；`docs/chat-deepseek-live-verification.md` §2/§3 | ⚠️ 部分验证 |
| C6b | **供应商差异化思考参数（数据驱动，19 家 + 本地）** | `services/reasoning_specs.py:145`（`REASONING_SPECS`）、`:486`（`reasoning_support`）、`:571`（`build_reasoning_params`）、`:619`（`covered_providers`）；`jsonl_server.py:2126`（两条注入通道 kwargs/`extra_params`）、`:2149`（三态 `set/transparent/unsupported`）；`config.py:747`（预算表单一来源）；`model_capabilities.py:23`（`reasoning_form` 转读规格表） | pytest：`tests/test_reasoning_specs.py` 105 条（19 家 × 四档映射 + unknown 兜底 + Anthropic 预算约束 + transparent）；`tests/test_jsonl_backend.py:5783`（**wire 级** stub `urlopen` 读请求体）、`:6000/:6055/:6080/:6100`（置灰/透传/三态） | 本次任务 `claude-reasoning-specs-impl`（未提交，工作区交付）；数据源 `docs/reasoning-specs-research.md`；实现口径 `docs/reasoning-specs.md`；全量 `python -m pytest -q --no-cov` → **1258 passed, 1 skipped**（2026-09-26，TEMP/TMP=`.pytest_claude`） | ✅ 已验证（文档级；**未做真机验证**，用户裁定） |

### 组 D · 探测工具

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| D1 | 思考档位探测脚本（R1 off / R2 mono / R3 budget / R4 verdict） | `scripts/probe_model_reasoning.py` | 本机 Ollama 实测 16/16 调用 | `85d5552`；`docs/model-reasoning-probe.md` §2/§4（verdict: `NOT-SUPPORTED / none`） | ✅ 已验证 |
| D2 | DeepSeek 思考强度裸 API 探测（对照组 + 单调性） | `_p5_verify/p6proto/probe_reasoning_effort.py`（外部验证目录，不在本仓 src） | 3 次/档实测均值 | `docs/reasoning-effort-probe.md`（disabled 0 < low 2624 < high 4509 < max 6834） | ✅ 已验证 |
| D3 | 供应商思考控制矩阵（四种参数模型对照） | 文档产物 | 文献+实测对照 | `docs/reasoning-effort-matrix.md`；`1e639c7` | ✅ 已验证 |

### 真实验收（真实链路，不打桩）

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| Live-Ollama | 本机 Ollama 链路（事件顺序/隔离/耗时/非空答案） | `scripts/verify_chat_live.py` + `JsonlBackend` + `OllamaProvider` | 真机脚本两轮 | `7a5acae`；`docs/chat-live-verification.md`（0.7s/46.3s，答案 61/4361 字符） | ⚠️ 部分验证 |
| Live-Ollama-usage | 本机 usage 真实性 | 同上 | 真机脚本 | `docs/chat-live-verification.md` §3 差异①：usage 三键**全 0**，只能走 `estimate_tokens` 估算 | ⚠️ 部分验证 |
| Live-DeepSeek | 云端四档思考强度端到端（`/think` 真实切换） | `scripts/verify_deepseek_live.py` + `JsonlBackend` + DeepSeek provider | 真机脚本 5 次调用 | `c398808`；`docs/chat-deepseek-live-verification.md`（off=0；2669<2891<11736；6/6 断言） | ✅ 已验证 |
| Live-review-think | **review 链路**的思考档位（现状语义 + 开启代价 + 独立档位落地 + **第二步后真机复验**） | 默认档 `off` = 现状：`structured_output=True` 经 `structured_review_params`（`review_policy.py:16` ← `model_capabilities.py:32`）追加 `thinking: {"type": "disabled"}`，**随供应商而异**（`ollama/local` 走 `think=False`；`anthropic` 与多数兼容供应商不发思考参数）。**第二步已落地**（`preferences.review_reasoning_effort`，默认 off）：注入点 `ai_client.py:192`（`_review_reasoning_plan`）/`:249`（预算封顶 +4000/+8000/+12000 受 `max_output` 封顶）/`:259`（封顶来源＝内置预设优先）/`:280`（两通道拆分，按请求建 provider 副本，不写落盘 `extra_params`）；通道判据 `services/reasoning_specs.py:616/631/650`；出口 `jsonl_server.py:912`（snapshot）/`:1337`（config.options）/`:1694`（config.setup）/`:1866`（model.status）；CLI `cli.py:3553` | 现状：**DeepSeek 真机脚本** `scripts/verify_review_reasoning.py`（4 场景 × 1 次调用，7/7）；第二步：**offline wire 断言** `tests/test_review_wire.py`（四档 × deepseek + 本地置灰 + 未收录/transparent 预设封顶/Anthropic 协议中转/qwen/anthropic 共 17 条）+ `tests/test_reasoning_specs.py` 4 条通道判据；**真机复验（2026-09-26）**：产品入口四档（短 diff + 382 行长 diff）+ 长 diff × max 边界，完成 8 次调用、**10/10 门禁全过** | `docs/review-reasoning-assessment.md` §2/§3（第一步真机）+ §9（第二步落点/wire 表）+ **§10（最新：四档数据 / 长 diff × max 预算边界 / §6 #3 收口 / §10.6 探针缺陷与调用预算）**；日志 `.pytest_claude/review-live-run4.utf8.log`（10/10，exit 0）、`.pytest_claude/review-live-run3.utf8.log` | ✅ 已验证（第二步 + 真机；余项 = `deepseek-chat`/中转/其它供应商未测、enabled-only 未测、TUI 未接入，见 §10.5） |

### 契约验收（stub，离线可复跑）

| 组 | 功能点 | 实现位置（文件:行，HEAD） | 验收方式 | 证据（提交/测试数字/帧） | 状态 |
|---|---|---|---|---|---|
| Contract-v1 | 契约 v1 端到端（事件序列/字段完整性/隔离/错误路径/命令结构） | `tests/test_chat_contract_events.py:140` 起 10 条 | pytest stub | `35f54c1`；10 passed；`docs/chat-contract-verification.md`（含前后端字段对照 25 行） | ✅ 已验证 |
| Contract-v1-fix | `/think` 字段名 `effort`↔`level` 不一致修复 | `84b739e`（后端读 `effort`） | 契约回归 | `docs/chat-contract-verification.md` §5.2 → `84b739e` | ✅ 已验证 |
| Contract-gap | 契约 `context` 是否含 `budget_source` | `jsonl_server.py` `_chat_context_payload`（**已扩键**：`context` 六键） | 契约 stub 十用例 + 全量 pytest | **已修复（主控）**：`assistant.finished.context.budget_source` 随事件下发（config\|model_spec\|fallback）；`tests/test_chat_contract_events.py` 与 `test_jsonl_backend.py` 同步为六键；文档 `codex-chat-backend-c1.md` §2 / `chat-contract-verification.md` 已更新 | ✅ 已验证 |

---

## 2. 必须点名的未验证 / 部分验证项（诚实清单）

| # | 项 | 现状 | 需补什么才能验证 |
|---|---|---|---|
| 1 | **review 链路思考档位** | **产品已拍板 (c)：(c) 两步走已全部落地，且第二步已真机复验**——第一步 wire 加锁（`tests/test_review_wire.py` 4 条）、第二步 `preferences.review_reasoning_effort`（默认 `off` = 现状）含请求注入/预算预留/三个出口（`docs/review-reasoning-assessment.md` §9）。**真机（2026-09-26，§10）**：产品入口四档 — 短/长 diff 下 `off` = 显式 `thinking: disabled` + reasoning 0 字符；长 diff 上 `low/high/max` reasoning 1931/7310/9828 字符（476/1877/2693 tok），耗时 6.0/13.9/20.7s；**长 diff × max 预算边界已收口**：completion 5139/20192 tok（余量 15053）、`finish_reason=stop`、答案 6393 字符、JSON 可解析，预留 +12000 只用了 22.4% | 剩余：① TUI 未接入该档位（前端另行排期）；② `deepseek-chat`/中转端点/其它供应商未测、`thinking: enabled` 不带 effort 未测（§10.5）；③ 小输出模型（`max_output ≤ 8192`）的"预留被吃光"缺提示文案（§10.7 建议，另开任务）；④ 既有向导丢字段问题（§9.4 #4，非本任务引入） |
| 2 | **组 B 的 TUI 侧合并** | `mimo-config-wizard-ui` = blocked（11 条 manual 回归）；`claude-config-wizard-fix` = claimed/**进行中** | 11 条断言全绿 + 补规格屏/source 徽标/中转站五项 manual 帧 + `docs/mimo-config-wizard-ui.md` 交付 |
| 3 | **`/context` 的 `budget_source` TUI 展示** | 后端已输出（`/context` 与 `config.snapshot`），前端**无消费方** | TUI 状态栏或 `/context` 回显加上 `budget_source`；补 manual 帧断言 |
| 4 | **Ollama usage 全 0** | 行为链路正常，但数值不可用于精确预算；本地占比提示是估算 | 改走 Ollama 原生 `/api/chat` 的 `prompt_eval_count`（另开任务），或接受"本地估算"并在 UI 标注 |
| 5 | **本地 reasoning 为空真** | `OllamaProvider.stream_chat` 强制 `think=False`（`docs/chat-live-verification.md` §3 差异②）；隔离断言不具区分力 | 产品决策已定"本地不开放思考"（`13b8a08`）；若未来开放，需真机验证 reasoning 隔离 |
| 6 | ~~**契约 `context.budget_source`**~~ | ~~不在契约 v1~~ | **已完成（主控，2026-09-26）**：契约扩为六键并同步文档与两处测试；TUI 消费见第 3 条（mimo 进行中） |
| 7 | **`max_output < 思考预留` 的档位降级** | 只封顶总额度，不自动降档；可能答案被思考挤空 | 产品决策是否自动降档（`docs/claude-backend-followup.md` §6.6）；补 `/think` 反馈文案 |
| 8 | **manual-route-wizard-check 首测 flaky** | 一次测量 `PASS=104 FAIL=2`，随后三次复跑均 `PASS=107 FAIL=0` | 若 `claude-config-wizard-fix` 收尾后仍偶发，需查焦点/时序；当前以 107/0 为准并记录波动 |
| 9 | **`/think` 的 `transparent` 态在 TUI 未渲染提示** | 后端已返回 `state:"transparent"` + `reason`（"是否生效取决于上游"）+ `form`/`doc_url`，但 TUI 只区分 `unsupported` 与"其它"（`app.tsx:887`），`transparent` 仍渲染成档位行 | 本次任务明确"不改前端"；前端排期后按 `state === "transparent"` 走一条提示文案（后端字段已就绪，无需再改后端） |

---

## 3. 测试总量汇总（最新真实数字）

> 环境：仓库根目录；`TEMP`/`TMP` = `<repo>\.pytest_mimo`；命令均带 `--no-cov`。
> 下表为**本次审计现场复跑**所得（2026-09-26），历史数字仅作出处备注。

### 3.1 Python 全量

| 命令 | 结果 | 出处 |
|---|---|---|
| `python -m pytest -q --no-cov` | **1299 passed, 1 skipped, 1 warning in 85.18s** | 任务 `claude-review-effort-step2` 复跑（`TEMP/TMP=.pytest_claude`；相对本次改动前 +41 条新用例：config 22 / review-wire 14 / jsonl-backend 5） |
| `python -m pytest -q --no-cov` | **1144 passed, 1 skipped, 1 warning in 91.99s** | 本次审计复跑（此前 `docs/claude-backend-followup.md` §5 记录 1143/1144 同口径） |

唯一 warning 来自既有用例故意喂非法偏好值（`test_chat_context_budget_can_be_set_in_the_config_file`），非回归。

### 3.2 Python 关键分文件（本次复跑）

> `claude-review-effort-step2` 复跑刷新了三行：`tests/test_jsonl_backend.py` **234 passed**、
> `tests/test_config.py` **171 passed**（旧值 224/149 是本次审计时的数字），并新增
> `tests/test_review_wire.py` **21 passed**、`tests/test_reasoning_specs.py` **109 passed**
> 两行（`TEMP/TMP=.pytest_claude`）。其余各行仍是本次审计的现场复跑记录。

| 文件 | 结果 |
|---|---|
| `tests/test_jsonl_backend.py` | **234 passed**（step2 复跑刷新，审计时为 224） |
| `tests/test_chat_contract_events.py` | **10 passed** |
| `tests/test_chat_commands.py` | **38 passed** |
| `tests/test_model_catalog.py` | **15 passed** |
| `tests/test_config.py` | **171 passed**（step2 复跑刷新，审计时为 149） |
| `tests/test_review_wire.py` | **21 passed**（step2 新增行：4 条第一步 + 17 条档位用例） |
| `tests/test_reasoning_specs.py` | **109 passed**（step2 新增行：+4 条通道判据用例） |

（历史对照：组 A 交付时全量 1036；契约验收时 1096；后端 C1 时 1057；后端收尾 456→466 三文件。）

### 3.3 前端 bun

| 命令 | 结果 | 出处 |
|---|---|---|
| `cd frontend/tui && bun run typecheck` | **exit 0** | 本次复跑 |
| `bun test src` | **171 pass / 0 fail / 830 expects / 13 files** | 本次复跑（历史：render-c 137、frontend-c1 155、render-c3 164） |

### 3.4 manual 帧断言

| 命令 | 结果 | 出处 |
|---|---|---|
| `bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx` | **PASS=75 FAIL=0 → ALL PASS** | 本次复跑 |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **PASS=107 FAIL=0 → ALL PASS** | 本次复跑（三次稳定；一次历史测量 104/2，见 §2 #8） |

帧证据目录（仍在，未清理）：

- `.pytest_mimo/ai-pr-review-chat-markdown/`：`frame-chat-markdown.txt`、`frame-code-fold-collapsed.txt`、`frame-code-fold-expanded.txt`、`frame-contract-120x30.txt`、`frame-contract-209x51.txt`、`frame-over-budget-tip-en.txt`、`frame-table-120x30.txt`、`frame-table-209x51.txt`、`frame-thinking-collapsed.txt`、`frame-user-message-120x30.txt`、`frame-user-message-209x51.txt`
- `.pytest_mimo/ai-pr-review-route-check/`：`frame-summary-zh.txt`、`frame-summary-local-zh.txt`、`frame-summary-preset-zh.txt`、`frame-local-endpoint-zh.txt`、`frame-route-chat-*.txt`、`frame-status-*.txt` 等

---

## 4. 复跑指引（可直接复制）

> 全部在仓库根目录执行。不要打印、不要提交任何密钥。

### 4.1 Python 全量与关键分文件

```powershell
$env:TEMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo'
$env:TMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo'
python -m pytest -q --no-cov
python -m pytest -q --no-cov tests/test_jsonl_backend.py
python -m pytest -q --no-cov tests/test_chat_contract_events.py
python -m pytest -q --no-cov tests/test_chat_commands.py
python -m pytest -q --no-cov tests/test_model_catalog.py
python -m pytest -q --no-cov tests/test_config.py
```

### 4.2 前端类型与单测

```powershell
cd frontend/tui
bun run typecheck
bun test src
```

### 4.3 manual 帧断言（生成/复核帧证据）

```powershell
$env:TEMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo'
$env:TMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo'
cd frontend/tui
bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx
bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx
```

### 4.4 真实链路（需本机 Ollama 或 DeepSeek 密钥）

```powershell
# 本机 Ollama（先确认 127.0.0.1:11434 在线）
python scripts/verify_chat_live.py --timeout 600
python scripts/verify_chat_live.py --json

# DeepSeek 云端（密钥只从环境变量读，绝不写入文档/命令行明文）
$env:DEEPSEEK_API_KEY='<your-key>'   # 本地设置，勿提交
python scripts/verify_deepseek_live.py
```

退出码约定：`0` 断言全过；`1` 有断言失败；`2` 环境不可用。

### 4.5 探测工具（组 D）

```powershell
# 本机 Ollama 思考档位探测（16 次调用）
python scripts/probe_model_reasoning.py --provider ollama --model qwen3.5:4b --trials 3 --json

# DeepSeek 裸 API 探测（外部脚本，需密钥）
# DEEPSEEK_API_KEY=... python _p5_verify/p6proto/probe_reasoning_effort.py
```

### 4.6 提交哈希复核

```powershell
git log --oneline -30
```

矩阵引用的提交均可在上表找到：`a26e88f` `3a0a694` `357e10f` `85d5552` `92d8d1e` `1c1a829` `fa04897` `9bdb158` `bd1d358` `6a87fad` `35f54c1` `84b739e` `917aa5c` `dc01535` `95a204a` `7a5acae` `c398808` `2a8cc2b` `13b8a08`。

---

## 5. 数据来源（本矩阵的证据出处）

1. 提交历史：`git log --oneline -30`（本文件 §4.6 引用的 19 个哈希）。
2. 方案与进度台账：`docs/chat-experience-plan.md` §0.1 / §5。
3. 交付报告：`docs/claude-chat-context-a.md`、`docs/codex-model-catalog.md`、`docs/mimo-chat-render-c.md`、`docs/mimo-chat-render-c3.md`、`docs/mimo-chat-frontend-c1.md`、`docs/codex-chat-backend-c1.md`、`docs/claude-b2b3-impl.md`、`docs/claude-backend-followup.md`、`docs/chat-contract-verification.md`、`docs/chat-live-verification.md`、`docs/chat-deepseek-live-verification.md`、`docs/model-reasoning-probe.md`、`docs/reasoning-effort-probe.md`、`docs/chat-features.md`。
4. 测试与帧证据：`tests/`（尤其 `test_jsonl_backend.py` / `test_chat_contract_events.py` / `test_chat_commands.py`）、`scripts/manual-*.tsx` 产生的帧目录（`.pytest_mimo/ai-pr-review-chat-markdown`、`.pytest_mimo/ai-pr-review-route-check`）。
5. 任务状态：`.agent-bus/tasks/`（`claude-config-wizard-fix` = claimed；`mimo-config-wizard-ui` = blocked）。

---

## 6. 一句话结论

**A 组 7/7、B 组后端 6/7、C 组 9/10、D 组 3/3、契约验收 3/4 已拿到可复核证据**；
当前唯一进行中项是 **TUI 配置助手侧（`claude-config-wizard-fix`）**；
诚实列出的未决里，**review 思考档位已拍板并落地**（(c) 两步走，默认 `off`，见 §2 #1）；
仍待产品拍板的是 **`budget_source` 是否进 TUI/契约**。
