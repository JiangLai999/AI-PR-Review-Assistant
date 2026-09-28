# B2/B3 实施记录：models.dev 接进配置助手 + 规格可编辑 + 中转站逐项自定义

- 任务：`claude-b2b3-impl`（实施）；上游设计：[docs/b2b3-wiring-design.md](b2b3-wiring-design.md)（提交 `92d8d1e`）
- 写作基线：`fa04897`（开工前 `git diff HEAD --stat` 里 Python 侧零改动；工作树里只有 mimo 的 `frontend/tui/src/*` 并发改动）
- 写集：`src/ai_pr_review/backend/jsonl_server.py`、`src/ai_pr_review/config.py`、
  `src/ai_pr_review/services/model_catalog.py`、`src/ai_pr_review/provider_diagnostics.py`、
  `tests/test_model_catalog.py`、`tests/test_jsonl_backend.py`、本文件
  （`config_commands.py` 在写集内但**最终未改**，理由见 §2.7）
- 验证环境：PowerShell，`TEMP`/`TMP` = `.pytest_claude`
- 结论：设计 §0 的 8 条决策全部落地；§4.1 的 22 条用例全部补齐（另加 1 条可选协议方法的用例，共 23 条）；
  与设计文档有 5 处偏差，全部记在 §2，其中 §2.1 是设计漏掉的**真问题**（不处理则 B3 的落盘会丢规格）。

---

## 1. 逐条对照

### 1.1 §0 决策表

| # | 决策 | 落地情况 | 证据 |
|---|---|---|---|
| 1 | 取数时机 = 打开配置助手，进程内一次，失败静默 | ✅ `config.options` 分支先 `await self._ensure_model_catalog()`（`jsonl_server.py:3241`）；失败 → `builtin`/`fetch_failed`，`ok` 仍为 true | `test_config_options_fetches_the_catalog_once_per_process`、`..._falls_back_to_builtin_when_the_catalog_fails` |
| 2 | 取数不阻塞事件循环 | ✅ `asyncio.to_thread(self._model_catalog.fetch)`（`jsonl_server.py:1062-1077`） | `test_catalog_fetch_does_not_block_the_event_loop`（同步睡 0.3s 时后台 ticker 仍跑 ≥3 次） |
| 3 | 读出口三处同键同形 | ✅ 三处都调 `_active_spec_block()` / `_model_spec_options()`（`jsonl_server.py:847`、`994`、`1719`） | `test_config_setup_persists_specs_and_all_exits_read_them_back`（断言三份键集合相等） |
| 4 | 快照/状态里叫 `model_spec`，不占 `model` 键 | ✅ `config.snapshot.model_spec`（`847`）、`model.status.model_spec`+`source`+`needs_verification`（`1719-1721`） | `test_model_status_spec_key_does_not_shadow_the_model_name` |
| 5 | 写入口 4 个可选参数，缺失/`null`=不动、非法=整单失败 | ✅ `_plan_model_spec_params`（`1275`）+ `_apply_model_spec_params`（`1335`） | `test_config_setup_spec_params_are_partial_updates`、`test_config_setup_rejects_an_invalid_spec_and_writes_nothing` |
| 6 | 不猜测：不一致 → `needs_verification` + 两个数字都给出 | ✅ `config.resolve_model_spec`（`config.py:659`）只算来源与待核标记，`catalog` 块原样带目录值 | `test_model_spec_block_marks_a_user_override_without_overwriting_it` |
| 7 | custom 不套官方预设 | ✅ 预设表里只有 `custom-model`；`from_model_provider(spec_overrides=...)` 让中转站模型不再是死数字 | `test_custom_endpoint_specs_never_take_official_presets` |
| 8 | `source` 四值口径由算法唯一决定 | ✅ 判定算法在 `config.resolve_model_spec`；`MODEL_SPEC_SOURCES`/`CATALOG_SOURCES` 与它同源 | `test_model_spec_bounds_are_sane`（`is` 断言两处同一份对象） |

### 1.2 §3 接线点

