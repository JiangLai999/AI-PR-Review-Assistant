# Web 审查工作台下一阶段方案（opencode 提案）

- 任务：`web-wb-opencode`（调度器认领，方向：**配置面与前端工程**）
- 性质：**方案商讨**，本文只写提案，未修改任何源码/配置/其它文档
- 审读方式：只读源码 + 在临时目录实跑最小复现（不触碰真实用户配置、不读取任何凭据）
- 日期：2026-09-27

---

## 0. 一句话结论

**"对齐 CLI 6 阶段"这件事，真正的瓶颈不在 UI，而在 `web_config.py` 的白名单：设置页今天提交的 `ui_language`/`output_format` 等键会被静默丢弃（已复现），而在 `hybrid_strategy=local_only` 下提交的 `base_url`/`model` 会先"保存成功"、再被 `_sync_runtime_sections()` 用本地槽位的值覆盖（已复现）。** 所以建议顺序是：先补 `web_config.py` 的偏好读写 + 报告被忽略的键（S/M），再做设置页 6 阶段分组（M），ApiPage 与漂移防护（M）可以并行，i18n（L）放在键位稳定之后。

另外要先纠正主控审计的一处结论：**缺口 7「CI 不构建前端」不成立**，`.github/workflows/ci.yml:46-82` 已经有完整的 `frontend` job（含 typecheck、build、"产物 == 已提交产物"校验）。真正缺的是 `frontend/tui` 的 CI 与该产物校验的一个盲区（见 §1.3、§4）。

---

## 1. 现状核对（file:line）

### 1.1 前端 `web/src/`（与主控审计逐条核对）

| 主控审计说法 | 核对结果 |
| --- | --- |
| `App.tsx` 侧边栏 + hash 路由 6 页 + 服务/凭证健康条 + 每页 ErrorBoundary | ✅ 成立：`web/src/App.tsx:18`（PageId 6 项）、`:20-27`（NAV）、`:67-71`（hashchange）、`:136-164`（statusbar：凭证 `:143-156` + 在线态 `:160-162`）、`:181-188`（`<ErrorBoundary key={page} scope={...}>` 每页兜底）、`:166-176`（服务未连接横幅） |
| `api/client.ts` 15 个 fetch | ⚠️ **实测 16 个方法**（`web/src/api/client.ts:64-128`：health/demoCases/demoRun/plan/review/history/meta/credentials/config/saveConfig/startReviewJob/job/cancelJob/report/feedback/benchmark）。覆盖面 **14/16 路径**，缺 `GET /api/jobs`（`web_server.py:126`，前端无人调用）与 `GET /api/jobs/{id}/events`（`web_server.py:330`，前端在 `web/src/pages/ReviewPage.tsx:204` 直接 `new EventSource(...)`，不经 client.ts） |
| pages 大小 Overview 16K / Review 30.8K / History 9K / Benchmark 12.6K / Api 7.2K / Settings 17.5K | ✅ 成立：16180 / 30824 / 9102 / 12628 / 7205 / 17461 字节 |
| `components/`：… `ui/ErrorBoundary` | ⚠️ 路径应为 **`web/src/components/ErrorBoundary.tsx:1`**（`App.tsx:6` 导入），`ui.tsx` 是组件库（Card/Section/Chip/Notice/Spinner/cx）。其余 ✅：ReviewPanels / FindingCard / DemoPanel / HeroKnot / ParticleBackground(21420B) |
| `styles/tokens.css`(11.6K) + `components.css`(57K) | ✅ 11644B / 57059B（378 行 / 1126 行） |
| `web/tools/*.mjs` 9 个 Playwright 脚本 | ✅ 正好 9 个 `.mjs`（audit-pages / measure-top / probe-layout / shoot-ref / shoot-report / shoot-slices / shoot / study-awwwards / trace-gap），另有 `_tmp_ui.cjs`、`_run_pr_web.ps1` |
| `vite.config.ts` base=`/static/`、outDir=`src/ai_pr_review/web_static`、dev 5173 代理 `/api`→8787 | ✅ 成立（`web/vite.config.ts:13-29`，含 `emptyOutDir: true`） |

规模基线（i18n 工作量依据）：`web/src` 共 **20 个文件 / 6105 行 / 4898 个汉字**；含汉字的 17 个文件里最大的是 `pages/ReviewPage.tsx`（977 汉字 / 810 行）、`pages/OverviewPage.tsx`（852 / 411）、`styles/components.css`（550 / 1126）、`pages/SettingsPage.tsx`（515 / 460）、`pages/ApiPage.tsx`（372 / 184）。

### 1.2 设置页与配置读写链路

- 前端可编辑面（`web/src/pages/SettingsPage.tsx`）：
  - `NUMERIC_FIELDS` **6 项**（`:8-15`）：max_tokens / timeout_seconds / review_concurrency / cross_file_max_files / max_cost_per_run / max_cost_per_24h
  - `BOOL_FIELDS` **2 项**（`:17-24`）：enable_static_analysis / enable_cross_file_review
  - 供应商预设下拉 + Base URL + 模型名 + API 格式 + API Key + GitHub Token（`:230-353`）
  - 保存载荷为**平铺键**（`:113-124`）：`provider_name, base_url, model, api_format, persist_secrets, validate, <6 numbers>, <2 bools>, api_key?, github_token?`
  - 凭证健康走 `GET /api/credentials`（`:85-106` 自动探测一次）
