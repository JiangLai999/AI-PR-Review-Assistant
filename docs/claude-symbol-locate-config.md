# `symbol_locate` 配置入口（协议三出口 + CLI 开关）交付报告（任务 `claude-symbol-locate-config`）

**一句话结论**：L2 符号定位开关（`preferences.symbol_locate`，`docs/mimo-l2-symbol-locator.md`）
从此有了配置入口——`config.setup` 接受可选 `symbol_locate`（布尔；`"true"/"off"` 等 config 层
同款写法也接受；**非法值抛 `ConfigValidationError` 且整单不落盘**；缺失/`null` = 保持不变），
`config.options` / `model.status` 给出当前值 + 可选值（同键同形），`pr-review preferences`
新增 `--symbol-locate` / `--no-symbol-locate`（一份实现、两条命令入口，回显当前值）。
未改 `config.py` / `symbol_locator.py` / `review_orchestrator.py` 一个字；既有协议载荷全部是
加法式扩展。`tests/test_jsonl_backend.py tests/test_cli.py`：**258 passed**（基线 231，新增 27）。

- 任务类型：实现（写入范围：`src/ai_pr_review/backend/jsonl_server.py`、`src/ai_pr_review/cli.py`、
  `tests/test_jsonl_backend.py`、`tests/test_cli.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 未做：未读/打印凭据；未执行任何 git 操作；未改 `frontend/tui`（界面留后续任务）、未改 `config.py`
  的字段与 `normalize_symbol_locate`、未改 `symbol_locator.py` / `review_orchestrator.py`；未联网

## 1. 三个出口（键名相同、形状与用途不同）

| 出口 | 形状 | 位置 | 用途 |
|---|---|---|---|
| `config.setup` | 入参 `symbol_locate`（**可选**） | `jsonl_server.py:1022` | 写：用户在向导里开关它 |
| `config.options` | `{"value": bool, "options": [{"value", "label"}]}` | `jsonl_server.py:838`，组装点 `_symbol_locate_options()` `:686` | 读：当前值 + 可选值 + 双语 label |
| `model.status` | 同上（与 `config.options` **同键同形**） | `jsonl_server.py:1176` | 读：状态栏/TUI 直接渲染，不必再拉一次 options |

```json
{
  "symbol_locate": {
    "value": true,
    "options": [
      {"value": true,  "label": "开启 / On"},
      {"value": false, "label": "关闭 / Off"}
    ]
  }
}
```

（上面这段是实测输出，见 §5 的离线联调脚本 [B]。）

- `options[].value` 是**布尔**而不是 `"on"/"off"` 字符串：开关只有两态，前端把选中项原样塞回
  `config.setup` 即可，不需要在 TS 侧做一次字符串↔布尔转换（少一次"两边写法不一致"的机会）。
  协议侧同时接受 `"true"/"false"/"on"/"off"/"yes"/"no"/"1"/"0"` 与 `0|1`（见 §3），
  所以手写载荷/脚本化调用也不会因为写法不同被拒。
- label 由后端给出（`SYMBOL_LOCATE_CHOICES`，`jsonl_server.py:134`），与 `runtime_profiles` /
  `repo_context` 同惯例，TUI 不硬编码中文。
- **`config.snapshot` 刻意没有加这个键**：本任务要求的是上面三个出口，而 TUI 预选该屏只需要
  `config.options.symbol_locate.value`（`repo_context` 屏就是这么读的）；要加是一行的事，
  留给真正消费它的 TUI 任务决定（见 §7.1）。

## 2. `config.setup` 语义（部分更新 / 非法值 / 精度）

`_apply_setup`（`jsonl_server.py:1022-1025`）：

```python
if "symbol_locate" in params and params.get("symbol_locate") is not None:
    preferences.symbol_locate = self._coerce_symbol_locate(params["symbol_locate"])