| § | 位置 | 落地 |
|---|---|---|
| 3.1 | `model_catalog.py` | ✅ `_cache_origin`（`137`）、`last_load_origin()`（`163`）、`lookup_in_index()`（`110`，只读索引、绝不取数）；`lookup()` 改为复用它，签名与返回不变 |
| 3.2-1 | `config.py` 常量 | ✅ `CONTEXT_WINDOW_RANGE`/`MAX_OUTPUT_RANGE`（`809-810`）、`DEFAULT_MODEL_*`（`491-492`）、`MODEL_SPEC_SOURCES`（`812`） |
| 3.2-2 | `ProviderConfig.set_model_spec()` | ✅ `config.py:586` |
| 3.2-3 | `from_model_provider(spec_overrides=...)` | ✅ `config.py:526`（见 §2.1，另有 `save()` 一处调用点） |
| 3.2-4 | 不给 `ProviderModelConfig` 加字段 | ✅ 一个字段都没加（新→旧降级仍安全） |
| 3.3.1 | 常量块 | ✅ `CATALOG_SOURCES`（`168`）、`REASONING_KIND_LABELS`（`170`）；`MODEL_SPEC_SOURCES` 见 §2.5 |
| 3.3.2 | 构造与状态 | ✅ `model_catalog` 关键字参数 + `_catalog_state`（`JsonlBackend.__init__`） |
| 3.3.3 | `_ensure_model_catalog` | ✅ `jsonl_server.py:1062` |
| 3.3.4 | 三个 builder | ✅ `_spec_block_for`（`933`）、`_slot_spec_block`（`982`）、`_active_slot_name`（`985`）、`_active_spec_block`（`994`）、`_model_spec_options`（`998`）、`_custom_endpoint_options`（`1018`）、`_reasoning_text`（`893`） |
| 3.3.5 | `_setup_options` 插入点 | ✅ `"model"`（`1208`）、`"custom_endpoint"`（`1211`） |
| 3.3.6 | `_config_snapshot` 插入点 | ✅ `"model_spec"`（`847`） |
| 3.3.7 | `_model_status` 插入点 | ✅ `spec` 先算好（不发网络），`"model_spec"/"source"/"needs_verification"`（`1719-1721`）；`_model_status_text` 未改 |
| 3.3.8 | 写路径 | ✅ `_apply_model_spec_params(spec_plan)` 在所有 profile 分支之后、`_sync_runtime_sections()` 之前（`1568`） |
| 3.3.9 | 协议分发 | ✅ `await self._ensure_model_catalog()`（`3241`）；可选方法 `config.catalog.refresh`（`3243`）也落地了 |
| 3.4 | `provider_diagnostics` | ✅ 补 4 个键（`context_window`/`max_output`/`spec_source`/`needs_verification`，`36-42`），与助手同源判定、**不联网**；`config_diagnostics` 透传无需改 |
| 3.5 | `config_entry`/`config_wizard` 不改代码 | ✅ 未改；补了两条回归用例（§1.3 的 D1/D2） |
| 3.6 | 前端 | ⛔ 不在本任务（TUI 助手屏后续单独派单），后端契约已按 §3.6 的字段名交付 |

### 1.3 §4.1 测试清单（22 条 → 全部落地，另加 1 条）

> 文件落位与设计文档不同：设计把 C 组点名给 `tests/test_config.py`、D 组给 `tests/test_cli.py`，
> 而本任务 write_scope 只允许 `tests/test_model_catalog.py` 与 `tests/test_jsonl_backend.py`。
> 5 条用例按**同名**落在允许的两个文件里（先例：`test_symbol_locate_vocabulary_matches_the_config_layer`
> 本来就在 `test_jsonl_backend.py` 里）。D1/D2/D3 用 `CliRunner` + 全局 `--config <path>` 跑真实 CLI。