- 后端 `src/ai_pr_review/web_config.py`：
  - `EDITABLE_AI_FIELDS` **11 个键**（`:21-33`），与前端 6+2+4 完全对齐
  - `ConfigView`（`:36-65`）暴露：`config_path / github_token_set+masked / provider_name / base_url / model / api_format / api_key_set+masked / settings{11} / available_providers[]`
    —— **没有 `preferences`、没有 `runtime_profile`、没有槽位、没有每个 provider 的 `models[]`**（`available_providers` 只有 `name/display_name/base_url/api_format/default_model`，`:73-82`），因此前端模型名只能是自由文本（`SettingsPage.tsx:282-289`），也没有语言/输出格式等当前值可读。
  - `apply_config_update`（`:107-192`）：只遍历 11 键白名单（`:144-167`）+ `provider_name`（`:127-141`）+ `github_token`（`:170-173`）+ `api_key`（`:176-180`，带 `startswith("•")` 掩码保护）→ `config.save(target, save_key=persist_secrets)`（`:185`）。
- `web_server.py`：`GET /api/config`（`:121-125`）、`POST /api/config`（`:168-170` → `_handle_config_save` `:292-319`，`validate` 先跑凭证探测 `:294-304`，**失败即 400 不落盘**）。

### 1.3 主控审计的**遗漏/需修正项**（均给 file:line）

1. **缺口 7「CI 不构建前端」不成立。** `.github/workflows/ci.yml` 除 `test-and-quality`（`:10-44`，pytest/black/isort/mypy/build）外，**已有 `frontend` job**：`setup-node@v4` + `node-version: '22'` + npm 缓存（`:56-61`）、`npm ci`（`:63-64`）、`npx tsc --noEmit`（`:66-67`）、`npm run build`（`:69-70`）、以及"构建产物 == 已提交产物"校验（`:72-82`）。该文件 mtime 为 **2026-09-14**，早于本任务派发时间，非并行 agent 现场新增。
   → 真正剩下的 CI 缺口是：**`frontend/tui` 完全没有 CI**（`frontend/tui/package.json:7-13` 有 `typecheck`/`build`/`test` 三个脚本，ci.yml 无对应 job）；以及**该产物校验有盲区**（`git diff --quiet` 只看已跟踪文件，新增产物文件是 untracked、diff 为空 → 校验静默通过，`ci.yml:77`）。
2. **`client.ts` 是 16 个方法不是 15**（`web/src/api/client.ts:64-128`）；且未覆盖 `/api/jobs` 列表与 SSE（SSE 在 `ReviewPage.tsx:204`）。
3. **`ErrorBoundary` 位置**是 `web/src/components/ErrorBoundary.tsx:1`，不是 `components/ui/`。
4. **ApiPage 缺口的准确口径**：服务端 **16 个路径**（枚举见 §2.2），`ApiPage.tsx:11-57` 只列 **7 条** → 未文档化 **9 条**（meta / credentials / config(GET+POST) / demo/cases / demo/run / jobs / jobs/{id} / jobs/{id}/events / jobs/{id}/cancel）。
5. **"设置页比 CLI 少一半"是单向描述**：反方向上，Web 独有 8 项是 6 阶段助手**根本没有的**——`frontend/tui/src/app.tsx` 全文对 `max_tokens` / `timeout_seconds` / `review_concurrency` / `max_cost_per_run` / `enable_static_analysis` 均为 **0 命中**。所以"对齐"= 双向互补，不是把 Web 改成 CLI 的子集。
6. **配置面还有一个双方都没有的入口差异**：TUI 助手走 JSONL 协议 `config.setup`（`jsonl_server.py:4195-4196` → `_apply_setup` `:1586-1782`），Web 走 HTTP `POST /api/config` → `apply_config_update`。**两套校验规则目前不一致**（GitHub token 格式、枚举取值），见 §3。
7. 未列缺口：`GET /api/jobs` 前端无人使用（仅 `tests/test_web_server.py:420-424` 断言初始为空）；`/api/demo/*` 前端已接（`client.ts:67-70`）但 ApiPage 也没写。

---

## 2. 字段对照表 + 实现方案

### 2.1 CLI 6 阶段助手 ↔ Web 设置页 ↔ 后端支持

阶段名与屏→阶段映射来自 `frontend/tui/src/app.tsx:1761-1799`；助手落盘走 `config.setup`（`app.tsx:2340-2409` 载荷 → `jsonl_server.py:1586-1782`）。

