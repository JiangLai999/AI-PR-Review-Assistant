# P6 交付报告：审查工作台配置项与配置助手/命令支持（任务 `claude-p6-workbench-setting`）

**一句话结论**：`PreferencesConfig` 新增 `workbench_mode: str = "auto"`，取值只在
`auto|always|off` 内，非法值**回退 auto + 记录一次 `RuntimeWarning`，不抛异常**（旧配置必须能加载）；
配置助手第 6 阶段新增「审查工作台」三选一（中英文案 + 说明），第 2 阶段整体重建
`PreferencesConfig` 时把该字段原样带回；非交互命令 `pr-review preferences --workbench auto|always|off`
落地，并按契约注册同一实现的 `pr-review config preferences` 入口；`AppConfig.save/load` 往返保留，
`config export` / `config show` 的 preferences 视图（`__dict__`）自动带上该字段。
TUI 侧真正读取的 `JsonlBackend._config_snapshot()` 由 Codex 的并发集成提交补齐
（`jsonl_server.py:456/534/690-694`，见 §6 第 6 段实测）——**本任务报告提交时该键尚不存在**，
当时的实测证据与补丁见 §7.1。

- 任务类型：实现（写入范围：`src/ai_pr_review/config.py`、`src/ai_pr_review/cli.py`、
  `src/ai_pr_review/config_commands.py`、`tests/test_config.py`、`tests/test_cli.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**639 passed, 1 skipped in 71.72s**（改动前基线 613 passed / 1 skipped，与
  `docs/claude-p6-report-filtered-payload.md` 记录一致；本轮新增 26 个用例 = 613 + 26 = 639）。
  Codex 的并发集成提交（`jsonl_server.py`）落地后在同一工作树复跑：**639 passed, 1 skipped
  in 81.42s**（§6.1）
- 未做：`config_commands.py` 一行未改（理由见 §3.4）；未读/打印凭据；未执行任何 git 操作；
  未改 `frontend/tui`；未改 write_scope 之外的文件（含 `backend/jsonl_server.py`、
  `frontend/tui/src/app.tsx`、`docs/workbench-phase1-contract.md`）

## 1. 缺口（改动前实测）

| 证据 | 位置 | 结果 |
|---|---|---|
| 契约已定字段与三选一语义 | `docs/workbench-phase1-contract.md:23-29,97-105` | 契约先于实现 |
| 配置层完全没有该字段 | `src/ai_pr_review/config.py`（改动前 `PreferencesConfig` 7 个字段） | 改动前 `grep -rn workbench_mode src/ tests/` 无命中（只有任务 JSON 与契约文档） |
| 向导第 2 阶段**整体重建** `PreferencesConfig` | `cli.py:1115-1123`（改动前，字段逐个列出） | 任何新字段只要没被列进这次重建，就会在每次跑向导时被静默重置为默认值——这是本任务最容易漏的回归点 |
| 非交互入口没有该参数 | `cli.py:3407-3452`（改动前 `preferences` 只有 ui-language/response-language/chat-layout/output-format） | 无法脚本化设置 |
| 后端快照逐字段列举 | `backend/jsonl_server.py:441-461`（本任务开工时） | `_config_snapshot()` 不含 `workbench_mode`；该缺口已由 Codex 并发提交补齐（§6 第 6 段 / §7.1） |

后果：即便配置层写好了，用户跑一次 `pr-review config`（向导）就会丢掉刚设的工作台偏好；
TUI 侧也没有任何可读的值来源。

## 2. 实现

### 2.1 `config.py`：字段、归一化与加载

```python
WORKBENCH_MODES: tuple[str, ...] = ("auto", "always", "off")   # config.py:585
DEFAULT_WORKBENCH_MODE = "auto"                                # config.py:586

def normalize_workbench_mode(value: object) -> str:            # config.py:589-605
    normalized = str(value or "").strip().lower()
    if normalized in WORKBENCH_MODES:
        return normalized
    warnings.warn("配置项 preferences.workbench_mode 的值不受支持，已回退为 auto"
                  "（可选值：auto、always、off）。", RuntimeWarning, stacklevel=2)
    return DEFAULT_WORKBENCH_MODE

@dataclass
class PreferencesConfig:
    ...
    workbench_mode: str = DEFAULT_WORKBENCH_MODE               # config.py:619

    def __post_init__(self) -> None:                           # config.py:621-623
        self.workbench_mode = normalize_workbench_mode(self.workbench_mode)