```

| 输入 | 行为 |
|---|---|
| `true` / `false`（JSON 布尔） | 写入 `preferences.symbol_locate`，随同一次 `save()` 落盘 |
| `0` / `1`（数字） | 同上（`0`→`false`，`1`→`true`） |
| `"true"` / `"false"` / `"on"` / `"off"` / `"yes"` / `"no"` / `"1"` / `"0"`（大小写、首尾空格不敏感） | 同上 |
| 其它任意值（含 `""`、`"maybe"`、`2`、`-1`、`2.0`、数组、对象） | `ConfigValidationError`，**整单失败**：不落盘，内存也不改这个字段 |
| 字段缺失 / `null` | 保持不变（与 `ui_language`、`repo_context` 等偏好一致的部分更新语义） |

- 报错文案（双语，与 `repo_context` 同风格）：
  `请求失败：符号定位仅支持 true 或 false。（symbol_locate accepts true or false.）`
  ——后半句是 `handle()` 既有错误映射加的前缀，不是本任务新加的（同 `docs/claude-repo-config.md` §6.7）。
- **`""` 与 `repo_context` 的 `""` 不一样**（那里是"保持不变"）：布尔开关没有"空串"这个合法状态，
  静默当成 `true` 会把一个坏载荷变成"看起来成功"；要表达"不改"的写法是不传或传 `null`。
- 与加载路径的区别是刻意的：加载旧配置时非法值只告警回退成 `true`
  （`config.normalize_symbol_locate`，`config.py:756-774`），而向导里的非法值是用户刚刚做出的选择，
  静默改成别的档位比报错更糟（同 `_setup_slot` / `repo_context` 的理由）。
- 精度说明（与 `repo_context` 同）：非法值时赋值语句在抛错之前就被跳过，所以内存与磁盘都不变；
  但如果同一载荷里**更靠后**的字段（如 `auto_publish_comment`）才校验失败，`symbol_locate`
  可能已经在内存里更新过（磁盘仍未写）。反过来也成立：`{"ui_language": "en-US", "symbol_locate": "sometimes"}`
  会正确报错、磁盘不动，但 `ui_language` 的内存值已经改了。这是该方法既有的"逐项赋值 + 末尾统一
  `save()`"行为（`jsonl_server.py:1033` 是 `_apply_setup` 里唯一的 `save()`），不是本次新字段引入的。

## 3. 取值口径与 config 层的关系

`_coerce_symbol_locate`（`jsonl_server.py:701`）重列了一份解析表，而不是复用
`config.normalize_symbol_locate`：后者对非法值**只告警回退**，向导要的是**报错整单失败**，
两者语义相反，不能共用一个入口。为防止两张表漂移，加了一个把口径钉在一起的用例：

| 写法 | config 层（加载配置） | 向导层（`config.setup`） |
|---|---|---|
| `true` / `false` / `0` / `1` | 原样接受，不告警 | 接受，解析成同一个布尔 |
| `"true"` `"True"` `" ON "` `"yes"` `"1"` / 反向写法 | 原样接受，不告警 | 接受，解析成同一个布尔 |
| `""` / `" "` / `"maybe"` / `"tru"` / `2` / `-1` / `1.0` / `None` / `[]` / `{}` | 告警一次，回退 `true` | `ConfigValidationError` |

`tests/test_jsonl_backend.py::test_symbol_locate_vocabulary_matches_the_config_layer`（`:3692`）
对上面 24 个样本逐个对拍："config 层不告警 ⇔ 向导层接受，且解析结果相同"。
将来 `normalize_symbol_locate` 扩了写法而向导没跟上（或反过来），这个用例会红。

## 4. CLI：`pr-review preferences --symbol-locate / --no-symbol-locate`

- 选项定义 `cli.py:3480-3487`（click 布尔开关对，`default=None`），落盘与回显 `cli.py:3522-3527`；
  两条入口 `pr-review preferences` 与 `pr-review config preferences` 共用同一实现
  （`cli.py:3533` 的 `add_command`）。
- **不传**两个开关 = 只回显当前值、**不落盘**（连配置文件都不会被创建）；回执 JSON 增加
  `symbol_locate` 键，与 `--repo-context` / `--workbench` 的写法一致。
- 与协议层的差别：CLI 只认 `--symbol-locate` / `--no-symbol-locate` 两种写法，
  `--symbol-locate=false` 与 `--symbol-locate true` 都由 click 直接拒绝（`exit_code = 2`）——
  布尔开关在命令行上没有"带值"形式（同 click 既有的 flag 语义）。

```console
$ pr-review preferences          # 不传 = 只回显（默认开启），不创建配置文件
{
  "ui_language": "zh-CN",
  "language": "zh-CN",
  "chat_layout": "compact",
  "output_format": "terminal",
  "auto_publish_comment": false,
  "workbench_mode": "auto",
  "repo_context": "tests+imports",
  "symbol_locate": true
}
$ pr-review preferences --no-symbol-locate
{ ... "symbol_locate": false }      # 落盘 preferences.symbol_locate = false；其它偏好与已保存的 Key 不动
$ pr-review preferences --symbol-locate
{ ... "symbol_locate": true }
```

（逐字来自 §5 的离线联调脚本 [A]；两条命令都真的落盘，`AppConfig.load()` 读回同一个值。）

## 5. 测试与证据

命令：`New-Item -ItemType Directory -Force -Path .pytest_claude`；`TEMP`/`TMP` 指向该目录；
`python -m pytest -q --no-cov`。

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m pytest -q --no-cov tests/test_jsonl_backend.py tests/test_cli.py` | **258 passed in 39.38s** = 基线 **231**（改动前实测）+ 新增 **27**（后端 24 + CLI 3） |
| 2 | `python -m pytest -q --no-cov`（全量） | **928 passed, 1 skipped in 88.81s**（全绿；`1 skipped` 是仓库既有的那条，与本次改动无关） |