| 阶段（stageNames） | 屏（SetupScreen） | `config.setup` 键 | 后端落点 | Web 现状 | 建议控件 |
| --- | --- | --- | --- | --- | --- |
| 1 运行模式 | runtime / route_chat / route_review | `runtime_profile`（必填，`jsonl_server:1588-1592` 校验 ∈ cloud/local/hybrid/offline/custom）；custom 时 `chat_slot`,`review_slot`（`:1690-1697`，词表 `config.py:792-793`） | `preferences.hybrid_strategy` / `chat_slot` / `review_slot` | ❌ 完全没有；`ConfigView` 也读不到当前 profile | 下拉（含"当前槽位"只读展示）+ 两个槽位下拉（仅 custom 显示） |
| 2 模型服务 | provider / base_url / api_format / local_base_url | `provider_name`,`base_url`,`api_format`；本地 `local_provider`,`local_base_url`,`local_api_format` | `config.provider` / `config.local_provider` | ✅ 云端三项有（`SettingsPage:230-307`）；❌ 本地槽位没有 | 预设下拉 + URL 文本 + 协议下拉（已有）；新增"本地 Ollama"分组 |
| 3 凭据与模型 | api_key / model / model_spec / custom_endpoint / local_model | `api_key`,`model_name`；规格 `context_window`,`max_output`,`local_context_window`,`local_max_output`（`setup-routing.ts:270-288`）；中转站 5 项（`setup-routing.ts:317-336`） | `config.provider.api_key`、`provider.models[name]`（`config.py:495-501`）、`provider_name="custom"` 分支 | ⚠️ 只有 `api_key` + 自由文本 `model`；❌ 规格、❌ 中转站三态 key、❌ 模型下拉 | 模型下拉（需后端返回 `models[]`）+ 2 个数字（规格）+ 中转站分组（key 三态：留空不改 / 填写写入 / `-` 清空） |
| 4 GitHub Token | github | `github_token`（`jsonl_server:1706-1710`，格式校验 `:1784-1791` 要求 `ghp_`/`github_pat_` 且 len≥40） | `config.github_token` + `pr_fetcher.github_token` | ⚠️ 有（`SettingsPage:329-352`），但**无任何格式校验** | 文本 + 保存前 `ghp_`/`github_pat_` 前缀与长度校验 |
| 5 界面与输出 | ui_language / response_language / output_format / auto_publish / chat_layout / workbench / repo_context / review_effort | `ui_language`,`response_language`,`output_format`,`auto_publish_comment`,`chat_layout`,`workbench_mode`,`repo_context`,`review_reasoning_effort`（`jsonl_server:1712-1770`） | `config.preferences.*`（`config.py:1079-1112`） | ❌ **全部缺失**（`ConfigView` 无 `preferences`） | 4 个下拉（语言×2、输出格式、chat 布局）+ 2 个开关（自动发评论、符号定位）+ 3 个下拉（工作台模式、仓库上下文、审查思考档位） |
| 6 确认保存 | summary | 整单提交 `config.setup`（`app.tsx:2409`），失败回跳出错屏（`:2413-2428`） | `config._sync_runtime_sections()` → `save(save_key=True)` → `AppConfig.load()`（`jsonl_server:1776-1780`） | ✅ 形式不同：常驻表单 + 「校验后保存 / 直接保存 / 放弃改动」（`SettingsPage:428-453`） | 保留常驻表单；保存后展示 `changed` 明细 |

**Web 独有、助手没有的 8 项**（白名单已支持，保留即可）：`max_tokens`、`timeout_seconds`、`review_concurrency`、`cross_file_max_files`、`max_cost_per_run`、`max_cost_per_24h`、`enable_static_analysis`、`enable_cross_file_review`（`web_config.py:21-33`）。

**双方都没有、但 `preferences` 里存在、`config.setup` 也不收的键**（只能改配置文件）：`repo_context_max_files`、`repo_context_budget_tokens`、`repo_cache_max_mb`、`chat_reasoning_effort`、`chat_context_budget`、`compaction_tail_tokens/trigger_ratio/auto`、`suggested_patch`、`model_catalog_fetch`、`max_cost_per_review`、`hybrid_strategy`（`config.py:1079-1112`；`config.setup` 只认 `jsonl_server:1712-1770` 列出的键）。
**例外**：`symbol_locate`（`config.py:1096`）**`config.setup` 支持写入**（`jsonl_server:1751-1754`）但 **TUI 没有对应屏**（`app.tsx` 的 `SetupScreen` 无此项，全文 `symbol_locate` 0 命中）→ Web 可以"先做"，成为唯一 GUI 入口。

### 2.2 后端改动点（建议顺序第 1 步，`src/ai_pr_review/web_config.py`）

1. **`ConfigView` 增补三块**（`web_config.py:36-65`）：
   - `preferences: dict[str, Any]` —— 由 `asdict(config.preferences)` 脱敏后给出当前值（供首屏回填与 i18n 语言选择）；
   - `options: dict` —— 枚举清单（`ui_languages`/`output_formats`/`chat_layouts`/`workbench_modes`/`repo_contexts`/`review_efforts`/`runtime_profiles`/`providers[].models`）。**强烈建议抽公共函数**与 `jsonl_server._setup_options()`（`jsonl_server.py:1279-1408`，枚举在 `:1324-1347`）共用一份，否则就是第二份会漂移的清单；
   - `runtime_profile: str` 与 `routing`（可复用 `_routing_snapshot()`，`jsonl_server.py:906`）。
2. **`apply_config_update` 增加偏好白名单**（新 `EDITABLE_PREFERENCE_FIELDS`），逐键校验词表：
   `ui_language`/`response_language` ∈ {zh-CN,en-US}（对齐 `jsonl_server:1715/1720`）、`output_format` ∈ {terminal,markdown,json}（`:1725`）、`chat_layout` ∈ {compact,split,plain}（`:1730`）、`workbench_mode` ∈ `config.WORKBENCH_MODES`（`:1736-1740` / `config.py:739`）、`repo_context` ∈ `REPO_CONTEXT_MODES`（`:1741-1750` / `config.py:810`）、`review_reasoning_effort` ∈ `REVIEW_REASONING_EFFORTS`（`:1755-1765` / `config.py:748`）、`auto_publish_comment`/`symbol_locate` 为 bool。
   归一化可直接复用 `config.py:1114-1134` 已有的 `normalize_*`（构造时即归一）。
