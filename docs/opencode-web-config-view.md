# ConfigView 读侧三键 + 数值范围单一真相源（Phase 2 后端 · p2-config-view）

**一句话结论**：`GET /api/config` 的 `ConfigView.to_dict()` 现在多出 `preferences`（6 个可编辑偏好的当前值）、
`options`（6 份 `{value,label}` 下拉清单 + `numeric_ranges` 数值范围）、`runtime_profile`（当前运行档位）三键，
既有键一个未动；数值项的 `min/max/step` 与后端拒收越界值读的是**同一张表** `NUMERIC_FIELD_RANGES`。
写入侧语义（白名单 / 词表 / 落盘读回校验）保持不变。

改动面：`src/ai_pr_review/web_config.py`、`tests/test_web_config_writes.py`、本文档。`web_server.py`、`web/src/**` 未改。

## 1. 契约与字段来源（file:line）

响应三键（键名冻结，前端按 `web/src/api/types.ts:240-258` 的 `ConfigView` 消费）：

| 键 | 形状 | 当前值来源 | 可选项来源 | 落点（本文件） |
| --- | --- | --- | --- | --- |
| `preferences` | 6 个字符串键 | `config.preferences.*`（`config.py:1076-1112` 的 `PreferencesConfig`，与 CLI 助手读**同一份**） | — | `preference_values()` `:181-187` |
| `options.<6 个清单键>` | `[{value,label}]` | — | value = `web_config.py:64-71` 的 `PREFERENCE_VOCABULARIES`（其中 `workbench_mode`/`repo_context`/`review_reasoning_effort` **直接引用** `config.py:739`/`:810`/`:748` 的常量）；label = `PREFERENCE_OPTION_LABELS` `:92-113` | `preference_options()` `:189-207` |
| `options.numeric_ranges` | `{字段: {min,max,step}}` | — | `NUMERIC_FIELD_RANGES` `:122-129` | 同上 |
| `runtime_profile` | 字符串 | `JsonlBackend._infer_runtime_profile`（`backend/jsonl_server.py:827-837`） | — | `resolve_runtime_profile()` `:167-179` |

6 个清单键（**前端键名不可改**，`web/src/api/types.ts:230-238`）：`ui_languages` / `output_formats` /
`chat_layouts` / `workbench_modes` / `repo_contexts` / `review_efforts`，映射表 `PREFERENCE_OPTION_KEYS` `:76-83`。

label 的文案口径：前 4 份抄 `backend/jsonl_server.py:1329-1347`（`_setup_options()` 的内联清单），
后 2 份抄同文件 `REPO_CONTEXT_LABELS` `:171-175` / `REVIEW_REASONING_LABELS` `:187-193` ——
**取值的真相源仍是 `config.py` 的词表**，这里只补中文/英文说明，且由测试 `test_options_values_match_config_constants`
与 TUI 逐项比对，漂移即红。唯一刻意差异：`workbench_mode` 用短文案（`自动 / Auto` 等，冻结契约的示例值），
TUI 那份多带的是 TUI 专属快捷键提示（「Alt+W 收起」），照搬进设置页只会误导鼠标用户 —— 测试里用
`startswith` 锁定"短文案是 TUI 文案的前缀"。

`runtime_profile` 的折算规则（**复用、不重写**）：生效槽位是 `ollama`/`local` → `local`；
存在环境变量覆盖 → `cloud`；否则 `ROUTE_PROFILE_BY_STRATEGY[preferences.hybrid_strategy]`
（`backend/jsonl_server.py:156-160`：`remote_only→cloud`、`local_only→local`、`balanced→hybrid`）。
本文件不推导 `chat_slot`/`review_slot`，也不自己折算槽位 —— 槽位路由归后端，设置页只读展示。
`_RuntimeProfileProbe` `:153-164` 只为避免实例化整个 `JsonlBackend`（它的 `__init__` 会建会话存储、
事件计数、审查超时等运行态，`:797-825`），该方法本身只读 `self.config`。

## 2. 与 CLI 助手 6 阶段的对应关系

阶段号以 CLI 的**渲染源**为准：`frontend/tui/src/app.tsx:1761-1790`（`screenStages`）、
`:1792-1799`（`stageNames`）、`:2762`（渲染成 `N/6 · 阶段名`）。设置页侧的阶段标注见
`web/src/pages/SettingsPage.tsx:21-23`。