| 组 | 用例 | 位置 |
|---|---|---|
| A | `test_last_load_origin_reports_network_then_cache` | `tests/test_model_catalog.py:292` |
| A | `test_failed_fetch_keeps_origin_none` | `tests/test_model_catalog.py:311` |
| B | `test_config_options_fetches_the_catalog_once_per_process` | `tests/test_jsonl_backend.py:5864` |
| B | `test_config_options_falls_back_to_builtin_when_the_catalog_fails` | `…:5881` |
| B | `test_config_options_respects_model_catalog_fetch_off` | `…:5898` |
| B | `test_model_spec_block_marks_a_user_override_without_overwriting_it` | `…:5917` |
| B | `test_model_spec_block_matches_the_catalog_when_values_agree` | `…:5941` |
| B | `test_custom_endpoint_specs_never_take_official_presets` | `…:5957` |
| B | `test_config_setup_persists_specs_and_all_exits_read_them_back` | `…:5994` |
| B | `test_config_setup_spec_params_are_partial_updates` | `…:6040` |
| B | `test_config_setup_rejects_an_invalid_spec_and_writes_nothing` | `…:6076`（7 组参数化） |
| B | `test_config_setup_applies_specs_in_the_custom_routing_profile` | `…:6112` |
| B | `test_model_status_spec_key_does_not_shadow_the_model_name` | `…:6135` |
| B | `test_model_status_and_config_snapshot_never_fetch_the_catalog` | `…:6153` |
| B | `test_reasoning_summary_text_follows_the_ui_language` | `…:6176` |
| B | `test_catalog_fetch_does_not_block_the_event_loop` | `…:6207` |
| B | `test_protocol_config_options_and_setup_carry_model_specs` | `…:6241` |
| C | `test_set_model_spec_touches_only_the_target_model` | `…:6310` |
| C | `test_model_spec_bounds_are_sane` | `…:6348` |
| D | `test_config_show_and_export_keep_model_specs` | `…:6364` |
| D | `test_config_import_round_trips_a_relay_spec` | `…:6402` |
| D | `test_config_health_reports_the_effective_spec_and_source` | `…:6443` |
| ＋ | `test_config_catalog_refresh_bypasses_the_process_memo`（§3.3.9 的可选方法） | `…:6291` |

前置设施（设计 §4.1-B 明确要求，**不是可选项**）：

- `tests/test_jsonl_backend.py:5778` `_offline_model_catalog`（**autouse**）：整份文件把 models.dev 的
  HTTP 层换成 `URLError`。打 HTTP 层而不是 `fetch`，失败路径因此与真实断网逐字一致。
  设计要求的"取数点必须落在协议分支、不能塞进 `_setup_options()`"也是为这条服务的。
- `tests/test_jsonl_backend.py:5798` `_stub_catalog`：注入真实 payload（`CATALOG_PAYLOAD`，`5752`），
  并在 `ModelCatalog.fetch` 上计数——数 URL 分不清"backend 的 memo 生效"和"恰好命中目录缓存"。
- `tests/test_jsonl_backend.py:5838` `_deepseek_backend`：远端槽 = deepseek/deepseek-flash 并同步活跃槽。

---

## 2. 与设计文档的偏差（5 处）

### 2.1 【设计漏项，必须处理】`save()` 自己就会重建 provider，把规格打回预设

设计 §3.3.8 写的是"写规格 → `_sync_runtime_sections()` → save → 重载"，并注明"重载会重建 provider 对象，
所以规格必须在 save 之前写"。**但 `save()` 自己就是重建点**：`config.py` 的 `active is self.provider` 分支会
执行 `ProviderConfig.from_model_provider(self.ai_client.model_provider)`，而 `ai_client.model_provider` 是
`ModelProviderConfig`（**不带任何规格字段**）——重建出来的模型表只有预设值，中转站模型拿回写死的
32 768/4 096。也就是说：按设计原文实施，`test_config_setup_persists_specs_and_all_exits_read_them_back`
与 `test_custom_endpoint_specs_never_take_official_presets` 会失败，B3 等于没做。

**处理**（三处，都在写集内）：