3. **未知键不再静默丢弃**：`web_config.py:144-147` 现在对不在白名单的键直接 `continue`，建议返回 `ignored: [...]` 并在 `SaveResult` 里带上，界面据此提示"这几项本服务不支持"（这是本次实测到的 3 个坑之一，见 §3.1）。
4. **GitHub token 复用 TUI 校验**：把 `jsonl_server.py:1784-1791` 的 `_validate_github_token` 提为公共函数（建议放 `ai_pr_review/credentials.py` 或 `config.py`），Web 侧 `web_config.py:170-173` 调用；否则 TUI 拒绝的 token 会被 Web 写进配置文件。
5. **不动的两处**：`save(save_key=persist_secrets)`（`:185`）与掩码保护（`:177`）保持原样——这两处语义正确且有测试（`tests/test_credentials_and_jobs.py:232-258`、`tests/test_web_server.py:384-405`）。

### 2.3 设置页改动点（建议顺序第 2 步，`web/src/pages/SettingsPage.tsx`）

- 分组从现在的 4 个 `Section`（CREDENTIALS / PROVIDER / BEHAVIOUR / SAVE，`:177/:223/:357/:420`）改成与 6 阶段同构的 6 个 Section：
  `凭证健康` → `运行模式与槽位`（新） → `模型服务与凭据`（含本地槽位、中转站） → `GitHub Token`（新，从 PROVIDER 拆出） → `行为与成本`（现 BEHAVIOUR） → `界面与输出`（新） → `保存`。
  阶段编号可复用 `eyebrow`（如 `STAGE 5 · UI & OUTPUT`），视觉上即"对齐 6 阶段"，改动量远小于做真正的向导式分步。
- 控件类型：**下拉**（provider / api_format / runtime_profile / 4 个语言与格式 / workbench / repo_context / review_effort / 双槽位 / 模型）、**数字**（现有 6 项 + 规格 context_window/max_output）、**开关**（现有 2 项 + `auto_publish_comment` + `symbol_locate`）、**文本**（base_url / model / api_key / github_token / local_base_url）。
- 校验：数字项加 `min/max`（词表边界见 `config.py:826-833`：repo_context_max_files 1–10、context_window 1024–10_000_000、max_output 1–10_000_000）；下拉取值必须来自 `ConfigView.options`，前端不硬编码词表（`jsonl_server.py:1280-1284` 的注释即此意图）。
- 保存载荷：**继续用平铺键，但键名与 `config.setup` 保持一致**（`ui_language`、`output_format`、`auto_publish_comment`、`chat_layout`、`workbench_mode`、`repo_context`、`review_reasoning_effort`、`response_language`），避免出现第二套命名（现状的坑：前端发 `model`，TUI 发 `model_name`，两者都叫"模型名"但落到不同键，`web_config.py:25` / `jsonl_server.py:1626`）。
- `web/src/api/types.ts` 的 `ConfigView` 同步补 `preferences`/`options`/`runtime_profile`。

### 2.4 ApiPage 补全（16 端点信息结构 + 防漂移机制）

**信息结构**（每条 7 个字段）：`method / path / 描述 / 入参(query+body) / 出参(关键字段) / 错误码 / 示例`。

| # | 方法 | 路径 | 入参 | 出参要点 | 错误码（`web_server.py` 行号） |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/health` | – | `{ok, service}` | `:103-105` |
| 2 | GET | `/api/meta` | – | `{rule_count, provider_count, tree_sitter_available, cross_file_review_enabled, static_analysis_enabled, model, default_branch}` | 400 `:501-502`（`:482-502`） |
| 3 | GET | `/api/credentials` | `probe=1\|0` | `{items:[{key,label,ok,configured,detail,fix_hint}], ok}` | 400 `:289-290`（`:280-290`）；`probe=0` 只本地检查不发网络 |
| 4 | GET | `/api/config` | – | `ConfigView`（含 `settings{11}`、掩码、`available_providers`） | –（`:121-125`） |
| 5 | POST | `/api/config` | `provider_name, base_url, model, api_format, api_key, github_token, <11 白名单键>, persist_secrets, validate` | `{ok, changed[], message, save_key_used, config}` | 400 body 超 64KB `:145`；400 JSON 非法 `:149-151`；400 凭证校验失败 `:297-304`；400 落盘异常 `:307-309` |
| 6 | GET | `/api/history` | `limit`（1–200，默认 20） | `{runs[], statistics}` | 400 limit 非整数 `:411-413`（`:408-425`） |
| 7 | GET | `/api/report` | `run_id`（必填） | `{run_id, run, review, plan, validation, cross_file_impacts, interface_impacts, feedback}` | 400 缺 run_id `:429-431`；404 未知 run `:435-437`；400 其它 `:454-455` |
| 8 | GET | `/api/benchmark` | `strategy` ∈ static/ast/combined/all | 单策略报告或 `{name: report}` | 400 未知策略 `:469-477`（`:457-480`） |
| 9 | POST | `/api/plan` | `{pr_url}` | `{pr, filter, plan, validation, cross_file_impacts, interface_impacts, run}` | 400 缺 pr_url `:174-175`；400 异常 `:208-209` |
| 10 | POST | `/api/review` | `{pr_url, async_job?}` | 同上 + `review`；`async_job=true` → **202** `{job_id,...}` | 同上（`:179-207`） |
| 11 | POST | `/api/feedback` | `{run_id, finding_id, status, note}` | `{ok, run_id, finding_id, status}` | 400 缺字段 `:509-511`；404 未知 run `:514-516`；400 ValueError `:522-523` |
| 12 | GET | `/api/demo/cases` | – | `{cases:[...]}` | –（`:87-89`） |
| 13 | GET | `/api/demo/run` | `case`（默认 sql-injection） | demo 结果 | 404 未知 case `:96-97`；500 执行失败 `:98-101` |
| 14 | GET | `/api/jobs` | – | `{jobs:[最近 10 条 snapshot]}` | –（`:126-128`） |
| 15 | GET | `/api/jobs/{id}` | – | snapshot（完成时附 `result`） | 404 `:326-328` |
| 16 | GET | `/api/jobs/{id}/events` | – | **SSE**：`data: <snapshot>`，事件 `done/failed/cancel` 结束，15s 心跳 `: keep-alive` | 404 `:326-328`（`:367-402`） |
| 17 | POST | `/api/jobs/{id}/cancel` | `{}` | `{ok, job_id, message}` | 404 已结束/不存在 `:157-158` |