| CLI 阶段 | CLI 阶段名 | 本任务暴露的键 | Web 分组 / 控件（`SettingsPage.tsx`） |
| --- | --- | --- | --- |
| 1/6 | 运行模式 | `runtime_profile`（只读） | 模型服务与凭证卡头的只读 Chip `:527` |
| 2/6 | 模型服务 | （Phase 0.2 写侧已有：`base_url` 等） | 供应商预设 / Base URL / 模型名 / API 格式 |
| 3/6 | 凭据与模型 | （掩码：`api_key_masked`） | 模型 API Key |
| 4/6 | GitHub Token | （掩码：`github_token_masked`） | GitHub Token |
| 5/6 | 界面与输出 | `preferences` 6 键 + 对应 6 份清单 | 界面与输出 `:741`（`ui_language`/`output_format`/`chat_layout`/`workbench_mode`）+ 审查偏好 `:751`（`repo_context`/`review_reasoning_effort`） |
| 6/6 | 确认保存 | — | 保存区 `:761` |
| — | （CLI 无此阶段） | `options.numeric_ranges` | 成本与并发 `:660-707`（Web 独有的 6 个数值 + 2 个开关） |

6 个下拉在 CLI 助手同属**第 5 阶段**（`app.tsx:1779-1788` 把它们全标成 5）；Web 拆成两组只为便于查找，
两组的阶段 Chip 都写 `CLI 助手 5/6`。任务书里"4 界面与输出 · 5 审查偏好"的写法与 CLI 源码不一致，
见 §5 未决项 1。

## 3. 校验单一真相源（数值范围）

任务：前后端各存一份数值边界迟早漂移（"前端允许、后端拒绝"没人说得清为什么）。现在**后端是唯一真相源**：

1. **一张表**：`NUMERIC_FIELD_RANGES`（`web_config.py:122-129`）定义 6 个数值项的 `min/max/step`
   （`max_tokens` 1~128000/1、`timeout_seconds` 5~600/5、`review_concurrency` 1~16/1、
   `cross_file_max_files` 1~10/1、`max_cost_per_run` 0~100/0.1、`max_cost_per_24h` 0~1000/0.5）。
2. **两个消费点**：
   - 读：`preference_options()` 把它原样放进 `options.numeric_ranges`，前端
     `web/src/pages/SettingsPage.tsx:677-689` 据此渲染 input 的 `min/max/step`（拿不到就退回本地 step，
     `docs/claude-web-settings-parity.md` §4-1）；
   - 写：`apply_config_update()` 的数值段 `web_config.py:409-426`，越界一律
     `SaveResult(ok=False, message="invalid value for <k>：超出允许范围 <min>~<max>")`，
     **不改内存、不落盘、`changed == []`**（沿用 Phase 0.2 的拒绝语义，调用方按 `ok` 映射 HTTP 400）。
     message 不回显原值（可能带误粘贴内容），但会给出允许区间，用户知道该往哪改。
3. **`step` 只服务 UI**：不参与后端判定（0.1 步进的浮点用 `==` 判对齐会踩二进制误差），
   后端只判闭区间。
4. **表的边界**：`set(NUMERIC_FIELD_RANGES) == EDITABLE_AI_FIELDS 里的 int/float 字段`
   （由 `test_numeric_ranges_are_exposed_and_enforced` 钉住），布尔开关与 `base_url`/`model`/`api_format`
   这类文本项不进范围表。
5. 口径与前端离线契约一致（`docs/claude-web-settings-parity.md` §5 场景 [5]：`timeout_seconds` 5/600/5、
   `max_cost_per_24h` 0/1000/0.5），要放宽**只改这一张表**。

既有键位语义未变：`ACCEPTED_PAYLOAD_KEYS`（白名单）、`PREFERENCE_VOCABULARIES`（偏好词表）、
落盘读回校验（`_read_back_mismatches`）都照旧；本轮只在数值段前插了范围判定。

## 4. 验证（真跑，数字如下）

```
$ $env:TEMP='.pytest_opencode'; $env:TMP='.pytest_opencode'; python -m pytest tests/test_web_config_writes.py tests/test_web_server.py -q --no-cov
73 passed in 32.50s

$ $env:TEMP='.pytest_opencode'; $env:TMP='.pytest_opencode'; python -m pytest tests/test_credentials_and_jobs.py -q --no-cov
36 passed in 0.88s
```

新增用例（`tests/test_web_config_writes.py`，连同既有 7 条共 10 条）：

| 用例 | 行号 | 断言 |
| --- | --- | --- |
| `test_config_view_exposes_preferences_and_options` | `:226-280` | 三键齐、既有 11 键一个不少、`preferences` 逐键等于 `config.preferences`、6 份清单每项 `{value,label}`、`runtime_profile` ∈ {cloud,local,hybrid,custom} 且**等于同一份配置下 `JsonlBackend.runtime_profile`**、`hybrid_strategy=local_only` → `local` |
| `test_options_values_match_config_constants` | `:282-317` | 6 份清单 value（含顺序）== `PREFERENCE_VOCABULARIES`；`repo_contexts`/`review_efforts` == `config.REPO_CONTEXT_MODES`/`REVIEW_REASONING_EFFORTS`；与 TUI `_setup_options()` 同值同文案（workbench 用前缀比对） |
| `test_numeric_ranges_are_exposed_and_enforced` | `:319-373` | 范围表 == 数值字段集合、`max_tokens` 三元组原样、6 个越界值逐个 `ok=False` + message 带字段与区间 + 不落盘 + 内存未改；4 个边界/区间内载荷（含字符串 `"30"`）`ok=True` 且真的写进磁盘 |

