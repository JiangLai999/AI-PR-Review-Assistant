# Phase 0.2：Web 配置写入三个静默缺陷（opencode 修复报告）

- 任务：`web-p0-config`（agent：opencode，基线：`docs/web-workbench-proposal-opencode.md` §3.1/§3.2/§3.3）
- 改动文件（均在 write_scope 内）：
  - `src/ai_pr_review/web_config.py`（主改动）
  - `tests/test_web_config_writes.py`（新建，7 个用例）
  - 本文档
- **未改动**：`web_server.py`、`config.py`、`web/src/**`、`tests/test_web_server.py`；未做任何 git 操作；未读取/输出任何凭据（测试里出现的 `sk-*` 均为合成值，且用 autouse fixture 清掉了环境变量里的真实密钥，见 `tests/test_web_config_writes.py:24`）。

---

## 1. 缺陷 1：白名单外的键被静默丢弃

### 根因（修复前的行号）

- `src/ai_pr_review/web_config.py:144-147`（旧）：`for name in EDITABLE_AI_FIELDS` 只遍历 11 个 `ai_client` 字段，其余键 `continue`；
- `SaveResult` 没有"拒绝"语义，`:182-183` 只要 `changed == []` 就返回 `ok=True, message="没有需要保存的改动。"`；
- 结果：`POST /api/config {"ui_language":"en-US"}` → `ok=true, changed=[]`，**用户以为保存了，实际一个字节没写**。

### 修复（`src/ai_pr_review/web_config.py`）

| 内容 | 位置 |
| --- | --- |
| 新增 `EDITABLE_PREFERENCE_FIELDS`（6 个偏好键：`ui_language`/`output_format`/`chat_layout`/`workbench_mode`/`repo_context`/`review_reasoning_effort`） | `:48-55` |
| `PREFERENCE_VOCABULARIES` 词表（config.py 拥有的 3 项直接引用常量） | `:64-71` |
| `ACCEPTED_PAYLOAD_KEYS` = AI 字段 + 偏好键 + 控制键（`provider_name`/`github_token`/`api_key`/`persist_secrets`/`validate`） | `:84-88` |
| 未知键**整体拒绝**：`SaveResult(ok=False, message="unsupported key: <k>")`，且发生在任何写入之前（不改内存、不落盘） | `:241-246` |
| `changed` 语义写进函数 docstring：只报"被接受 + 落盘读回校验通过"的键；`ok=False` 时恒为空 | `:207-234` |
| 顺带修掉同类的静默丢弃：`provider_name` 不在预设表 → `unsupported provider: <k>`；数值转不动 → `invalid value for <k>`；偏好词表外 → `invalid value for <k>（可选值：…）`（不回显原值，理由同 `config._warn_invalid_preference`） | `:248-257` / `:269-278` / `:294-296` |
| 回显键名前过 `_safe_token()`（去控制字符 + 截断 64 字符） | `:166-173` |

**刻意不暴露**：`response_language` / `auto_publish_comment` 不进白名单（交互式界面自动往 GitHub 发评论风险过高），提交即 `unsupported key` —— 见 `tests/test_web_config_writes.py:162`。

> `response_language`/`auto_publish_comment` 在修复前也**不在**白名单里，所以"若已在白名单则语义不变"这条不触发，本次没有回退任何既有语义。

---

## 2. 缺陷 2：`local_only` 下提交的 `base_url`/`model` 被 Ollama 值覆盖

### 根因（file:line，均在 `src/ai_pr_review/config.py`）

1. `config.py:1486-1489` `_active_provider_config()`：`hybrid_strategy == "local_only"` 且云端槽位不是 ollama/local 时，**生效槽位 = `local_provider`**；
2. `config.py:1678` `save()`：`if active is self.provider:` 才用 `ai_client` 重建云端槽位 —— local_only 下不重建（这是刻意的，见 `:1674-1677` 注释：防止云端配置被 Ollama 预设摧毁）；
3. `config.py:1697` `save()` → `_sync_runtime_sections()` → `config.py:1503-1510` **用生效槽位的值重建 `ai_client`**；
4. 旧 `web_config.py:166-167` 只把用户提交值写进 `ai_client`，`:185` 一调 `save()` 就被第 3 步用 `local_provider` 的 `http://127.0.0.1:11434/v1` / `qwen3.5:4b` 盖回去 → `changed=['base_url','model']` 是**假的**。

### 修复（不改 `config.py`，只改 `web_config.py`）