1. `ProviderConfig.from_model_provider(..., spec_overrides=...)`（`config.py:526`，设计 §3.2 第 3 条要求的方法）；
2. `AppConfig.save()` 重建时带上**当前生效模型**的条目规格（`config.py:1556-1567`）；
3. `_apply_setup` 的两条重建分支（cloud/local）带上 `_carry_over_spec(...)`（`jsonl_server.py:1314`）——
   否则"上一次保存过的规格"会在下一次提交时被分支重建悄悄吃掉。

**影响面**：只有"用户/助手显式填过规格的那个模型"会与改造前不同（这正是 B3 要的）；预设表里的其它模型、
`/model <name>` 切换、`config model` 路径与改造前逐字节一致（新条目仍然落 32 768/4 096）。
不传 `spec_overrides` 时 `from_model_provider` 与改造前的输出逐字节相同。

### 2.2 规格块的 `provider` 键撞上"不回显被忽略覆盖值"的既有红线

新增 `model_spec.provider` 让既有用例 `test_matching_invalid_provider_override_is_still_rejected`
（`tests/test_jsonl_backend.py:851`，断言快照 JSON 里不出现被忽略的 provider 覆盖原值）失败。
处理：规格块复用 `_config_snapshot` 的同一条判定（`_safe_provider_name`，`jsonl_server.py:922`），
被忽略/非法的覆盖一律渲染成 `"unsupported"`。**这是设计没考虑到的**：新增出口必须继承既有出口的红线。

### 2.3 `max_output <= context_window` 的校验时机

设计 §2.5 说"用**本次提交后的两个值**比较"。而运行模式分支可能刚把 provider 换成另一个模型（预设规格不同），
所以这个关系检查放在**写入前、分支后**（`_apply_model_spec_params`，`jsonl_server.py:1335`）；
整型与闭区间检查留在解析时（`_plan_model_spec_params`，`1275`）——非法值因此一个字段都不写（"整单失败"）。
代价与设计 §5 风险 9 一致：关系检查失败时，本次提交早先的**内存**赋值不回滚（磁盘一字不动）。

### 2.4 测试文件落位受限（见 §1.3 开头的说明）

设计点名的 `tests/test_config.py`、`tests/test_cli.py` 不在 write_scope 内，
5 条 C/D 用例按同名落到允许的两个文件里，并保持判据不变。

### 2.5 `MODEL_SPEC_SOURCES` 落在 `config.py` 而不是 `jsonl_server.py`

设计 §3.3.1 把三张取值表都放在 `jsonl_server`，但 §3.4 又建议把判定算法抽到 `config.py` 共用。
最终：判定算法与其取值集合都归 `config.py`（`resolve_model_spec` / `MODEL_SPEC_SOURCES`），
`jsonl_server` 直接 `from ... import MODEL_SPEC_SOURCES`（同一份对象，`test_model_spec_bounds_are_sane`
用 `is` 钉住），只把纯展示用的 `CATALOG_SOURCES`/`REASONING_KIND_LABELS` 留在 `jsonl_server`。

### 2.6 空串不是"不动"

`context_window: ""` 按"必须为整数"报错（只有**缺失**与 `null` 才是部分更新）。理由：TUI 的输入框会预填
当前值，空串意味着用户主动清空了这一格，静默忽略比报错更糟（同 `_setup_slot`/`repo_context` 的取舍）。

### 2.7 `config_commands.py` 最终未改

设计 §3.4 只要求给 `build_provider_health_payload`（在 `provider_diagnostics.py`）补 4 个键，
`config_commands.run_config_health` 是直通转发，本来就没有可改的地方；`run_config_test` 明确不在本轮范围。
所以写集里的这个文件保持零改动。

---

## 3. 关键行号（本次实施，基线 `fa04897` + 本 PR）