（16 个**路径**、17 个方法-路径对，因 `/api/config` 同时是 GET 与 POST。）

**防漂移机制（二选一，推荐 A）：**

- **A（推荐）单源清单**：新增 `src/ai_pr_review/web_api_manifest.py`，用一个 `ROUTES: tuple[Route, ...]`（`method/path/summary/params/response/errors`）描述上表；`web_server.py` 暴露 `GET /api/endpoints`（只读、无凭据、只回元数据），`ApiPage.tsx` 改为拉取渲染。
  同时加一条 pytest `tests/test_web_api_manifest.py`：正则扫 `web_server.py` 的路径字面量（本次已验证可扫到：`/api/benchmark|config|credentials|demo/cases|demo/run|feedback|health|history|jobs|meta|plan|report|review` 13 个字面量 + `/api/jobs/` 前缀 `:129/:153`，合起来正好 16 路径），与 manifest 双向比对，缺一即红。文档因此**不可能**再与路由表漂移，且 `ApiPage` 文案天然双语可扩展（配合 §2.5）。
- **B（最小，不动运行时）**：只加 pytest，比对 `web/src/pages/ApiPage.tsx:11-57` 的 `ENDPOINTS` 数组与 `web_server.py` 字面量；缺点是仍需人工同步 16 条描述，只能发现"漏了"，不能自动生成。

### 2.5 i18n 最小可行方案

- **词典**：`web/src/i18n/zh-CN.ts` + `web/src/i18n/en-US.ts`（扁平 key，如 `nav.overview`、`settings.api_key.hint`），导出 `Dict` 类型让缺 key 编译期报错（`tsconfig` 已是 `strict`）。
- **接入**：`LangProvider`（React Context）+ `useLang()` 返回 `{lang, t, setLang}`；`App.tsx` 顶部挂 Provider。**没有路由级切换开销**——当前是 hash 路由单页（`App.tsx:29-32`），换语言即整树重渲染。
- **语言来源与打通 `preferences.ui_language`**：首屏读 `GET /api/config` → `preferences.ui_language`（**依赖 §2.2 的 ConfigView 增补**），`localStorage` 仅作"本次会话覆盖"；在设置页保存 `ui_language` 时回写（`POST /api/config`），这样 TUI/CLI 改的语言 Web 会跟随，反之亦然。语言切换若要立即生效，需在 `setLang` 后回传 `POST /api/config {ui_language}`。
- **改造面（实测数字）**：`web/src` 20 文件 / 6105 行 / **4898 汉字**，含汉字的 17 个文件。分批建议：① `App.tsx`（199 汉字，导航/状态栏/横幅）② `components/ui.tsx`(64) + `ErrorBoundary.tsx`(167) ③ `SettingsPage`(515) + `ApiPage`(372) ④ `HistoryPage`(146) + `BenchmarkPage`(360) ⑤ `OverviewPage`(852) ⑥ `ReviewPage`(977，最大，放最后)。CSS 内 814 汉字（`components.css` 550 + `tokens.css` 264）需逐条判断是注释还是 `content:` 文案。
- **风险**：
  1. **服务端消息不会跟语言切换**：`web_config.py:183`「没有需要保存的改动。」、`:189`「已保存 N 项到 …」、`web_server.py:156`「已请求停止。」、`:299`「凭证校验未通过，未保存。」都是硬编码中文 → 建议响应加 `code` 字段、前端按 code 映射词典；后端已有按语言出文案的先例（`jsonl_server.py:2449`、`:3844`）。这属于**后端改动**，要排进同一批。
  2. **现状本就中英混排**：`App.tsx:139` `Review session`、`:158` `AI runtime`、`:161` `Connected/Offline`、`:122` `WORKSPACE`、`:120` `PR智审` → 需要先定"品牌词/技术词不翻"的规则，否则 en 版会出现"中文 + Connected"的割裂。
  3. **ErrorBoundary 的 `scope` 用了中文标签**（`App.tsx:181` `scope={NAV.find(...)?.label}`）：改成按 `page` id 传，否则语言切换会改变错误页标题/统计维度。
  4. GSAP 动画按 class 选择（`App.tsx:49-54`），不受文案影响 ✅；但任何"按可见文本查找元素"的 Playwright 脚本（`web/tools/audit-pages.mjs` 等 9 个）在 en 模式下会失配 → 视觉审计脚本必须加语言参数。
