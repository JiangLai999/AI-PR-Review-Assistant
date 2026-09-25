# 运行时与协议层交付报告：CHAT/REVIEW 双槽路由（任务 `claude-chat-routing`）

**一句话结论**：`backend/jsonl_server.py` 的聊天改为按 `resolve_chat_slot()` 选槽（`remote` = 持久化主
Provider、`local` = `local_provider`），配置助手新增 `custom` 预设（写两个槽位并折算
`hybrid_strategy`），`config.snapshot` / `config.options` / `model.status` 统一新增 `routing` 块，
既有事件与 payload 字段**一个都没改名、没删除**；同时补上了两处会让老用户被静默改道的例外
（`AI_PR_REVIEW_PROVIDER` 覆盖、主 Provider 本身就是 Ollama）与"选预设即清空槽位"的一致性。

- 任务类型：实现（写入范围：`src/ai_pr_review/backend/jsonl_server.py`、
  `tests/test_jsonl_backend.py`、本文件）
- 验证命令（**未运行，见 §5**）：`New-Item -ItemType Directory -Force -Path .pytest_claude` →
  `TEMP`/`TMP` 指向它 → `python -m pytest -q --no-cov`
- 结果：**未运行**。本会话的权限层拒绝了任何 Python 执行（含 `python -m pytest`、`python -c`、
  `python scripts/agent_bridge.py`），且"本会话没有审批入口"，无法由任何人批准。
  因此本任务**没有任何实测数字**，测试是"已写好、未执行"，`.agent-bus` 的上报也是人工按
  `report` 子命令的字段格式写文件（该命令同样跑不了，见 §5 末）。
- 未做：未读/打印凭据；未执行任何 git 操作；未改 `config.py`（前置任务 `claude-route-slots` 已完成）；
  未改 `frontend/tui`（P3 前端任务的范围）；未改 `services/model_selector.py`（计划 §5.1 #7 的独立任务）。

> 并发提示：本仓库多个 agent 共用一个工作树。本任务运行期间
> `src/ai_pr_review/services/repo_context.py`／`tests/test_repo_context.py` 等文件由其它任务并行改动。
> 本任务的改动只落在上表三个文件；如果 `jsonl_server.py` 在本报告之后被其它 agent 改动，
> 请以 `git diff` 为准重新核对 `_routing_snapshot` / `_chat` / `_apply_setup`。

## 1. 交付内容（含行号）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `jsonl_server.py:99-115` | 新增模块级常量：`ROUTE_SLOT_LABELS`（槽位展示名）、`ROUTE_PROFILE_BY_STRATEGY`（策略→预设）、`RUNTIME_PROFILES`（配置助手第 1 步的预设清单，含 `custom`="自定义"） |
| 2 | `jsonl_server.py:422` | `_infer_runtime_profile` 改用同一个 `ROUTE_PROFILE_BY_STRATEGY`（纯重构，行为逐字不变） |
| 3 | `jsonl_server.py:447-448` | `_apply_runtime_profile`（`/model cloud\|local\|hybrid\|offline`、`config.apply`）也清空两个槽位：它和配置助手的预设是同一类动作 |
| 4 | `jsonl_server.py:454-509` | 新增 `_has_explicit_value()` / `_has_explicit_slot()` / `_clear_route_slots()` / `_slot_model()` / `_routing_snapshot()`，推导只发生在这里 |
| 5 | `jsonl_server.py:563` | `_config_snapshot()` 新增 `routing` |
| 6 | `jsonl_server.py:617,684` | `_setup_options()` 新增 `runtime_profiles` 与 `routing` |
| 7 | `jsonl_server.py:688-710` | 新增 `_setup_slot()`：读一个槽位、缺失=部分更新、空串=清除、非法值报 `ConfigValidationError` |
| 8 | `jsonl_server.py:717,771,797-816` | `_apply_setup`：允许 `custom`；local/offline 分支改为显式 `elif`；custom 写槽位 + 折算；其余预设清空两个槽位 |
| 9 | `jsonl_server.py:903` | `_model_status()` 新增 `routing` |
| 10 | `jsonl_server.py:1043-1098` | 新增 `_chat_slot_provider()`；`_chat` 改为按槽选 provider |
| 11 | `tests/test_jsonl_backend.py:3040-3400` | 新增 12 个测试函数（其中 1 个参数化 3 例，共 14 个用例） |

## 2. 协议契约（`routing`）

三个出口（`config.snapshot` / `config.options` / `model.status`）返回同一形状：