| 文件 | 位置 | 内容 |
|---|---|---|
| `services/model_catalog.py` | 110 / 137 / 163 / 205 | `lookup_in_index`（只读查询）/ `_cache_origin` / `last_load_origin()` / 取数成功记 `"network"` |
| `config.py` | 491-492 / 500 | `DEFAULT_MODEL_CONTEXT_WINDOW`(32768)、`DEFAULT_MODEL_MAX_OUTPUT`(4096) 与 dataclass 默认值同源 |
| `config.py` | 526 / 586 | `from_model_provider(spec_overrides=...)` / `ProviderConfig.set_model_spec()` |
| `config.py` | 641 / 659 | `_catalog_agrees()` / `resolve_model_spec()`（§2.8 判定，唯一真源） |
| `config.py` | 809-812 | `CONTEXT_WINDOW_RANGE`、`MAX_OUTPUT_RANGE`、`MODEL_SPEC_SOURCES` |
| `config.py` | 1556-1567 | `save()` 重建时带过当前生效模型的规格（§2.1） |
| `backend/jsonl_server.py` | 168 / 170 | `CATALOG_SOURCES` / `REASONING_KIND_LABELS` |
| `backend/jsonl_server.py` | 594 / 601 | `_catalog_fetched_at()` / `_CatalogState`（`disabled`/`builtin`/`from_fetch`/`lookup`） |
| `backend/jsonl_server.py` | 847 | `config.snapshot.model_spec` |
| `backend/jsonl_server.py` | 893 / 933 / 998 / 1018 | `_reasoning_text` / `_spec_block_for`（唯一构造点）/ `_model_spec_options` / `_custom_endpoint_options` |
| `backend/jsonl_server.py` | 1062 / 1079 | `_ensure_model_catalog`（唯一网络点）/ `_refresh_model_catalog` |
| `backend/jsonl_server.py` | 1208 / 1211 | `config.options` 的 `model` / `custom_endpoint` 两块 |
| `backend/jsonl_server.py` | 1239 / 1275 / 1314 / 1335 / 1568 | `_coerce_spec_int` / `_plan_model_spec_params` / `_carry_over_spec` / `_apply_model_spec_params` / 调用点 |
| `backend/jsonl_server.py` | 1719-1721 | `model.status` 的 `model_spec`/`source`/`needs_verification` |
| `backend/jsonl_server.py` | 3241 / 3243 | 协议分发：`config.options` 取数 / `config.catalog.refresh` |
| `provider_diagnostics.py` | 36-42 | health payload 的 4 个新键 |

---

## 4. 验证记录（真实数字）

> 全部命令在仓库根目录、`TEMP=TMP=<repo>\.pytest_claude` 下运行（PowerShell）；逐条为 `--no-cov`。

### 4.1 设计 §4.2 的逐项验证