`tests/test_jsonl_backend.py`（新增 24，全部落在既有 repo_context 小节之后的 `# L2 符号定位开关的配置入口` 小节）：

| 用例 | 断言要点 |
|---|---|
| `test_config_setup_persists_symbol_locate[8 组]`（`:3537`） | `false/true/0/1/"off"/"on"/" FALSE "/"True"` 八种写法都写入内存 + 落盘 + `config.options` 回显 |
| `test_config_setup_symbol_locate_does_not_touch_other_preferences`（`:3553`） | 同一次提交里的 `repo_context` / `workbench_mode` / `chat_layout` 一个都不改 |
| `test_config_setup_rejects_an_invalid_symbol_locate_and_writes_nothing[9 组]`（`:3568`） | `"maybe"/"yes please"/"tru"/""/2/-1/2.0/[]/{}` → 双语报错；内存与磁盘都保持上一次的合法值 |
| `test_config_setup_without_symbol_locate_keeps_the_stored_value[2 组]`（`:3600`） | 字段缺失 / 显式 `null`（旧 TUI 载荷）= 不重置成默认的 `true` |
| `test_config_options_and_model_status_expose_symbol_locate`（`:3616`） | 两出口同键同形、默认 `true`、可选值顺序 `[true, false]`、label 非空；关掉后两处同步 |
| `test_protocol_config_options_and_setup_carry_symbol_locate`（`:3636`） | **协议层**（`handle()` 分派）：`config.options` 暴露、`config.setup` 接受布尔与 `"on"`、非法值返回错误事件而非抛穿；既有 `repo_context` / `current.workbench_mode` 未被挤掉 |
| `test_symbol_locate_vocabulary_matches_the_config_layer`（`:3692`） | 24 个样本对拍 config 层与向导层的取值口径（见 §3） |
| `test_symbol_locate_switch_reaches_the_orchestrator_predicate`（`:3744`） | 落盘结果经 `AppConfig.load()` 读回后，编排器 `_symbol_locate_enabled()` 真的随之变化（消费逻辑本身由 `tests/test_symbol_locator.py` 覆盖） |

`tests/test_cli.py`（新增 3）：

