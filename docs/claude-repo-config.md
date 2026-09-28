# 后端与协议交付报告：repo_context 可配置化 + `/model chat|review` 子命令（任务 `claude-repo-config`）

**一句话结论**：仓库上下文（`preferences.repo_context`）现在可以从协议与命令行改动——
`config.setup` 接受可选 `repo_context`（`off | tests | tests+imports`，非法值抛
`ConfigValidationError` 且整单不落盘），`config.options` / `model.status` 给出当前值与可选值，
`config.snapshot` 带上当前值；`/model` 新增 `chat` / `review` 两个子命令，各自写入**该槽位实际会用的
那个 provider**（与 `_chat` / `ModelSelector` 的槽位判定同一套规则），裸模型名保持旧行为
（= `/model chat <name>`），缺参/多参给出 actionable 用法说明；`pr-review config preferences`
新增 `--repo-context`。TUI 界面按任务约定留给后续任务。

- 任务类型：实现（写入范围：`src/ai_pr_review/backend/jsonl_server.py`、`src/ai_pr_review/cli.py`、
  `tests/test_jsonl_backend.py`、`tests/test_cli.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**854 passed, 1 skipped in 73.93s**（全量，同命令复跑一次为 87.58s，均全绿）；
  本任务自己的两个文件
  `tests/test_jsonl_backend.py tests/test_cli.py`：**222 passed**
  = 既有 206 个用例（未改动一字）+ 本任务新增 **16 个用例**（后端 13 + CLI 3）
- 未做：未读/打印凭据；未执行任何 git 操作；未改 `frontend/tui`（界面留后续任务）、
  未改 `config.py` 字段定义、未改 `workspace_entry.py`（`--repo-context` 因此按
  `--workbench` 的既有写法落在 `cli.py` 内）；未联网

## 1. `repo_context` 的协议出口

三个出口的**键名相同、形状不同**（刻意，见 §6.2）：

| 出口 | 形状 | 位置 |
|---|---|---|
| `config.snapshot` | 纯字符串当前值（与 `workbench_mode` 等偏好一致） | `jsonl_server.py:575` |
| `config.options` | `{"value": str, "options": [{"value", "label"}]}` | `jsonl_server.py:724`、组装点 `:597` |
| `model.status` | 同上（与 `config.options` **同键同形**，供状态栏直接渲染） | `jsonl_server.py:1050` |

```json
{
  "repo_context": {
    "value": "tests+imports",
    "options": [
      {"value": "off", "label": "关闭 / Off"},
      {"value": "tests", "label": "仅测试文件 / Tests only"},
      {"value": "tests+imports", "label": "测试与依赖 / Tests + imports"}
    ]
  }
}
```

- 取值清单直接来自 `config.REPO_CONTEXT_MODES`（`config.py:629`），后端与前端都不再各存一份；
  label 也由后端给出，TUI 不需要硬编码中文（与 `runtime_profiles` / `chat_layouts` 同一惯例）。
- `value` 是**落盘值**：config 层已保证合法（非法值在加载时回退 `tests+imports` 并告警，见
  `config.py:684-692`）。

## 2. `config.setup`：三态、非法值、部分更新

`_apply_setup`（`jsonl_server.py:893-902`）：

```python
repo_context = str(params.get("repo_context") or "").strip().lower()
if repo_context:
    if repo_context not in REPO_CONTEXT_MODES:
        raise ConfigValidationError(
            "仓库上下文仅支持 off、tests 或 tests+imports。"
            "（repo_context accepts off, tests or tests+imports.）"
        )
    preferences.repo_context = repo_context