```

| 输入（配置值） | 结果 | warning |
|---|---|---|
| `"auto"` / `"always"` / `"off"` | 同值 | 无 |
| `" Always "` / `"OFF"` / `"Auto"` | `always` / `off` / `auto` | 无（与 `hybrid_strategy` 的 `.strip().lower()` 同风格，`config.py:877`） |
| 字段缺失（旧配置 / 旧版本写出的文件） | `auto` | **无**（静默，旧配置照常加载） |
| `"expanded"` / `""` / `null` / 数字 / 布尔 / 数组 | `auto` | 一次 `RuntimeWarning`，不抛异常 |
| 未知键（新版本写出的其它 preferences 字段） | 忽略该键 | 无（`_filter_dataclass_payload`，`config.py:1013-1018`） |

`_apply_payload` 改用既有的 `_filter_dataclass_payload(PreferencesConfig, …)`
（`config.py:1016-1018`）：这正是该 helper docstring 里写的场景——"用户配置比 CLI 版本活得久"。
`workbench_mode` 是新增字段，新版本写出的配置若被旧安装读到，不能在这里直接 `TypeError` 崩掉。

### 2.2 配置助手（`cli.py`）

第 6 阶段 `_prompt_preferences`（`cli.py:1131-1217`）新增「审查工作台」三选一：

| 值 | 中文标签 | English label |
|---|---|---|
| `auto`（默认） | 自动展开（审查时展开） | Auto (expand on review) |
| `always` | 常驻（始终保持展开） | Always (keep it open) |
| `off` | 仅手动（Alt+W 打开） | Off (open with Alt+W) |

- TTY 走既有 `_pixel_select`（`cli.py:1166-1179`），选项与默认值取自当前配置；
- 非 TTY 走既有 `Prompt.ask(..., choices=...)` 分支（`cli.py:1197-1205`），与
  output_format / auto_publish 的问法一致，脚本化输入用空行即接受当前值；
- 第 2 阶段 `_prompt_interface_preferences` 不提问该字段，但返回值里必须带回
  （`cli.py:1127`），否则跑一次向导就重置；配置摘要新增一行
  「审查工作台 / Review workbench」（`cli.py:1240`）。

### 2.3 非交互命令（`cli.py:3441-3504`）

```python
@click.option("--workbench", type=click.Choice(list(WORKBENCH_MODES)), default=None, ...)
...
if workbench is not None:
    config.preferences.workbench_mode = workbench
    config.save(config_path, save_key=_active_config_has_saved_api_key(config_path))