```json
"routing": {
  "profile": "custom",
  "chat":   { "slot": "local",  "label": "本地", "model": "qwen3.5:4b" },
  "review": { "slot": "remote", "label": "云端", "model": "deepseek-flash" }
}
```

- `slot`：`remote` / `local`（`review` 额外允许 `hybrid`），**只由后端 `resolve_chat_slot()` /
  `resolve_review_slot()` 推导**，前端不得自行由 `hybrid_strategy` 反推（方案 §5.4）。
- `label`：`云端` / `本地` / `混合`，取自 `ROUTE_SLOT_LABELS`。按 §5.4 的示例给中文规范名，
  双语由前端 i18n 负责（与 `output_formats` 等"选项列表"不同，这是**状态**而非可选项）。
- `profile`：显式槽位存在时是 `custom`；否则由 `hybrid_strategy` 折算
  （`remote_only`→`cloud`、`local_only`→`local`、`balanced`→`hybrid`，未知/缺失→`cloud`）。
- `hybrid` 的 `model` 取**远端（升级）模型**：它是能覆盖全部文件的那个；本地模型由
  `slot="local"` 表达（与 `ModelSelector` 的 local/remote 两个槽一致）。

既有字段全部保留：`_config_snapshot()` 的 `provider`/`model`/`local`/`runtime_profile` 仍描述
**活跃槽**（`ai_client`），新增的 `routing` 才是两个槽各自的真相。二者在 `custom` 下会**故意**
不同（例：`chat_slot=local` + `review_slot=remote` 时 `provider` 是远端、`routing.chat.slot` 是本地）。

## 3. 关键决策与理由

1. **`_chat` 的本地豁免仍按"选中的 provider 名"判断**（`jsonl_server.py:1079`）。槽位与
   provider 名在合法配置下总是一致（本地槽只允许 Ollama/Local），但"主 Provider 本身就是
   Ollama"这种受支持的配置里，`remote` 槽指向的也是本地模型——它同样不需要 API Key、
   同样要关掉思考通道。非本地 provider 缺 Key 抛 `RuntimeError` 的行为**逐字保留**。
   （一度写成"按槽位判断"，会让环境覆盖下指向云端的 `local` 槽被塞 `reasoning_effort`、
   并漏掉缺 Key 的错误——复核发现后已改回按 provider 名判断。）
2. **`_apply_setup` 的 `custom` 不碰凭据**。细化页只决定"用哪个槽"，不决定槽里配了什么；
   远端槽的 Key / 本地槽的端点仍由各自的 provider 配置与既有预设流程负责。
   代价：`custom` + 未配 Key 的远端槽不会在向导里被拦下，而是聊天时报
   `Missing API key for provider: ...`（已由 `_classify_error` 归到 `missing_api_key`）。
   若上游希望向导阶段就拦住，应在 P3 前端按"用到的槽"收集凭据（方案 §4.3）。
3. **预设清空槽位**：`cloud`/`local`/`hybrid`/`offline` 一律把两个槽位置 `""`，即使载荷里带了
   `chat_slot`/`review_slot` 也**忽略而不报错**（方案 §5.2 #13：预设不发送这两个字段）。
   这样"用户选了预设"就等价于"回到单一事实来源"，不会残留上一次的 custom。
4. **`custom` 的原子性**：两个槽位都校验通过之后才赋值（`jsonl_server.py:780-798`），
   任一非法 → 整单失败，磁盘和内存都不留半套状态。
5. **`offline` 不进 `runtime_profiles`**：它是旧值、读取时等价于"本地"，`_apply_setup` 继续接受
   以保持旧载荷兼容，但不再作为向导选项提供（方案 §4.1 的界面只有 4 档）。
6. **`model.status` 顶层字段不动**：`model.apply`（`/model <name>`）写的是**活跃槽**，
   若顶层改报聊天槽，状态与随后的写入会互相矛盾。切槽命令（`/model chat|review`）是
   计划 §5.3 的独立任务，本任务不做。**代价见 §6 第 2 项**：在 `custom` 下 `/model <name>`
   改的是活跃槽、聊天用的是 `routing.chat`，两者会不同——但 `custom` 目前还没有入口（§6 第 3 项），
   所以现有可达路径上二者始终一致。
7. **`local` 槽的两个例外**（`jsonl_server.py:1057-1066`，只在**没有**显式 `chat_slot` 时生效）：
   本进程被 `AI_PR_REVIEW_PROVIDER` 覆盖、或主 Provider 自己就是 Ollama/Local 时，"本地槽"
   本来就等于主槽（`config._active_provider_config()` 与 `ModelSelector.__init__` 都是这么判定的）。
   不加这两个例外，`local_only` 的老用户会从自己配的 Ollama 端点悄悄换到默认端点，
   `AI_PR_REVIEW_PROVIDER=deepseek` 的"本进程用云端"也会对聊天失效——两者都是改造前没有的回归。