```

| 输入 | 行为 |
|---|---|
| `"off"` / `"tests"` / `"tests+imports"`（大小写、首尾空格不敏感） | 写入 `preferences.repo_context`，随同一次 `save()` 落盘 |
| 其它任意值 | `ConfigValidationError`，**整单失败**：磁盘与内存都保持原值 |
| 字段缺失 / `null` / `""` | 保持不变（与 `ui_language`、`output_format` 等偏好一致的部分更新语义） |

与加载路径的区别是刻意的：加载旧配置时非法值只告警回退（`config.normalize_repo_context`），
而向导里的非法值是用户刚刚做出的选择，静默改成别的档位比报错更糟（同 `_setup_slot` 的理由）。

精度说明：`repo_context` 非法时，赋值语句在抛错之前就被跳过，所以内存与磁盘都不会变；但如果
同一载荷里**更靠后**的字段（如 `auto_publish_comment`）才校验失败，`repo_context` 可能已经在内存里
更新过（磁盘仍未写）。这与该方法里其它偏好的既有行为完全一致（它们都在同一个 `try` 里逐项赋值、
最后统一 `save()`），不是本任务新引入的。

**范围**：只做了 `repo_context` 这一档；`repo_context_max_files` / `repo_context_budget_tokens` /
`repo_cache_max_mb` 仍只走配置文件（任务未要求，见 §6）。

## 3. `/model` 子命令（`jsonl_server.py:1907-1944`）

| 写法 | 行为 |
|---|---|
| `/model` | 不变：`_model_status_text`（provider / 运行状态 / endpoint） |
| `/model status` | 不变：同上 + 结构化 `status` |
| `/model local\|cloud\|hybrid\|offline` | 不变：`_apply_runtime_profile`（清空槽位覆盖） |
| `/model chat <name>` | 切**聊天槽**模型（`_chat_slot_config()`） |
| `/model review <name>` | 切**审查槽**模型（`_review_slot_config()`） |
| `/model <name>` | 兼容旧行为：等同 `/model chat <name>` |

### 3.1 写入目标是"实际会用的 provider"

新增三个解析函数（`jsonl_server.py:946-978`），与各自消费方的判定**逐条一致**，避免"命令改 A、
运行时读 B"：

| 槽位 | 目标 provider | 与谁一致 |
|---|---|---|
| chat | 远端槽 → `config.provider`；显式本地槽 → `config.local_provider`；无显式槽时主 Provider 是 Ollama/Local 或本进程被 `AI_PR_REVIEW_PROVIDER` 覆盖 → `config.provider`，否则 `local_provider` | `_chat_slot_provider()`（`jsonl_server.py:1193`，`_chat` 实际用的那个；该函数现在就是 `_chat_slot_config().to_model_provider()`，只有一份判定） |
| review（remote / hybrid） | `config.provider` | `ModelSelector` 的远端槽；`_slot_model("hybrid")` 也报它——hybrid 没有单一模型，可写的是"能覆盖全部文件"的远端/升级模型 |
| review（local） | 主 Provider 是 Ollama/Local → `config.provider`，否则 `config.local_provider` | `ModelSelector.__init__` 的本地槽 |

写入本身走新的 `_apply_slot_model(target, name)`（`jsonl_server.py:926`）：`default_model` +
`ensure_default_model_present()` + `_sync_runtime_sections()` + `save(save_key=True)`，
与 `model.apply`（活跃槽）共用同一套步骤。

模型名**原样落盘**：旧代码把 `args` 整体 `.lower()`，`/model DeepSeek-V3` 会变成 `deepseek-v3`
写进配置；现在只有子命令与运行模式 token 大小写不敏感（`jsonl_server.py:1913-1916`）。

### 3.2 回执文本

命令返回 `{"text", "config", "status"}`（与其它 `/model` 分支同形，TUI 可继续读 `status`/`config`）：

```
对话模型已切换为 chat-model（本地槽 · Ollama (Local)）
审查模型已切换为 deep-x（混合槽 · DeepSeek）
注意：对话槽用的是同一个 Provider（DeepSeek），该槽的模型也会变为 deep-x。
混合策略：低风险文件仍由本地模型 qwen3.5:4b 审查。
```

- 第 2 行只在**两个槽指向同一个 Provider** 时出现：此时它们共用一份 `default_model`，改一个必然
  改到另一个（"聊天模型怎么变了"的困惑源头）。归属在写入**之前**判定——`AppConfig.save()` 会把
  活跃槽重建为新对象，写后再做 `is` 比较必然为假。
- 第 3 行只在 hybrid 出现，说明低风险文件仍走本地模型（本地模型不在本命令的写入范围内）。

### 3.3 错误（actionable）

| 输入 | 结果 |
|---|---|
| `/model chat` / `/model review` / `/model chat ""` | `ok: false`，`code: invalid_request`，消息含全部可用写法（`/model`、`/model status`、`/model chat <模型名>`、`/model review <模型名>`、`/model <模型名>`、`/model local\|cloud\|hybrid\|offline`） |
| `/model chat a b`（模型名带空格） | 同上（旧代码会静默丢掉多余 token） |
| `/model` 后跟未知子命令 | **不存在这一分支**：裸 token 一律按模型名处理（旧行为兼容） |
| `/model chat <不存在的模型名>` | **不校验、直接写入**：与 `model.apply` / `config model --name` 的既有语义一致（`_apply_model` 也只拒绝空名）。任意自定义/新发布的模型 ID 必须能用；`PROVIDER_MODEL_PRESETS` 不是白名单。写错名字的反馈来自下一次真实调用，而不是这里 |

## 4. CLI：`pr-review config preferences --repo-context`

- 选项定义 `cli.py:3473-3479`（`click.Choice(list(REPO_CONTEXT_MODES))`），
  落盘与回显 `cli.py:3508-3513`，两条入口 `pr-review preferences` 与
  `pr-review config preferences` 共用同一实现（`cli.py:3519` 的 `add_command`）。
- 非法值由 click 直接拒绝：`exit_code = 2`、`Invalid value`，配置文件不会被创建。
- 回执 JSON 增加 `repo_context` 键；未传该参数时输出当前值且**不触发额外写入**（与 `--workbench`
  的写法一致：都落在 `cli.py` 内，因为 `workspace_entry.apply_workspace_preferences` 不在
  本任务写入范围内）。

```console
$ pr-review config preferences --repo-context off
{
  "ui_language": "zh-CN",
  "language": "zh-CN",
  "chat_layout": "compact",
  "output_format": "terminal",
  "auto_publish_comment": false,
  "workbench_mode": "auto",
  "repo_context": "off"
}
```

## 5. 测试

`tests/test_jsonl_backend.py`（新增 16）：

| 用例 | 断言要点 |
|---|---|
| `test_config_setup_persists_each_repo_context_mode[off/tests/tests+imports]`（:3447） | 三态写入内存 + 落盘 + `config.snapshot` / `config.options` 回显 |
| `test_config_setup_rejects_an_invalid_repo_context_and_writes_nothing`（:3464） | 双语报错文案、内存与磁盘都保持上一次的合法值 |
| `test_config_setup_without_repo_context_keeps_the_stored_value`（:3483） | 旧载荷（无该字段）= 不重置 |
| `test_config_options_and_model_status_expose_repo_context`（:3497） | 两出口同键同形、清单来自 `REPO_CONTEXT_MODES`、默认档位 `tests+imports` |
| `test_model_command_without_arguments_keeps_reporting_the_current_model`（:3524） | 无参与 `/model status` 仍走原路径（新子命令没有挤掉旧分支） |
| `test_model_command_chat_writes_the_provider_chat_actually_uses`（:3542） | 写本地槽、远端槽不受影响、`routing.chat.model` 同步、落盘 |
| `test_model_command_review_writes_the_provider_review_actually_uses`（:3569） | 写远端槽、本地槽不受影响、`routing.review.model` 同步、落盘 |
| `test_protocol_config_options_and_setup_carry_repo_context`（:3594） | **协议层**（`config.options` / `config.setup` 的 `handle()` 分派）+ 非法值返回错误事件而非抛穿 |
| `test_model_command_review_local_slot_writes_the_local_provider`（:3635） | review 槽解析为 `local` 的分支 + 两槽不同 Provider 时**没有**"注意"提示 |
| `test_model_command_chat_with_a_primary_ollama_writes_the_primary_provider`（:3661） | 主 Provider 就是 Ollama 时写主槽（自定义端点/模型不丢），并钉住 `routing.chat.model` 的既有显示差异 |
| `test_model_command_review_in_hybrid_writes_the_upgrade_model_and_says_so`（:3692） | hybrid 写远端/升级模型 + 本地模型提示语 |
| `test_model_command_warns_when_both_slots_share_one_provider`（:3711） | 共用 Provider 的"注意"提示 |
| `test_model_command_bare_name_keeps_switching_the_chat_slot`（:3725） | 裸名 = chat 槽，且 `Qwen3.5:4B-Instruct` 大小写原样保留 |
| `test_model_command_rejects_incomplete_or_overspecified_subcommands`（:3744） | 缺参/多参 → `invalid_request` + 用法；磁盘无写入 |

`test_model_command*` 全部通过 `_offline_model_provider`（:2303）把 `create_model_provider`
换成无 `health_check` / `list_models` 的桩，`model.status` 不联网。

`tests/test_cli.py`（新增 3）：

| 用例 | 断言要点 |
|---|---|
| `test_cli_preferences_command_sets_repo_context`（:1144） | 回执 + 落盘 + 其它偏好与已保存 Key 不受影响 |
| `test_cli_config_preferences_alias_sets_repo_context`（:1173） | `config preferences` 别名同样生效（含 `tests+imports`） |
| `test_cli_preferences_command_rejects_invalid_repo_context`（:1187） | `exit_code=2`、`Invalid value`、不创建配置文件 |

**未回归**：既有 206 个用例（含 `test_custom_setup_*`、`test_config_and_model_snapshots_carry_routing`、
`test_runtime_switch_clears_the_slot_overrides`、`test_cli_preferences_*`）全部原样通过，未改动一字。

**重构等价性检查**：`_chat_slot_provider` 改为委托 `_chat_slot_config()`，用"改动前的原样逻辑"
在同一脚本里对拍 2（主 Provider：deepseek/ollama）× 3（运行模式预设）× 3（`chat_slot`：空/remote/local）
× 2（`AI_PR_REVIEW_PROVIDER` 覆盖开关）= **36 种组合，全部返回同一个 ProviderConfig 对象**
（`mismatches: 0`）。

## 6. 未决项 / 边界

1. **TUI 未接**（按任务约定）：`command-menu.ts` 仍只有 `/model`、`/model status` 两个补全项；
   配置助手的第 5 阶段还没有 `repo_context` 三选一。协议侧已就绪（`config.options.repo_context`
   提供 value + label，`config.setup` 接受该字段）。
2. **同名键两种形状**：`config.snapshot.repo_context` 是纯值（与 `workbench_mode` 等偏好一致），
   `config.options.repo_context` / `model.status.repo_context` 是 `{value, options}`。前者是
   "当前配置值"，后两者是"当前值 + 可选值"，文档即契约；若后续 TUI 觉得别扭，可统一成对象形状。
3. **两个槽共用一个 Provider 时无法分别设模型**：`default_model` 挂在 Provider 上，
   `chat_slot=remote` + `review_slot=remote` 天然共用一个模型；命令会用"注意"提示这一点。
   要真正分开必须让两个槽指向不同 Provider（`custom` 预设）。
4. **主 Provider 就是 Ollama 时 `routing.chat.slot` 仍显示"本地"对应的 `local_provider` 模型**
   （`_slot_model` 与 `_chat_slot_provider` 的既有差异，见 `claude-route-slots` 的交接）：
   `/model chat <name>` 写的是聊天**实际**会用的 provider（主 Provider），不会出现"改完不生效"。
   这条是本次刻意选择的语义：命令的有效性优先于状态栏的显示一致性。
   该差异由 `test_model_command_chat_with_a_primary_ollama_writes_the_primary_provider`
   （`tests/test_jsonl_backend.py:3661`）显式钉住——将来若有人修好 `_slot_model`，这个用例会红，
   提醒同一处要改的是显示而不是写入。
5. **`repo_context_max_files` / `repo_context_budget_tokens` / `repo_cache_max_mb` 未接入协议**，
   仍只能改配置文件；本次只做任务指定的 `repo_context` 档位。
6. **空串 = 保持不变**（不是"重置为默认"）：与 `ui_language` 等既有偏好一致；要回默认值需显式传
   `tests+imports`。
7. **协议层错误码沿用既有映射**：`config.setup` 里的 `ConfigValidationError` 与其它校验失败
   （缺 API Key、非法 `ui_language` 等）一样，经 `handle()` 的 `except Exception` 归为
   `backend_error`，消息末尾因此会带上通用的"检查模型状态后重试。"。双语正文能到达用户
   （TUI 显示 `error.message`），但那句通用恢复建议对配置校验并不贴切——这是既有行为，
   本任务没有改动它（改错误码会影响所有 `config.setup` 校验路径）。
8. **模型名不做白名单校验**（与 `model.apply` / `pr-review config model --name` 一致）：
   `/model chat <任意非空名>` 都会写入，`PROVIDER_MODEL_PRESETS` 不是白名单——自定义或新发布的
   模型 ID 必须能用，写错名字的反馈来自下一次真实调用。子命令位置则相反：`chat` / `review`
   现在会被当成子命令，真有模型叫这两个名字时需写 `/model chat chat`（旧行为里 `status` 等
   已有同样性质的位置保留）。
9. 未做 git 操作、未联网、未读取或输出任何凭据；`.pytest_claude/` 是本任务的 pytest 临时目录。

## 7. 独立复核（只读子 agent）与据此的补强

交付后用只读子 agent 对拍了一遍任务 prompt 的 6 项交付，结论与后续动作：

| 复核发现 | 处理 |
|---|---|
| (1)(2)(3)(5) 已实现；`_chat_slot_provider` 重构无行为漂移 | 另行用"改动前原样逻辑"对拍 36 种组合（§5 末尾），0 处不一致 |
| 覆盖缺口：review 的 local 分支、`_local_slot_config` 的主 Ollama 写入路径、`config.options`/`config.setup` 的协议层分派均无用例 | 补 3 个用例（`:3594`、`:3635`、`:3661`） |
| "两槽不同 Provider 时不应出现注意提示"没有断言 | 已并入 `:3635` |
| `/model chat <未知模型名>` 不报错，与"未知模型 → actionable 错误"的字面要求不符 | 不改为校验（会与 `model.apply` 语义冲突，且会误杀自定义模型 ID）；在 §3.3 与 §6 明确写清"不校验"的理由 |
| 文档"内存与磁盘都保持原值"的表述对"更靠后的字段才失败"不够精确 | §2 增加精度说明 |
| `.agent-bus/.gitignore` 有一处 `runs/` 被删除的改动不在 write_scope | **非本任务产生**（会话开始时 `git status` 已如此，且从未由我编辑）；未触碰，留给集成方判断 |
| 复核读到的是补数字之前的文档快照（`{{FULL_SUITE}}` 占位符） | 全文数字已实测填好（§5 与本节顶部） |