| 用例 | 断言要点 |
|---|---|
| `test_cli_preferences_command_toggles_symbol_locate`（`:1200`） | `--no-symbol-locate` 落盘 `false` + 回显；再 `--symbol-locate` 落盘 `true`；其它偏好与已保存的 Key 不受影响 |
| `test_cli_config_preferences_alias_sets_symbol_locate`（`:1238`） | `config preferences` 别名同样生效 |
| `test_cli_preferences_command_echoes_symbol_locate_without_writing`（`:1253`） | 一个开关都不传：回显默认 `true`、**不创建配置文件**（无隐式写入） |

**离线联调**（不联网、不 spawn TUI，脚本落在 `TEMP` 指向的 `.pytest_claude/symbol-locate-demo/`）：

- [A] 真 CLI：`AI_PR_REVIEW_CONFIG=<tmp>/config.json python -m ai_pr_review preferences ...`
  —— 无参数只回显且目录不被创建；`--no-symbol-locate` 后 `json.load()` 读回 `false`；
  `--symbol-locate` 再回 `true`；`--help` 里能读到新开关。`--symbol-locate=false` / `--symbol-locate true`
  都被 click 拒绝（`exit=2`）。
- [B] 真协议：`JsonlBackend.handle()` 直连 —— `config.options.symbol_locate` =
  `{"value": true, "options": [{"value": true, "label": "开启 / On"}, {"value": false, "label": "关闭 / Off"}]}`；
  `config.setup {symbol_locate: false}` → `ok: true`，`model.status.symbol_locate.value = false`；
  `config.setup {symbol_locate: "sometimes"}` → `ok: false`、`code: backend_error`、
  消息 `请求失败：符号定位仅支持 true 或 false。（symbol_locate accepts true or false.）`，
  且之后内存里的值仍是 `false`（非法值没有改动任何状态）。

**未回归**：既有 231 个用例（含 `test_config_setup_*repo_context*`、
`test_protocol_config_options_and_setup_carry_repo_context`、`test_cli_preferences_*`）全部原样通过，
未改动一字；三个出口都是**加法式扩展**（`_setup_options` / `model.status` 只多一个键，
`_apply_setup` 只多一个可选入参）。

## 6. 交付文件

| 文件 | 变更 |
|---|---|
| `src/ai_pr_review/backend/jsonl_server.py` | 新增 `SYMBOL_LOCATE_CHOICES` / `SYMBOL_LOCATE_TRUE_VALUES` / `SYMBOL_LOCATE_FALSE_VALUES`（`:132-143`）、`_symbol_locate_options()`（`:686`）、`_coerce_symbol_locate()`（`:701`）；`config.options` 挂载（`:838`）、`model.status` 挂载（`:1176`）、`config.setup` 写入（`:1022`） |
| `src/ai_pr_review/cli.py` | `preferences` 新增 `--symbol-locate/--no-symbol-locate`（`:3480`）、参数签名（`:3496`）、落盘与回显（`:3522-3527`） |
| `tests/test_jsonl_backend.py` | 新增 24 个用例（`:3537` 起） |
| `tests/test_cli.py` | 新增 3 个用例（`:1200` 起） |
| `docs/claude-symbol-locate-config.md` | 本文件 |

## 7. 未决项 / 边界

1. **`config.snapshot` 不带 `symbol_locate`**（刻意，见 §1）：本任务的"三出口"是
   `config.setup` / `config.options` / `model.status`，且 TUI 预选该屏只需 `config.options`。
   若后续 TUI 任务想在状态栏常显这个开关，加一行
   `"symbol_locate": self.config.preferences.symbol_locate` 即可（与 `workbench_mode` 同形）。
2. **TUI 未接**：`frontend/tui` 没有这一屏（本任务写域不含前端），配置文件与协议/CLI 侧已就绪。
3. **`normalize_symbol_locate` 的写法清单是"重列"的第二份**：由
   `test_symbol_locate_vocabulary_matches_the_config_layer` 钉住口径，但两份表仍是两处维护；
   彻底消除需要在 `config.py` 导出取值常量（不在本任务写域：任务明确要求不改 `config.py`）。