payload["workbench_mode"] = config.preferences.workbench_mode
...
config_command.add_command(preferences_command, "preferences")   # cli.py:3504
```

- 参数校验交给 `click.Choice`：非法值 exit 2 + `Invalid value for '--workbench'`，**不写盘**；
- `payload` 始终带 `workbench_mode`（未传参时回显当前值），与其他字段一样供脚本读取；
- 契约写的是 `pr-review config preferences --workbench …`，既有实现是顶层
  `pr-review preferences`；两个入口复用同一个命令对象，校验逻辑只有一份。

## 3. 语义选择

1. **回退放在 `__post_init__`**：`PreferencesConfig` 的构造入口只有 dataclass 一个，
   `load` / `config import` / 向导 / 测试因此共用同一套规则，不会出现"某条路径漏校验"。
   不抛异常是硬要求——配置坏了也要能进 `pr-review config` 去修。
2. **大小写与空白归一化（不告警）**：与 `hybrid_strategy`（`config.py:877`
   `.strip().lower()`）保持一致；手工编辑出的 `"Auto"` 不该算"非法值"。
3. **warning 不回显原值**：配置内容可能含终端控制字符或误粘贴的密钥，
   与 `config.py:919-925`（`AI_PR_REVIEW_PROVIDER` 越界时只报"值不受支持"）同一处理原则。
4. **`--workbench` 的落盘写在 `cli.py`，不进 `workspace_entry.apply_workspace_preferences`**：
   后者不在本任务写入范围。代价是同时传 `--workbench` 与其它参数时会写盘两次（幂等覆盖）；
   收益是不必跨模块扩大改动，且两个命令入口仍共用一份实现。后续若要合并，把该字段加进
   `apply_workspace_preferences` 的签名即可，`cli.py` 侧删掉这个 `if` 分支。
5. **未知 preferences 键忽略**：只影响"新版本配置被旧版本读"的方向，与
   `_filter_dataclass_payload` 的既定意图一致；用户把键名拼错时不再报错（这是刻意的取舍，
   与 `ai_client` 段现有行为相同）。
6. **字段加在 dataclass 末尾**：既有代码全部用关键字构造（已核对 `src/` 内 5 处），
   位置参数兼容性不受影响。

## 4. 测试

| 文件 | 新增用例（26 个） |
|---|---|
| `tests/test_config.py`（新文件，20 个用例 / 9 个函数） | `test_workbench_mode_defaults_to_auto:46`（默认值 + 常量形状）、`test_workbench_mode_accepts_supported_values_without_warning:54`（3 个合法值，断言**无** warning）、`test_workbench_mode_normalizes_case_and_whitespace:66`（4 组大小写/空白）、`test_workbench_mode_falls_back_to_auto_with_warning:73`（7 组非法输入 → auto + `RuntimeWarning`）、`test_load_legacy_config_without_workbench_mode_is_silent:80`（删掉键的旧配置 → auto 且**不告警**）、`test_load_invalid_workbench_mode_falls_back_and_keeps_other_settings:95`（坏值回退的同时 chat_layout/ui_language/provider 无损）、`test_load_ignores_unknown_preference_keys_from_newer_releases:113`、`test_workbench_mode_survives_save_load_roundtrip:127`（落盘 JSON 值 + 重新加载值）、`test_saved_preferences_view_carries_workbench_mode_for_snapshots:138`（`__dict__`/`asdict` 两种快照视图 + 重载后仍在） |
| `tests/test_cli.py`（6 个用例） | `test_cli_preferences_command_sets_workbench_mode:1089`（exit 0 + payload + 落盘 + 不动其它偏好 + 保留已存 Key）、`test_cli_config_preferences_alias_sets_workbench_mode:1117`（契约里的 `config preferences` 入口）、`test_cli_preferences_command_rejects_invalid_workbench_mode:1131`（exit 2 + `Invalid value` + **不创建配置文件**）、`test_cli_config_export_snapshot_carries_workbench_mode:1144`（`config export` 与 `config show` 的 preferences 视图）、`test_cli_config_quick_wizard_sets_workbench_mode:1172`（向导第 6 阶段写入）、`test_cli_config_quick_wizard_keeps_existing_workbench_mode:1205`（已存 `off` + 空行接受默认 → 仍是 `off`，钉住第 2 阶段不重置） |

**既有形状测试无回归**：5 个脚本化向导用例的输入脚本按"新增一道提问"更新
（`tests/test_cli.py:1641,1672,1692,1714,1746` 的用例，各插入一行空行 = 接受默认值），
`test_cli_preferences_command_updates_preferences` 追加一条 `workbench_mode == "auto"` 断言；
其余断言一字未改。全量 639 passed。

## 5. 变异检查（防止用例假绿）

| 变异 | 重跑范围 | 结果 |
|---|---|---|
| M1：`__post_init__` 去掉归一化（`self.workbench_mode = self.workbench_mode`） | `tests/test_config.py tests/test_cli.py` | **12 failed, 91 passed**（全部是非法值/大小写/加载回退用例）；随后逐字还原 |
| M2：第 2 阶段固定 `workbench_mode=DEFAULT_WORKBENCH_MODE` | `-k workbench` | **1 failed, 5 passed**——失败的正是 `test_cli_config_quick_wizard_keeps_existing_workbench_mode`（`assert 'auto' == 'off'`） |
| M3：命令里去掉 `config.save(...)`（只改内存） | `-k workbench` | **2 failed, 4 passed**——两个写入用例因配置文件不存在而 `FileNotFoundError` |

三处均逐字还原，`grep -rn MUTATION-CHECK src/ tests/` 无残留，还原后全量复跑 **639 passed**。

## 6. 本地端到端实测（离线，无网络、无凭据）

`.pytest_x/p6_workbench_setting_sample.py`（产物 `.pytest_x/p6_workbench_setting_sample.txt`）：
全程走真实组件——`CliRunner` → `cli.main` → `AppConfig.save/load` → `JsonlBackend`，
无任何桩：

```text
== 1. 非交互命令写入 ==
pr-review preferences --workbench off  -> exit=0
  payload.workbench_mode = off
  file.preferences.workbench_mode = off
pr-review config preferences --workbench always  -> exit=0
  payload.workbench_mode = always
  file.preferences.workbench_mode = always

== 2. 非法参数被 CLI 拒绝（不写盘） ==
pr-review preferences --workbench expanded  -> exit=2
  error = Error: Invalid value for '--workbench': 'expanded' is not one of 'auto', 'always', 'off'.
  file.preferences.workbench_mode = always  (未被改动)

== 3. save/load 往返 + 快照视图 ==
AppConfig.load().preferences.workbench_mode = off
asdict(preferences)['workbench_mode']      = off
config export 载荷 (config export 用的同一视图) = off
JsonlBackend._config_snapshot() 键含 workbench_mode = True  (TUI config.snapshot)

== 4. 旧配置与手改坏值 ==
旧配置（无该字段） -> workbench_mode=auto, warnings=[]
坏值 expanded      -> workbench_mode=auto, warnings=['配置项 preferences.workbench_mode 的值不受支持，已回退为 auto（可选值：auto、always、off）。']

== 5. 后端 config.apply(runtime) 之后仍在 ==
config.apply 之前 -> always
after config.apply runtime=local -> always
after config.apply 落盘值        -> always