- **写"当前生效槽位"**：供应商预设的 `name/display_name/base_url/api_format` 改写 `_active_provider_config()` 返回的槽位，而不是写死 `config.provider` —— `web_config.py:304-317`；
- **端点三键镜像**：`base_url`/`api_format`/`model` 里"确实提交且确实变了"的键，同步写进生效槽位（`model` 写 `default_model` 并 `ensure_default_model_present()`）—— `web_config.py:324-336`；
- 未提交的字段保持生效槽位原值（= **显式提交优先，未提交才回落**）；`api_key` 仍由 `config.save():1670-1673` 双向同步，语义未动。

实测（HTTP 探针，`probe_http.py`）：

```
初始  ai_client: http://127.0.0.1:11434/v1 qwen3.5:4b | 云端槽位: anthropic
POST {base_url,model} -> HTTP 200 ok=True changed=['base_url','model']
落盘  ai_client: https://new.example/v1 new-model | local_provider: 同左 | 云端槽位: anthropic https://api.anthropic.com（未被改写）
GET /api/config -> https://new.example/v1 new-model | provider: ollama
```

### 为什么不动 `config.py`

- `config.py` 的两条规则都是**刻意设计且被 CLI/TUI 共用**：`:1674-1677` 的注释写明"只重建生效槽位，否则会永久摧毁用户的云端配置"；`:1511-1519` 的注释写明"review 档位以 preferences 为准"。`jsonl_server._apply_setup` 也在 save 前调 `_sync_runtime_sections()`（`backend/jsonl_server.py:1776`），改这两条会同时改掉 CLI/TUI 的保存语义与 1387 个既有用例的行为基线。
- 真正的缺陷在 Web 侧**只写了半份状态**：`ai_client` 只是"视图/缓存"，真源是槽位（`provider`/`local_provider`）与 `preferences`。所以修复放在 `web_config.py`：提交时把显式值写进生效槽位，让 `config.py` 既有的同步规则把结果原样落盘 —— CLI/TUI 零变化，改动只落在一个文件里。
- 结论：**本任务没有改 `config.py`**（也就没有触发"先报告再动手"的条件）。

---

## 3. 缺陷 3：`review_reasoning_effort` 写错段

### 根因

- `config.py:1511-1519` `_sync_runtime_sections()` **每次 save 都会用 `preferences.review_reasoning_effort` 覆盖 `ai_client.review_reasoning_effort`**，而 `config.py:1697` `save()` 必调它 → 写 `ai_client` 的值落盘后仍是 `off`（`config.py:749` 默认值）。

### 修复

- 6 个偏好键一律写 `config.preferences`（`web_config.py:338-342`）；`ai_client` 侧由 `save()` 里的 `_sync_runtime_sections()` 自动回填，两边读回一致；
- 落盘后由 `_read_back_mismatches()`（`web_config.py:176-202`）逐键读回磁盘比对，不一致直接 `ok=False` —— 这是"保存成功 == 磁盘真实"的兜底。

---

## 4. 用例（`tests/test_web_config_writes.py`，全部走临时 config 目录）

| 用例 | 行号 | 断言 |
| --- | --- | --- |
| `test_unknown_key_is_rejected_not_silently_dropped` | `:56` | `ok=False`、`message=="unsupported key: nope_unknown"`、`changed==[]`、**文件未创建**；随后 `{"ui_language":"en-US"}` → `ok=True` 且落 `preferences` |
| `test_ui_language_and_review_effort_persist_and_read_back` | `:78` | `preferences` + `ai_client` 两段落盘都是 `high`；`AppConfig.load()` 读回 `preferences`/`ai_client` 均为 `high`，`ui_language` 为 `en-US` |
| `test_local_only_does_not_override_explicit_base_url_and_model` | `:103` | 磁盘 `ai_client` 与 `local_provider` 的 `base_url`/`model` == 提交值；**云端槽位三项与提交前逐字相等**；`AppConfig.load()` 读回一致 |
| `test_blank_api_key_keeps_existing` | `:146` | `api_key:""` → `changed` 不含 `api_key`，内存与磁盘仍是原值（既有语义回归） |
| `test_keys_never_exposed_to_the_web_stay_unsupported` | `:162` | `auto_publish_comment` / `response_language` → `ok=False`、不落盘 |
| `test_invalid_preference_value_is_rejected` | `:175` | `ui_language:"klingon"` → `ok=False`、`message` 以 `invalid value for ui_language` 开头、不落盘 |
| `test_preference_vocabularies_do_not_drift_from_the_tui` | `:188` | 6 个词表 == `JsonlBackend._setup_options()` 的展示清单（防"第二份会漂移的清单"） |

---

## 5. 验证数字（真实执行）