4. **`review_orchestrator._symbol_locate_enabled()` 读的是 `getattr(..., True)`**：即使配置里缺失该字段
   也等价于开启——这与 `DEFAULT_SYMBOL_LOCATE = True` 一致，不是本任务引入的。
5. **协议层错误码沿用既有映射**：非法 `symbol_locate` 与其它 `config.setup` 校验失败一样归为
   `backend_error`，正文前会带通用的"请求失败："前缀（`docs/claude-repo-config.md` §6.7 的同一现象）。
6. **本任务没有改 `config.py` / `symbol_locator.py` / `review_orchestrator.py` 任何一行**：
   字段、归一化函数与消费逻辑（签名变化触发）此前已存在，缺的只是入口。
7. 未做 git 操作、未联网、未读取或输出任何凭据；`.pytest_claude/` 是本任务的 pytest 临时目录，
   联调产生的配置文件（含 `symbol-locate-demo/`）都在其中。

## 8. 独立复核（只读子 agent）

交付后用只读子 agent 对拍了一遍任务 prompt 的 5 项交付与写入范围（它未执行 pytest，测试数字以 §5 为准）：

| 复核发现 | 处理 |
|---|---|
| (1)-(5) 逐项确认落地，`file:line` 与本报告一致；`_coerce_symbol_locate` 只有 `ConfigValidationError` 一条抛出路径（检查都在 `isinstance` 之后，不存在 `TypeError` 漏网） | 无需改动 |
| 取值口径与 `config.normalize_symbol_locate` **无漂移**：接受集合逐字相同（bool / `0\|1` / `true,1,yes,on` / `false,0,no,off`，strip+lower）；差异只有"告警回退 vs 报错"这一处刻意设计。float `1.0` 两侧一致拒绝 | 无需改动（`:3692` 的对拍用例就是这条证据） |
| CLI 三态语义在 **click 8.5.0**（pytest 实际用的版本）上实测：省略 → `None`、`--symbol-locate` → `True`、`--no-symbol-locate` → `False`；`click>=8.0` 用 `_missing` 哨兵而非 `None` 判定"未传"，该写法在 8.x 稳定 | 无需改动 |
| 未发现"功能坏掉也会通过"的用例：`persists_*` 对内存与 `AppConfig.load()` 双重断言（原始 `0`/`"off"` 直接赋值会失败）、`options/model.status` 先 `True` 后 `False`（写死 `True` 会失败）、编排器谓词那条改的是 `review_orchestrator.py:543` 真正读的字段 | 无需改动 |
| **原子性边界**（既有，非本次引入）：`_apply_setup` 逐项赋值、末尾统一 `save()`，同一载荷里更靠后的字段失败时，更靠前的字段已在内存里改过（磁盘未写），例如 `{"ui_language": "en-US", "symbol_locate": "sometimes"}` | §2 的精度说明补上这个反向例子 |
| 抽查强度：`does_not_touch_other_preferences` 只验 3 个字段；`rejects_*` 的"不写盘"只验本字段与磁盘 | 保留——目标（"开关是加法式的"）已被钉住，全字段对拍会与既有 `repo_context` 用例重复 |
| 写入范围：`git status` 只有 `jsonl_server.py` / `cli.py` / `tests/test_cli.py` / `tests/test_jsonl_backend.py` 被改 + 新增本文件，**`config.py` / `symbol_locator.py` / `review_orchestrator.py` 与 HEAD 逐字节相同**；对既有文件的改动是纯加法（`git diff --stat`：391 insertions / 1 deletion） | 符合约束 |
| `.agent-bus/.gitignore` 被删掉了一行 `runs/`，不在 write_scope | **非本任务产生**：会话开始时的 `git status` 已是如此，该文件 mtime（13:25:03）早于本任务被认领的时间（13:25:14），且 `scripts/agent_bridge.py` 每条命令都会重写它。未触碰，留给集成方判断 |