- **顺序**：在 §2.2/§2.3 键位与分组稳定**之后**做，否则新键位的文案要翻译两遍。

### 2.6 CI（修正后的建议）

现状（`ci.yml` 已有）：Python 3.12/3.13 矩阵 `test-and-quality`（`:10-44`）+ `frontend`（`:46-82`，node 22、`npm ci`、`tsc --noEmit`、`vite build`、产物同步校验）。建议只做 4 件小事：

1. **补 `frontend/tui` job**：`oven-sh/setup-bun` + `bun install` + `bun run typecheck` + `bun test src`（脚本见 `frontend/tui/package.json:7-13`）。注意 `scripts/hatch_build.py:27-35` 要求**在 Windows x64 上**才允许出 wheel，所以 ubuntu CI 只做 typecheck/test，**不要**在 ubuntu 上跑 `bun run stage`/`build` 后尝试打包。
2. **修产物校验盲区**：`ci.yml:77` 的 `git diff --quiet -- src/ai_pr_review/web_static` 对 untracked 新文件无效，改为 `git status --porcelain -- src/ai_pr_review/web_static` 非空即失败（新增 chunk 才会被抓到）。
3. **统一 Node 版本**：CI 用 `'22'`（`ci.yml:59`），本机实测 `v24.16.0` / npm `11.15.0` → 建议加 `web/.nvmrc`（或 `package.json#engines`）并让 CI 读同一来源，避免"本地构建产物在 CI 上被判不同步"。
4. **（可选，S）** Playwright 视觉审计 job：`npx playwright install --with-deps chromium` 后跑 `web/tools/audit-pages.mjs`（需要 `pr-review serve` 起后端，或用 `tests/test_web_server.py` 的 fixture 起服务）。建议放 nightly 而非 PR 必跑。

**"源码构建结果 == 已提交产物"要不要校验**：要——`src/ai_pr_review/web_static` 是随 pip 分发的界面（`web_server.py:6-7`、`web_server.py:32`、`pyproject.toml:64` `packages = ["src/ai_pr_review"]`），`web_server.py:222-230` 已有"产物缺失 → 503 + 提示重建"的兜底，但产物**过期**没有任何兜底（用户会看到旧界面）。当前校验方向正确，只需按第 2 点补盲区。

---

## 3. 风险与坑（均有代码证据；标注"已复现"的为本次实跑结果）

### 3.1 【已复现】`apply_config_update` 静默丢弃白名单外的键

- 证据：`web_config.py:144-147` 只遍历 `EDITABLE_AI_FIELDS`，其它键直接跳过；`SaveResult` 没有 `ignored` 字段。
- 实跑（临时目录，空密钥）：提交 `{"ui_language":"en-US","output_format":"json"}` → `ok=True, changed=[], message="没有需要保存的改动。"`——**用户以为保存了，实际一个字节没写**。
- 影响：任何直接把 TUI `config.setup` 载荷或"完整偏好"发给 `/api/config` 的尝试都会得到 200 + 空 `changed`。
- 对策：§2.2 第 3 点（返回 `ignored[]`），前端把 `ignored` 显示为"本页暂不支持"。

### 3.2 【已复现】`hybrid_strategy=local_only` 时，模型/端点修改被静默覆盖

- 证据链：`web_config.py:166-167` 先把值写进 `ai_client` → `:185` `config.save()` → `config.py:1678` `if active is self.provider` 才用 `ai_client` 重建 provider；当 `preferences.hybrid_strategy == "local_only"` 时 `_active_provider_config()` 返回 `local_provider`（`config.py:1486-1489`）→ 跳过重建 → `config.py:1697` `_sync_runtime_sections()` 用 **local 槽位**反向覆盖 `ai_client.model/base_url/api_format/api_key`（`config.py:1503-1521`）→ 落盘的 `ai_client` 是 Ollama 的值。
- 实跑：`hybrid_strategy="local_only"`，提交 `{"base_url":"https://new.example/v1","model":"new-model"}` → 返回 `changed=['base_url','model']`（**声称改成功**），但内存与磁盘均为 `http://127.0.0.1:11434/v1` / `qwen3.5:4b`。
- 影响：从 TUI 切到本地模式的用户，在 Web 设置页改云端端点会"保存成功但无效"，且 `changed` 明确骗人。
- 对策（三选一）：① Web 在 `runtime_profile=local` 时禁用云端字段并显示原因；② `apply_config_update` 里按 active slot 分流写入；③ `changed` 只在 `save()` 后重新比对得出。**建议 ①+③ 组合**（最小改动且诚实）。

### 3.3 `review_reasoning_effort` 必须写 `preferences`，不能写 `ai_client`

- 证据：`config.py:1511-1519` 在 `_sync_runtime_sections()` 里**强制**用 `preferences.review_reasoning_effort` 覆盖 `ai_client.review_reasoning_effort`，而 `save()` 每次都会调它（`config.py:1697`）。
- 实跑：设 `ai_client.review_reasoning_effort="high"` 后 `save()` → 落盘值仍是 `off`（= `preferences` 的默认值）。
- 结论：即便把 `review_reasoning_effort` 加进 `EDITABLE_AI_FIELDS` 也是**无效改动**（且会把 `changed` 报成真）。必须走 `preferences`。

### 3.4 掩码与"留空 = 不改"的语义要保持，但**无法显式清空**