== 6. TUI 后端路径：config.snapshot / config.setup ==
config.snapshot.workbench_mode = 'always'
config.options.current.workbench_mode = None
config.options.workbench_modes = ['auto', 'always', 'off']
config.setup workbench_mode=off -> snapshot 'off', 落盘 'off'
config.setup workbench_mode=expanded -> ConfigValidationError: 审查工作台仅支持 auto、always 或 off。
```

第 5 段走的是后端真实的 `_apply_runtime_profile("local")`（内部 `config.save` + 返回
`_config_snapshot()`）：运行时策略切换、重新加载、再落盘都不会丢掉该字段。
第 6 段是 Codex 并发集成提交落地后的复跑：`config.snapshot` 带值、`config.setup` 能写能校验、
非法值被后端拒绝——"配置层 → 快照 → TUI"这条链路闭环。**本任务首次跑该样例时第 3 段是
`False`、也没有第 6 段**，当时的结论与补丁记录在 §7.1（本任务的 JSONL 报告已提交且不可改写，
以本节复跑为准）。

### 6.1 TUI 后端路径复跑（Codex 补齐快照之后）

| 检查 | 结果 |
|---|---|
| `JsonlBackend._config_snapshot()["workbench_mode"]` | `'always'`（与落盘值一致） |
| `JsonlBackend._setup_options()["workbench_modes"]` | `['auto', 'always', 'off']`（三选一交给 TUI 渲染） |
| `JsonlBackend._setup_options()["current"]["workbench_mode"]` | `None` —— 见 §7.1 的遗留小缺口 |
| `_apply_setup({...,"workbench_mode":"off"})` | snapshot `'off'` + 落盘 `'off'` |
| `_apply_setup({...,"workbench_mode":"expanded"})` | `ConfigValidationError: 审查工作台仅支持 auto、always 或 off。`（未写盘） |
| `app.tsx:2418` | `String(runtime().workbench_mode ?? "").trim().toLowerCase()`，缺键/坏形状不会崩 |

## 7. 未决项 / 边界

1. **后端快照携带：已由 Codex 并发补齐，遗留两个小口子。**
   本任务开工时的实测是 `'workbench_mode' in JsonlBackend._config_snapshot() == False`
   （`jsonl_server.py` 逐字段列举，且不在本任务 write_scope）；提交报告后 Codex 的集成提交落地了
   `jsonl_server.py:456`（快照）、`:534`（三选一选项）、`:690-694`（`config.setup` 写入 + 校验），
   §6.1 复跑确认闭环。剩余：
   - `_setup_options()["current"]` 没有回显 `workbench_mode`（实测 `None`；偏好回显段在
     `jsonl_server.py:559-563`，`chat_layout` 就在最后一行），所以 TUI 设置向导打开时无法把
     "当前值"预选出来；建议紧挨 `chat_layout` 加一行。
   - `jsonl_server.py:692` 把合法值**硬编码**为 `{"auto","always","off"}`，而配置层导出的常量是
     `WORKBENCH_MODES`（`config.py:585`）。两处目前一致，但改一处忘另一处就会漂移；建议后端
     `from ai_pr_review.config import WORKBENCH_MODES` 后 `workbench_mode not in WORKBENCH_MODES`。
   （本任务的 bus 报告在 Codex 提交之前生成，`--status completed` 不可改写，故以 §6.1 的复跑为准。）
2. **前端未验证**：未运行 `frontend/tui` 的测试/构建（禁止改动）；`app.tsx` 侧对
   `auto/always/off` 的解释由 Codex 的集成任务落地，本任务只保证值在配置层与导出视图里可取。
3. **文档未同步**（不在写入范围）：`README.md` / `docs/API.md` 的 `pr-review config …`
   子命令列表没有 `preferences`（本任务新增的别名入口），建议集成方补一行。
4. **`config_commands.py` 未改动**：该模块现有三个 helper 都是"命令 → 服务"的转发，
   本任务的 `--workbench` 只是一次属性写入 + `save`，直接落在 `cli.py` 的命令里更贴近既有
   `apply_workspace_preferences` 的用法；如后续要统一，建议把工作台字段并入
   `workspace_entry.apply_workspace_preferences` 的签名（见 §3.4），而不是再开一个 helper。
5. **双入口写盘两次**：`--workbench` 与其它参数同时给出时 `save()` 会执行两次（第二次覆盖同一文件，
   幂等）；`save_key=False` 且存在 Key 时 `save()` 会发一次 `RuntimeWarning`，两次调用即两次告警。
   实测命令路径 `save_key_checker` 命中已保存的 Key，因此走 `save_key=True`，不触发该告警。
6. **未覆盖**：`workbench_mode` 的 TUI 渲染矩阵、`Alt+W` 快捷键、`/workbench` 命令、
   窄屏状态条均属前端任务，未在本任务验证；本任务也未改动 `tui_static`（Codex 负责重建）。