## 4. 测试清单（已写、未运行）

| 用例 | 断言要点 |
|---|---|
| `test_chat_uses_the_local_slot_provider_when_chat_slot_is_local` | 活跃槽停在远端（strategy=remote_only）时，聊天仍走 `local_provider` 的 name/model/base_url/api_format，且仍传 `reasoning_effort="none"` |
| `test_chat_uses_the_remote_slot_provider_when_chat_slot_is_remote` | 反向：活跃槽是本地时聊天仍打远端，且**不**传 `reasoning_effort` |
| `test_chat_without_a_key_on_the_remote_slot_is_a_missing_api_key` | 远端槽缺 Key → 协议层返回 `ok:false` + `code="missing_api_key"`（`_chat` 的 RuntimeError 被协议边界转成事件，不冒泡），且失败后 `chat_cancellations` 为空 |
| `test_custom_setup_writes_slots_and_folds_hybrid_strategy`（3 例） | `remote/local/hybrid` → `remote_only/local_only/balanced`，且落盘后 `AppConfig.load` 读回一致 |
| `test_custom_setup_keeps_the_slot_it_was_not_given` | 只传一个槽位=部分更新；显式 `""`=清除该槽覆盖 |
| `test_custom_setup_rejects_invalid_slots_and_writes_nothing` | 非法槽位报 `ConfigValidationError`（`chat_slot="hybrid"` 也必须被拒），失败后磁盘无文件、内存无残留 |
| `test_switching_to_a_preset_clears_both_slot_overrides` | 预设清空两个槽位（载荷里带着也要清），`routing` 回到 `cloud/remote/remote` |
| `test_config_options_expose_routing_and_the_custom_preset` | `runtime_profiles` 含 `custom="自定义"`；默认 `profile="hybrid"`；custom 后两个槽的 label/model 正确 |
| `test_config_and_model_snapshots_carry_routing` | `config.snapshot` / `config.options` / `model.status` 三个出口的 `routing` 完全一致；顶层 `provider`/`model`/`runtime_profile` 仍描述活跃槽 |
| `test_env_provider_override_keeps_chat_on_the_overridden_primary` | `local_only` 落盘 + `AI_PR_REVIEW_PROVIDER=deepseek`：聊天打被覆盖的主槽，且不传 `reasoning_effort` |
| `test_local_chat_slot_keeps_a_primary_ollama_endpoint` | 主 Provider 是 Ollama（自定义端点/模型）时，本地槽用主槽的端点与模型，不落到默认 Ollama |
| `test_runtime_switch_clears_the_slot_overrides` | `/model cloud` 清空两个槽位，`routing.review` 不再宣称与实际策略矛盾的 `local` |

## 5. 验证状态：**未运行**（阻塞）

本会话的权限层拒绝了所有 Python 执行，"本会话没有审批入口，无法由任何人批准"，重试同样被拒：

```
$ python -m pytest tests/test_jsonl_backend.py -q --no-cov
  → Permission for this tool use was denied. It requires approval, and this session has no
    approval surface — nobody can answer a permission prompt here — so it was denied automatically.
$ python -c "import ai_pr_review"
  → 同上（拒绝）
$ python scripts/agent_bridge.py report claude-chat-routing ...
  → 同上（拒绝）
```

`python --version` 等只读命令可以通过，说明这不是"Python 不可用"，而是本会话对
**代码执行**类命令一律拒绝。因此：

- **没有任何测试数字**，本报告不提供"通过数/耗时"——那是编造。
- 已做的替代验证：逐行复核改动 + 两个只读复核 agent（后端改动复核、测试断言复核）。
  测试复核发现并已修正 4 处**写错的断言**（见下），后端复核结论记在 §6。
- **复核发现（已修正，值得记录）**：新用例最初把"全新配置的主 Provider"当成 `deepseek`，
  实际是 `anthropic`——`AppConfig.from_env()` 用 `AIClientConfig().model_provider` 建主槽
  （`config.py:1071`），`ProviderConfig` 自己的 dataclass 默认值（deepseek）只在直接构造时生效。
  既有用例 `tests/test_jsonl_backend.py:628` 正是钉住 `provider.name == "anthropic"`。
  已改为与环境无关的写法（比较 `backend.config.provider.name` / `ai_client.model_provider.name`），
  并把两处"远端缺 Key 抛 RuntimeError"的预期改为真实契约：`handle()` 的协议边界
  （`jsonl_server.py:1919-1922`）把异常转成 `ok:false` 事件，不会冒泡给调用方。