- 证据：`web_config.py:176-180`（空串跳过 + `startswith("•")` 保护）、`github_token` 同理 `:170-173`；测试 `tests/test_credentials_and_jobs.py:232-258`、`tests/test_web_server.py:384-396` 锁定了该语义。
- 差异：TUI 中转站有**三态** key（`setup-routing.ts:293-343`：不填=不发、`-`=清空、其它=写入），Web 目前只有两态（留空=不改、填写=写入）→ Web **无法清除**已存的 API Key / Token。
- 对策：若要对齐三态，需要新增显式"清除密钥"按钮并让后端支持 `clear_api_key: true`（新键，须同步进白名单与 ApiPage 文档）。

### 3.5 两套校验规则不一致

- GitHub token：TUI 校验前缀+长度（`jsonl_server.py:1784-1791`），Web 完全不校验（`web_config.py:170-173`）→ 同一个 token 在 TUI 被拒、在 Web 被写进配置文件，下一次 TUI 打开助手才报错。
- 枚举词表：TUI 逐键校验并**整单失败**（`jsonl_server.py:1715-1765` 的注释明确"静默回退比报错更糟"），Web 侧目前根本没有枚举字段。
- 对策：把词表与校验函数提为共享（`config.py` 已有 `normalize_*`，`config.py:1114-1134`），两侧调用同一份。

### 3.6 `ConfigView` 无 `preferences` → i18n 首屏无法得知语言

- 证据：`web_config.py:36-65` / `web/src/api/types.ts` `ConfigView` 均无该字段；`web/src` 全文对 `ui_language`/`i18n`/`locale` **0 命中**（`useLang` 亦 0）。
- 影响：§2.5 的"与 `preferences.ui_language` 打通"必须先做后端增补，否则只能靠 `localStorage`，TUI 里改的语言 Web 感知不到。

### 3.7 构建与分发

- `vite.config.ts` `emptyOutDir: true` → 本地跑 `npm run build` 会**清空并重写** `src/ai_pr_review/web_static`（19 个文件 / 约 1.9 MB）——这是 write_scope 之外的文件，**本次未执行构建**（见 §5）。
- 产物校验盲区（untracked）见 §2.6 第 2 点。
- CI node 22 vs 本地 node 24 见 §2.6 第 3 点（是否真的造成字节差：**未确认**，需要实测两种 node 各构建一次比对）。

### 3.8 未确认项（明确标注）

- `available_providers` 缺 `models[]` 是否会导致"预设模型名与 `PROVIDER_MODEL_PRESETS` 不一致"：**未确认**（未比对两份清单）。
- 服务端中文消息改成 `code` 化是否会影响既有前端解析（`SettingsPage.tsx:128` 直接显示 `result.message`）：**未确认**，需补测试。
- 视觉审计脚本是否已按文案选择元素：**未确认**（未逐个读 9 个 `.mjs`）。

---

## 4. 优先级建议（7 条缺口重排 + "只做 3 件"）

| 排名 | 缺口 | 我的判断 | 工作量 |
| --- | --- | --- | --- |
| **P0** | ③ 设置页对齐 CLI 6 阶段 | 最高：配置面是 Web 唯一的用户可控入口，且**当前已有两个静默失败的真实缺陷**（§3.1、§3.2），先修正确性再补功能 | **L**（后端 S + 设置页 M + 测试 M；建议拆两个 PR） |
| **P0** | ④ ApiPage 只有 7/16 | 纯收益、零回归风险；配一条漂移测试即可永久防复发 | **M**（清单 B 方案 S） |
| **P1** | ⑦ CI 不构建前端 | **前提已被证伪**（`ci.yml:46-82` 已有）。剩余工作：补 `frontend/tui` job + 修 `git diff` 盲区 + Node 版本统一 | **S** |
| **P1** | ② 报告无导出/复制 | 体验缺口，且是"别人也想要"的能力（并行 agent `web-wb-claude` 覆盖此项） | **M** |
| **P2** | ⑤ 无 i18n | 价值高但触 17 个文件；必须在键位/分组稳定后做，否则返工 | **L** |
| **P2** | ⑥ 审查结果问答/会话 | 需要新会话存储与 SSE 复用（`/api/jobs/{id}/events` 模式可复用），并行 agent `web-wb-mimo` 覆盖 | **L** |
| **P3** | ① 无法发布评论到 GitHub | CLI 已有 `pr-review publish`（`publish_service.py`），但 Web 侧涉及权限、幂等、失败重试与审计，风险最高、依赖凭证真实可用 | **L** |

**"只做 3 件"选：③ 设置页对齐、④ ApiPage + 漂移防护、⑦ CI 加固。**

理由：
1. **③ 是唯一带"正在撒谎"的缺陷的条目**——`changed=['base_url']` 而磁盘没变（§3.2）、`ok=true` 而什么都没写（§3.1）。新功能可以晚，"保存成功但没保存"不能晚。
2. **④ 的性价比最高**：9/16 的文档缺口，B 方案一条 pytest 就能止血，A 方案再多花一点把文档变成运行时数据（顺带为 i18n 铺路）。
3. **⑦ 被误判为 L，实际是 S**——但正因为误判，"产物 == 源码"这条防线上的 `git diff` untracked 盲区没人看（`ci.yml:77`），而它守的是 `pip install` 后用户看到的界面是否过期（`web_server.py:222-230` 只兜"缺失"，不兜"过期"）。
4. ①②⑥ 都有并行 agent 在做或依赖真实凭证，我这票排后不等于它们不重要；⑤ i18n 排在 ③ 之后是**顺序**问题（先定键位再翻译），不是价值问题。