```bash
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_config_writes.py -q --no-cov
#   → 7 passed in 0.75s

TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_server.py tests/test_credentials_and_jobs.py -q --no-cov
#   → 96 passed in 30.83s
#     （改动前同一命令基线：96 passed in 39.57s → 用例数不变，无回归；
#       提案里的"81 passed"是更早的基线，master 后续往 test_web_server.py 加过用例）

TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest -q --no-cov
#   → 1387 passed, 1 skipped, 1 warning in 104.95s

python -m mypy src          # （.venv313）→ Success: no issues found in 87 source files
python -m black --check src/ai_pr_review/web_config.py tests/test_web_config_writes.py   # → 2 files would be left unchanged
python -m isort --check-only src/ai_pr_review/web_config.py tests/test_web_config_writes.py  # → 通过
```

HTTP 端到端探针（`.pytest_opencode/probe_http.py`，临时 config、同源 Origin）：

| 探针 | 修复前（提案 §3 实测） | 修复后实测 |
| --- | --- | --- |
| `POST {"ui_language":"en-US"}` | `ok=true, changed=[]`（没写盘） | `HTTP 200 ok=True changed=['ui_language']`，落盘 `preferences.ui_language=="en-US"` |
| `POST {"nope_unknown":1}` | `ok=true, changed=[]`（静默丢弃） | `HTTP 200 ok=False message='unsupported key: nope_unknown'`（HTTP 码待 master 在 `web_server.py` 映射 400） |
| `POST {"base_url","model"}`（`local_only`） | `changed=['base_url','model']` 但磁盘是 Ollama 值 | `ok=True changed=['base_url','model']`，磁盘 `ai_client` 与 `local_provider` 均为提交值，云端槽位未被改写，`GET /api/config` 与磁盘一致 |
| `POST {"review_reasoning_effort":"high"}` | 落盘仍是 `off` | `changed=['review_reasoning_effort']`，落盘 `preferences=high`、`ai_client=high`，`AppConfig.load()` 读回 `high` |
| `POST {"ui_language":"klingon"}` | （未测） | `ok=False message='invalid value for ui_language（可选值：zh-CN、en-US）'`，不落盘 |

---

## 6. 未决项 / 未确认

1. **`web_server.py` 仍对 `ok=False` 返回 HTTP 200**（`web_server.py:310-319` 只回传 `ok` 字段）。主控约定由其在 web 侧把 `ok=False` 映射成 HTTP 400 —— 本任务按约束**没有改 `web_server.py`**，这一步待主控完成。
2. **`ConfigView` 仍不暴露 `preferences`/`options`/`runtime_profile`**（提案 §2.2/§3.6）。设置页因此还读不到当前 `ui_language` 等值；该增补不在本任务清单内，未做。
3. **GitHub token 格式校验 Web 侧仍缺失**（TUI 有 `jsonl_server._validate_github_token`，`backend/jsonl_server.py:1784-1791`）。提公共函数要改 `credentials.py`/`config.py`/`jsonl_server.py`，均超出 write_scope，**未做** → TUI 拒绝的 token 仍会被 Web 写进配置（提案 §3.5）。
4. **密钥仍是"两态"**（留空=不改、填写=写入），Web 无法显式清空 `api_key`/`github_token`（提案 §3.4）；需要新增 `clear_api_key` 之类的键并同步白名单，未做。
5. **槽位路由的边界**：`_active_provider_config()` 在"云端槽位本身就是 ollama/local"时会返回云端槽位（`config.py:1486-1489` 的刻意设计）。此时 `provider_name` 写云端槽位、端点镜像不触发 —— 行为与修复前一致。**未确认**这是否符合产品预期（Web 目前没有运行模式/双槽位入口，属设置页 6 阶段任务）。
6. **词表仍是两处字面量**：`ui_language`/`output_format`/`chat_layout` 在 `web_config.py:60-62` 与 `backend/jsonl_server.py:1329-1342` 各有一份（`config.py` 没有这三组常量）。本次用 `tests/test_web_config_writes.py:188` 的漂移用例锁死一致性；要彻底单源需在 `config.py` 加常量（超 write_scope，未做）。
7. **仓库级 lint 基线**：本机 `.venv313` 的 black 26.5.1 / isort 9.0.1 对 `src tests` 全量检查会报 31 个**既有**文件不合格（`config.py`、`web_server.py`、`test_web_server.py` 等，均非本次改动）。我改动的 2 个文件单独检查全部通过；CI 装的是 `black>=24`/`isort>=5.13`，是否同样报错**未确认**（本机无对应版本可验证）。