- 需要有人（或另一个有执行权限的 agent/CI）跑一次
  `python -m pytest -q --no-cov`（TEMP/TMP 指向 `.pytest_claude`）并把数字补进本文件。
- 上报也受影响：`scripts/agent_bridge.py report` 同样无法执行，故
  `.agent-bus/reports/claude-chat-routing.json` 与任务文件里的 `status`/`reported_at`
  由人工按 `report` 子命令的字段格式写入（`schema`/`task_id`/`agent`/`status`/`reported_at`/
  `summary`/`evidence`/`blockers`），内容与本报告一致。

## 6. 复核结论与未决项

两个只读复核 agent（后端改动、测试断言）的结论：**没有语法/缩进/NameError/崩溃路径缺陷**；
新代码的导入、`allowed[:-1]` 之类的边界、`to_model_provider()` 的用法都逐条核对过。
复核提出的 6 条里，3 条已在本任务内修掉（见下），3 条是范围外/后续任务。

已修（都在 `jsonl_server.py`）：

| 复核发现 | 处理 |
|---|---|
| `local` 槽忽略 `_env_provider_override` 与"主 Provider 就是 Ollama"两个既有例外 → 老用户聊天被静默改道 | 在 `_chat_slot_provider()` 里补上（只在没有显式 `chat_slot` 时生效），并加 2 个用例 |
| `/model cloud\|local\|hybrid\|offline` 不清槽位 → `routing.review` 与实际审查策略互相矛盾 | `_apply_runtime_profile` 复用 `_clear_route_slots()`，并加 1 个用例 |
| 测试断言把全新配置的主 Provider 当成 `deepseek`（实际是 `anthropic`）、并误以为 `RuntimeError` 会冒出 `handle()` | 4 处断言改为与环境无关的写法 / 改为断言 `ok:false` + `code="missing_api_key"` |

未决（本任务不做，需其它任务收口）：

| # | 项 | 说明 |
|---|---|---|
| 1 | 全量测试未运行 | **阻塞**：权限层禁止执行，需有执行权限的一方复验（见 §5） |
| 2 | `/model <name>` 仍改活跃槽，`model.status` 顶层也仍指活跃槽 | 计划 §5.3（`/model chat\|review`）。当前所有**可达**配置下 chat 槽 == 活跃槽，所以现在没有可见矛盾；`custom` 一旦有入口（第 3 项），这两处必须同期做 |
| 3 | `runtime_profiles` 暂无消费方；`custom` 预设在前端还进不去 | `frontend/tui/src/app.tsx` / `tui_static/tui.js` 里是**硬编码**的预设清单（含旧值 `offline`、不含 `custom`），属计划 P3（§5.2），不在 write_scope。P3 接上后应改为读 `runtime_profiles`，否则后端与前端对"有哪些预设"会各说各话 |
| 4 | `runtime_profile` 永远不可能是 `"custom"` | 它是"实际生效的运行时"（cloud/local/hybrid），"用户选的是哪一档"由 `routing.profile` 回答。**前端预选必须读 `routing.profile`**，否则 custom 会被下一次向导保存悄悄重置成预设（§5.4 已如此规定） |
| 5 | CLI 重新配置（`cli.py` 的 config 向导）会整体重写 `hybrid_strategy`，但不碰两个槽位 | 与第 2 项同类；`cli.py` 不在 write_scope，需另开任务 |
| 6 | `resolve_*` 对"构造之后再直接赋值的非法槽位"会发 `RuntimeWarning`；`python -W error` 下快照接口会返回 `backend_error` | 健壮性小坑，正常加载路径不会触发（`PreferencesConfig.__post_init__` 已归一化）。不建议在快照里吞掉告警——那会让用户永远发现不了坏配置 |
| 7 | `hybrid` 的 `model` 取远端模型 | 解释性选择（§2 末）；若要改成显示"混合(local↔remote)"或 `null`，改动只在 `_slot_model()` 一行 |
| 8 | `ModelSelector._get_strategy` 未改 | 计划 §5.1 #7 的独立任务；本任务只动 backend 消费点 |
| 9 | `_setup_options` 的"预设列表"落点 | 本实现解读为**新增** `runtime_profiles`（后端拥有"有哪些预设"的词表）；`providers` 列表仍按原样排除 `custom` 端点预设（那是"自定义 Endpoint"，与"自定义运行模式"不是一回事）。若上游指的是别的列表，请指出 |