---

## 5. 验收方式（可执行命令与断言）

### 5.1 本次已执行（真实数字）

```powershell
# 1) 相关测试（TEMP/TMP 指向 .pytest_opencode）
$env:TEMP='C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_opencode'; $env:TMP=$env:TEMP
python -m pytest tests/test_web_server.py tests/test_credentials_and_jobs.py -q -p no:cacheprovider
#   → 81 passed in 25.59s   （收集数：test_web_server.py 45 + test_credentials_and_jobs.py 36）

# 2) 全量回归
python -m pytest -q -p no:cacheprovider
#   → 1365 passed, 1 skipped, 1 warning in 105.29s

# 3) 前端类型检查（只读，不产出文件）
cd web && npx tsc --noEmit     # → exit code 0

# 4) 配置写入探针（临时目录，未读取/输出任何凭据）
#   → 探针 A：local_only 下 changed=['base_url','model'] 但磁盘为 Ollama 值（§3.2）
#   → 探针 B：{"ui_language","output_format"} → ok=True changed=[] （§3.1）
#   → 探针 C：ai_client.review_reasoning_effort="high" 落盘后仍为 "off" （§3.3）
```

**未执行**（超出 write_scope 或需要外部资源）：`cd web && npm run build`（会清空并重写 `src/ai_pr_review/web_static`，该目录在 write_scope 之外）、`python -m build`、GitHub Actions 实跑、任何需要真实 token 的端点探测。

### 5.2 落地后应新增的断言（建议写进 PR 验收清单）

```powershell
# 后端
python -m pytest tests/test_web_config_preferences.py -q      # 新增
  # ├ GET /api/config 含 preferences.ui_language 且 == 配置值
  # ├ POST {"ui_language":"en-US"} → 200 且 "ui_language" in changed（当前实测 changed==[]）
  # ├ POST {"ui_language":"klingon"} → 400，且配置未被改写
  # ├ POST {"unknown_key":1} → 200 且 ignored==["unknown_key"]（当前被静默丢弃）
  # ├ hybrid_strategy=local_only 时 POST base_url → 重新 GET 得到的 base_url == 提交值
  # │   （当前实测：返回 changed 却落盘 Ollama 端点）
  # └ review_reasoning_effort 写入 preferences，save 后 ai_client 与 preferences 一致

python -m pytest tests/test_web_api_manifest.py -q           # 新增（漂移防护）
  # ├ web_server.py 路径字面量集合 == manifest 路径集合（当前 16 路径）
  # └ ApiPage 渲染的条目数 == 16（当前 7）

python -m pytest -q                                          # 全量不得回归 → 期望 1365 passed, 1 skipped
python -m black --check src && python -m isort --check-only src && mypy src   # 与 ci.yml:34-41 一致

# 前端
cd web && npx tsc --noEmit                                   # exit 0
cd web && npm run build                                      # 产物变更必须提交
git status --porcelain -- src/ai_pr_review/web_static        # 空 = 源码与产物同步（比 ci.yml:77 更严）
git diff --stat -- src/ai_pr_review/web_static               # 空

# i18n（落地后）
cd web && npx tsc --noEmit                                   # 缺 key 必须编译失败（Dict 类型）
node web/tools/audit-pages.mjs --lang=en                     # 6 页可见性断言全绿（脚本需加语言参数）
```

### 5.3 验收口径（每项"怎么算做完"）

| 项 | 完成判据 |
| --- | --- |
| 设置页 6 阶段 | 6 个 `Section` 覆盖 §2.1 表中"Web 现状 ❌"的每一行；保存后重新 GET，所有值与提交一致（含 `local_only` 场景） |
| 后端偏好读写 | §5.2 前 6 条断言全绿；`ignored` 可见于 UI |
| ApiPage 16 端点 | ApiPage 条目 == 16，含方法/入参/出参/错误码；漂移测试常绿 |
| i18n | `zh-CN`/`en-US` 下 6 页全可见（`audit-pages.mjs` 两轮）；切换语言后服务端消息按 `code` 翻译或明确标注"原文" |
| CI | `frontend/tui` job 绿；产物校验能捕获"新增未跟踪产物文件"；CI 与本地 Node 版本一致 |

---

## 6. 附：我建议的落地顺序（供主控排期）

1. **PR-1（S/M，正确性）**：`web_config.py` 加 `EDITABLE_PREFERENCE_FIELDS` + `ignored[]` + token/枚举校验共享化 + `ConfigView.preferences/options` + 4 条新测试；同步 `types.ts`。
2. **PR-2（S，CI）**：`ci.yml` 修 `git diff` 盲区 → `git status --porcelain`；加 `frontend/tui` job；加 `web/.nvmrc`。
3. **PR-3（M，ApiPage）**：`web_api_manifest.py` + `GET /api/endpoints` + 漂移测试；`ApiPage.tsx` 改为渲染清单。
4. **PR-4（M，设置页）**：`SettingsPage` 6 阶段分组 + 新控件 + `ignored` 提示 + `local_only` 禁用提示。
5. **PR-5（L，i18n）**：词典 + `useLang` + 按 §2.5 的 6 批顺序迁移 + 服务端消息 `code` 化。