回归面（同样真跑，含 `test_benchmark.py` 在内的全量）：

```
$ $env:TEMP='.pytest_opencode'; $env:TMP='.pytest_opencode'; python -m pytest -q --no-cov
1399 passed, 1 skipped, 1 warning in 106.58s (0:01:46)
```

（那 1 条 warning 是 `tests/test_jsonl_backend.py::test_chat_context_budget_can_be_set_in_the_config_file`
里 `config.py:1137` 的既有 `RuntimeWarning`，与本任务无关；1 skipped 是既有的跳过用例。）

**端到端冒烟**（真实 `ThreadingHTTPServer` + `ReviewWebHandler`，脚本
`.pytest_opencode/opencode/smoke_config_view.py`，临时 config 路径，退出码 0）：

```
GET /api/config -> 200
top-level keys: [... 'options', 'preferences', 'runtime_profile', ...]
preferences: {"ui_language": "zh-CN", "output_format": "terminal", "chat_layout": "compact",
              "workbench_mode": "auto", "repo_context": "tests+imports",
              "review_reasoning_effort": "off"}
options keys: ['chat_layouts', 'numeric_ranges', 'output_formats', 'repo_contexts',
               'review_efforts', 'ui_languages', 'workbench_modes']
runtime_profile: hybrid
numeric_ranges: {"max_tokens": {"min":1,"max":128000,"step":1}, ..., "max_cost_per_24h": {...1000...}}
repo_contexts[1]: {"value": "tests", "label": "仅测试文件 / Tests only"}
POST max_tokens=0        -> 400 {"ok": false, "changed": [],
                                 "message": "invalid value for max_tokens：超出允许范围 1~128000"}
POST timeout_seconds=5   -> 200 {"ok": true, "changed": ["timeout_seconds"],
                                 "message": "已保存 1 项到 config.json。"}
```

风格与类型（`.venv313` 内的工具）：`black --check` / `isort --check-only` / `mypy src/ai_pr_review/web_config.py`
与 `mypy tests/test_web_config_writes.py` 均退出码 0。

## 5. 未决项

1. **阶段号口径冲突（未裁决）**：任务书写"4 界面与输出 · 5 审查偏好"，CLI 源码与实测帧是
   **5/6 界面与输出（含 6 个偏好键）**、4/6 = GitHub Token（`app.tsx:1778-1788`、`:1796`）。
   本文与前端（`SettingsPage.tsx:23`）都按 CLI 取 5/6；若主控裁定以任务书为准，改文档与那一处常量即可。
2. **`runtime_profile` 依赖 `jsonl_server` 的私有方法**：`resolve_runtime_profile()` 调
   `JsonlBackend._infer_runtime_profile`（复用而非复制折算规则），耦合点是私有方法 + `_RuntimeProfileProbe`
   这个"最小 self"。更干净的收口是把该函数上提为 `config.py` 的模块级函数（`web_config`、`jsonl_server`
   两侧共用），但 `config.py` 不在本任务 `write_scope`，未动。当前由
   `test_config_view_exposes_preferences_and_options` 的同配置比对兜底：后端改了折算规则而 Web 没跟上 → 测试红。
3. **`runtime_profile` 不会返回 `custom`**：它是"实际哪一档在生效"的折算，`custom` 是"用户选的是哪一档预设"
   （记在 `routing.profile`，`docs/claude-chat-routing.md` §未决 4）。设置页目前没有槽位路由入口
   （只有只读 Chip，`SettingsPage.tsx:527`），所以本键恒为 `cloud|local|hybrid`；契约里的 `custom` 是为
   未来接 `routing.profile` 留的位置。
4. **范围上限是"与前端契约对齐"的口径，不是硬约束**：例如 `timeout_seconds` 上限 600 秒对慢供应商偏紧
   （默认 120）。放宽只改 `NUMERIC_FIELD_RANGES` 一处，但会同时改变前端 `min/max` 展示，需与前端并行确认。
5. **未对真实服务复跑前端离线脚本**：`docs/claude-web-settings-parity.md` §5 的 71 断言脚本
   （`.pytest_claude/claude/verify-settings-parity.mjs`）场景 [1]/[2] 针对的正是本任务的读侧三键，
   但它需要 `node` + `vite` 静态服务且不在 `write_scope`；建议由主控或前端 agent 对真实服务复跑一次
   （对应 `claude-web-settings-parity.md` 未决 2/6）。