| # | 验证对象 | 命令 | 实测 |
|---|---|---|---|
| 1 | 服务层来源标注（§3.1） | `python -m pytest tests/test_model_catalog.py -q --no-cov` | **15 passed in 0.07s**（13 旧 + 2 新） |
| 1b | 同上，只跑来源用例 | `... -k origin` | **2 passed, 13 deselected** |
| 2 | 规格块与判定（§3.3.4-3.3.7） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k "model_spec or catalog"` | **12 passed, 209 deselected in 1.65s**（全离线，无 skip） |
| 3 | 写路径（§3.3.8） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k "config_setup and spec"` | **10 passed, 211 deselected in 0.70s** |
| 4 | CLI 出口（§3.4） | `python -m pytest tests/test_cli.py -q --no-cov -k "spec or health or export"` | **7 passed, 82 deselected in 1.24s**（`test_cli.py` 零改动，纯回归） |
| 5 | 全量回归 | `python -m pytest -q --no-cov` | **1086 passed, 1 skipped, 1 warning**（两次独立运行：74.11s / 89.53s，结果一致）。设计基线 1049 passed / 1 skipped；差额含 codex 两个 chat 提交新增的用例 + 本任务新增 29 例。唯一 warning 是既有用例故意喂非法偏好值触发的 |
| 6 | 断网手工验证（§2.1 降级） | `echo '{"id":"1","method":"config.options","params":{}}' \| HTTPS_PROXY=http://127.0.0.1:9 AI_PR_REVIEW_CONFIG=<cfg> python -m ai_pr_review.backend.jsonl_server` | 单行 JSON：`ok: True`、`catalog_state: builtin fetch_failed`、`remote.source: builtin`、`catalog: None`，无 traceback，进程数秒内退出 |
| 7 | 联网手工验证（§2.2 命中） | 同上但不设代理（真实请求 models.dev） | `catalog_state: models.dev`、`catalog = {context_window: 1000000, max_output: 393216, source: models.dev}`、`reasoning: "开关 · 档位 low/high/max"`、落盘 1048576/384000 与目录不一致 → `needs_verification: True` |
| 8 | 状态/快照不拉取（方案 §B2 验收） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k never_fetch` | **1 passed, 220 deselected in 0.81s** |
| 9 | 语法检查 | `python -c "import ast; [ast.parse(...) for p in (config.py, jsonl_server.py, model_catalog.py, provider_diagnostics.py)]"` | `ast ok`；`python -c "from ai_pr_review.backend.jsonl_server import JsonlBackend"` → `import ok` |

第 6 条的"断网"用 HTTPS 代理指向死端口（`127.0.0.1:9`）模拟：本机有外网，
不能靠拔网线复现；代理不可达与真实断网在该路径上完全等价（`urlopen` 抛异常 →
`_fetch_from_source` 吞掉并记 `fetch_failed`）。

### 4.2 本任务新增的用例数

```text
$ git diff HEAD -- tests/test_jsonl_backend.py tests/test_model_catalog.py | grep -c "^+def test_"
23          # 21（jsonl） + 2（catalog）
```

其中 `test_config_setup_rejects_an_invalid_spec_and_writes_nothing` 参数化 7 组
（越界 ×3、bool、float、非数字串、max_output > context_window），故**新增 test case = 29 个**。
两文件当前收集数：`236 tests collected`。

### 4.3 集成点复检（并发工作树）

收尾时 HEAD 已从 `fa04897` 前进到 `bd1d358`（mimo 的 TUI 两个提交 + 一个文档提交）。
`git diff --stat fa04897..HEAD` 显示那两个提交只碰 `frontend/tui/*` 与 `docs/*`，**零 Python 改动**；
本任务的 7 个文件仍在工作树里、`git diff HEAD --name-only` 除它们外只剩 `.agent-bus/.gitignore`
（开工前就是修改状态）。复检后重跑全量仍是 1086 passed / 1 skipped。

---

## 5. 未决项

1. **TUI 侧**：助手屏的「模型规格」屏、状态栏来源角标、错误路由（`message.includes("模型规格")` 必须排在
   泛化 `message.includes("模型")` 之前）都还没做——设计 §3.6 已给契约，等后续派单。
2. **`config.catalog.refresh` 的 UI**：后端方法已落地并有用例，但"重新获取"按钮与拉取中/失败反馈未定（设计 §6.6）。
3. **`max_tokens` 不跟随 `max_output`**：设计 §6.5 明确不在本轮，规格改了请求体不会变，需单独立项。
4. **`needs_verification` 的一键实测**：本轮只给文案与命令提示（`scripts/probe_model_reasoning.py`），
   不从 TUI 跨进程执行。
5. **`config_entry.py:119` 偏好不过滤**（设计 §5 风险 2）：导入"新版本导出、含未知偏好键"的文件仍会
   `TypeError`，属既有缺陷，交配置层 owner（Codex）。
6. **`config test` 仍不显示规格**（设计 §1 第 14 条）：`ModelProviderConfig` 没有规格字段，属新增功能。
7. **本地槽规格的"重新选择模型"路径**：`_apply_slot_model`（`/model`）保持现状（新模型落 32 768/4 096），
   与设计 §2.5 的"不在 `/model` 路径上拉目录"一致；但用户在助手里给本地槽填过规格后，若在 `/model` 里
   换成另一个模型名，旧规格仍留在旧条目上（新模型走默认值）——与远端槽行为一致，暂不改。
