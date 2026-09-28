# 独立复核报告：P3（后端健壮性 11 项）/ P4（流式与体验 8 项）

> 复核方式：全程只读（Read / Grep / `git diff` / `git show HEAD:...`），未修改任何源码或配置，未运行 Python/Bun/TUI，未读取或输出任何密钥与私人会话内容。
> 依据：`docs/DEV_PLAN_2026-09-24.md` P3/P4 执行状态表、`docs/claude-tui-audit.md`（原始基线）、未提交 git diff（22 个已跟踪文件 + 未跟踪的 `src/ai_pr_review/backend/`、`frontend/tui/`）。
> 所有结论标注 **【确证】**（静态代码可完全确定）或 **【推理】**（需要运行验证）。

## 结论摘要

| 级别 | 数量 | 主题 |
|---|---|---|
| P0 | 0 | 未发现启动即崩 / 密钥丢失 / 跨库串线级别的新缺陷 |
| P1 | 3 | 双槽位写入点未同步（`config model` 静默失效 + 污染远程槽位）；env 覆盖静默改写并持久化 `hybrid_strategy`；`config test` 校验的是非激活槽位 |
| P2 | 11 | 见下 |

**核心判断：F3 的「双槽位」只改了一半。** `_active_provider_config()` 建立后，只有 `jsonl_server`（`/model`、`model.apply`）与 `config_wizard` 被同步更新；CLI 的模型写入、诊断、展示、旧 Chat 上下文仍有 8 处直接读写 `config.provider`（远程槽位）。其中 `_set_active_model` 会产生「命令报成功但配置实际未生效 + 远程槽位被本地模型名污染」。

---

## P1

### P1-1 `pr-review config model` 在 local_only 下静默失效并污染远程槽位

- **文件**：`src/ai_pr_review/cli.py:1731-1749`（`_set_active_model`）、`src/ai_pr_review/config_commands.py:56-58`（`run_config_model` 调用后立刻 `save()`）、`src/ai_pr_review/config.py:995`（`save()` 内 `_sync_runtime_sections()`）
- **复现路径（新机器，纯本地配置）**【确证】：
  1. `pr-review config` → 运行模式选 **local** → `apply_wizard_configuration` 写入 `local_provider`（因为 `config.provider.name == "anthropic"` 不在 `{ollama, local}`，`config_wizard.py:54-64`），策略 `local_only`。
  2. `pr-review config model --name qwen3.5:4b`
- **失败一（误报错误）**：`cli.py:1731` 取 `config.provider.name` = `"anthropic"`（**远程槽位**，用户从未选择过），`_model_provider_hint("qwen3.5:4b")` 命中 `PROVIDER_MODEL_PRESETS["ollama"]`（`config.py:334-335`）返回 `"ollama"` → 抛出 `ClickException("模型 qwen3.5:4b 是本地 Ollama 模型，但当前 Provider 是 Anthropic…请先运行 pr-review config，选择 Ollama")`。用户**已经**选了 Ollama，却被告知去配置 Ollama。
- **失败二（静默 no-op + 假成功）**：换成不受 hint 约束的本地模型名（如 `--name my-local:latest`）走通后，`cli.py:1746-1749` 把模型写进 `config.provider`（远程槽位）与 `config.ai_client.model`，随后 `run_config_model` 立即 `save()` → `save()` 第 995 行调用 `_sync_runtime_sections()` → `active = _active_provider_config()` = `local_provider`（`config.py:811-814`）→ `ai_client.model` **被重建成本地槽位的模型**，用户看到 `Active model set to: my-local:latest` 但生效模型未变。
- **附带损坏**：`config.provider.default_model` 与 `config.provider.models[...]` 已被改成**本地**模型名（`cli.py:1747-1748`）并落盘。用户日后 `/model cloud` 或 `--mode remote` 时会拿着一个本地模型名去请求云端端点。
- **对照证据（说明这是遗漏而非设计）**：同一语义的 TUI 路径 `jsonl_server._apply_model`（`jsonl_server.py:118-120`）用的是 `self.config._active_provider_config()`，是正确的。
- **建议修复**：`_set_active_model` 改为 `slot = config._active_provider_config()`，hint 校验与写入都基于 `slot`；`_model_provider_hint` 的期望 provider 与 `slot.name` 比较。

### P1-2 `AI_PR_REVIEW_PROVIDER` 会静默改写并持久化 `hybrid_strategy`

- **文件**：`src/ai_pr_review/config.py:859-867`（覆盖生效时把 `local_only` 改成 `remote_only`）、持久化点 `jsonl_server.py:92`（`_apply_runtime_profile` 的 `save`）、`jsonl_server.py:122`（`_apply_model`）、`config_commands.py:57`（`run_config_model`）
- **机制**【确证】：`_apply_env_overrides` 在每次 `load()` 末尾无条件执行（`config.py:978`）。当 `AI_PR_REVIEW_PROVIDER` 合法且与持久化的 provider 名不同时，除了重建 provider，还把内存中的 `preferences.hybrid_strategy` 由 `local_only` 改为 `remote_only`。该改动**没有任何警告**，且只要进程内发生任意一次 `save()`（`/model`、`/model <name>`、`pr-review config model`）就被写进用户配置文件，用户的「本地优先」偏好被永久覆盖。
- **额外的语义不一致**【确证】：第 842 行的守卫是 `provider_override.lower() != self.provider.name.lower()`。若 env 值**恰好等于**持久化的 provider 名（例如用户 `export AI_PR_REVIEW_PROVIDER=deepseek`，配置里 provider 也是 `deepseek`，但策略是 `local_only`），整个分支被跳过 → 策略不被改写 → 实际服务的仍是本地槽位。于是「env 覆盖必须胜过 local_only」只在「名字不同」时成立，与第 859-861 行注释的宣称相反。
- **影响**：只在用户 shell 里常驻 `AI_PR_REVIEW_PROVIDER` 时触发；一旦触发即为静默持久化改写。与 F3 同类（未征得同意的配置变更），但可恢复，故列 P1 下限。
- **建议修复**：不要改 `preferences.hybrid_strategy`；改为在 `_active_provider_config()` 里优先判断「本次 load 是否有显式 provider 覆盖」，或在覆盖生效时发 `RuntimeWarning` 并把该决定只保留在运行时（`JsonlBackend.runtime_profile`），不落 `preferences`。

### P1-3 `config test` / `config health` 校验的是非激活槽位

- **文件**：`src/ai_pr_review/config_diagnostics.py:20-26`（`validate_provider_for_test` → `config.provider.to_model_provider()`）、`src/ai_pr_review/config_commands.py:23`（`run_config_test` 同上）；对比 `provider_diagnostics.py:55-72`（`discover_remote_models` / `probe_provider_connection`）与 `:25`（`build_provider_health_payload`）用的是 `config.ai_client.model_provider`（**激活槽位**）
- **后果**【确证】：local_only 用户执行 `pr-review config test`（或 `config health`，两者都先过 `validate_provider_for_test`）会对**从未配置过的远程槽位**做校验，报 `Missing API key for provider: anthropic`（`_missing_api_key_message`，`cli.py:1678-1683`）。同一条命令内部的两个 provider 来源互相矛盾（校验用远程、探测用本地）。
- **诚实标注**【推理】：P3 之前向导会把 `config.provider` 整体覆盖为 Ollama，因此「无 Key 的本地 provider 过不了 key 检查」在修复前也存在；本次变化是**报错对象从 ollama 变成用户没选过的 anthropic**，属诊断正确性退化而非全新失败路径。我未实际运行该命令验证输出。
- **建议修复**：`validate_provider_for_test` 改用 `config.ai_client.model_provider`，或复用一个统一的 `active_model_provider()` 访问器，彻底消除「同一个概念两种取法」。

---

## P2

### P2-1 `/review` 无后端 busy 守卫，`review_cancellations` 存在身份竞态

- **文件**：`jsonl_server.py:743-761`（启动审查，无并发检查；对比 chat 在 `:557-558` 有 `busy` 守卫）、`:811-814`（`finally` 无条件 `pop`）
- **序列**【确证】：同一 `session_id` 上第二个 `/review` 会覆盖 `self.review_cancellations[session_id]`；先结束的那个在 `finally` 里 pop 掉的是**第二个**的 `asyncio.Event`，第二个审查从此不可取消（`cancel` 命令查不到条目，返回「当前没有正在运行的任务」）。
- **为什么不算 P1**：P1-2 已在前端加 `reviewStarting` 同步锁，但 `docs/DEV_PLAN_2026-09-24.md:33` 自己写明「真实审查双击 Ctrl+R 的验证放到 P5」，即该路径**尚未被实测**。后端是语义权威，不应依赖客户端锁。
- **建议修复**：`claim` 式守卫——`if review_session_id in self.review_cancellations: error("审查已在进行", "busy")`；`finally` 中改为 `if self.review_cancellations.get(sid) is cancel_event: pop(sid)`。

### P2-2 F17 的回归测试没有覆盖「子类化」这个修复点本身

- **文件**：`tests/test_jsonl_backend.py:267-300`
- **问题**【确证】：该测试 monkeypatch `ai_pr_review.cli.run_review` 为 `fake_run_review`，它**从不抛出编排器的 `ReviewCancelled`**；测试直接调用 `backend._run_review(...)` 并断言 `pytest.raises(ReviewCancelled)`（jsonl 自己的类）。由于 `_run_review` 的 `check_cancelled()` 抛的就是这个类，断言在任何基类关系下都成立。而修复说明（`DEV_PLAN:83`）称「`ReviewCancelled` 改为编排器异常的子类（此前会误报 `review.failed`）」——**这条路径没有任何测试**：全仓 `tests/` 中 `review.cancelled` / `review.failed` 零命中（仅 `test_credentials_and_jobs.py:413` 用基类构造了一个假异常）。
- **建议修复**：加一个走 `handle()` 的测试，让 fake `run_review` 抛 `review_orchestrator.ReviewCancelled`（基类，非子类），断言发布的是 `review.cancelled` 而非 `review.failed`。

### P2-3 `emit` 超时测试名不符实，且会白等 10 秒

- **文件**：`tests/test_model_providers.py`（`test_stream_emit_stops_quietly_once_the_event_loop_is_gone`）、被测代码 `openai.py:58-70`
- **推理依据**【确证】：测试在**事件循环线程内**（协程里）调用 `emit`。`asyncio.run_coroutine_threadsafe(...)` 对「正在运行但被阻塞」的 loop 会成功入队，随后 `future.result(timeout=10)` 在 loop 线程上**阻塞循环**，那个 `on_delta` 协程永远没机会执行 → 必然走满 `EMIT_TIMEOUT_SECONDS = 10.0` 才抛 `TimeoutError`（Python ≥3.12 下 `concurrent.futures.TimeoutError` 就是内建 `TimeoutError`，故被吞掉），断言 `callable(emit)` 平凡成立。
- **后果**：① 名为「事件循环已关闭」的用例实际上从未走到 `except RuntimeError` 分支（该分支才是 `:62-64` 想守的东西）；② 每个测试进程白付 10 秒墙钟。
- **建议修复**：用例改为在 loop 关闭后（测试函数返回后，例如通过 `asyncio.run` 外层）调用 `emit`，或直接把 `EMIT_TIMEOUT_SECONDS` 打桩为 0.05。

### P2-4 取消时「辅助线程 close」存在首字节窗口；`active_response` 仍无锁

- **文件**：`openai.py:71-86`（`except asyncio.CancelledError` 分支）、`:120-122`
- **窗口**【确证】：`active_response.append(response)` 发生在 `request.urlopen(...)` **返回之后**（即收到响应头之后）。LLM 常见「思考 5–30 秒才出首字节」，若用户在这段时间取消，`active_response` 为空 → 不发起 close → 读线程只能在收到首字节（或 `timeout_seconds`=120s 到期）后才由 `for line` 里的 `cancel_event` 检查退出。代码注释「Closing unblocks the reader's socket read」在该窗口内不成立。
- **另**：`active_response` 是事件循环线程与工作线程共享的裸 `list`，审计 F11 建议的「用锁保护」未落地（CPython 下 append/clear/索引不致崩溃，但这是靠 GIL 的巧合）。
- **另**：从另一线程 close 一个正被 `readline` 阻塞的 socket 在 Linux/Windows 上都是 best-effort（可能不唤醒）；因为异常分支要求 `cancel_event.is_set()` 才吞异常，所以「不唤醒」表现为线程残留而非错误。
- **影响**：不写脏会话（V7 仍成立），代价是取消后线程/连接滞留至首字节。建议把 `cancel_event` 的轮询下沉到等待首字节的阶段，或在工作线程侧检查 `cancel_event` 后自行 `close`。

### P2-5 Anthropic 原生流式丢掉了非流式路径的空响应兜底

- **文件**：`anthropic.py:56-98`（新 `stream_chat`）对比 `anthropic.py:27-54`（`chat()`）
- **差异**【确证】：`chat()` 在无 `content` 文本时会回退到 `block.thinking` / `response.output_text`（`:38-47`）；`stream_chat` 只消费 `stream.text_stream`，没有等价兜底，也没有 `if not text: raise` 之类的失败语义（OpenAI 侧 `openai.py:175-176` 有）。同时 `chat()` 返回 `"\n".join(parts).strip()`，`stream_chat` 返回 `"".join(parts)`。
- **后果**：当模型只产出 thinking 块（用户在 advanced 里配了 `extra_params.thinking`）或流未产出文本增量时，`ProviderResponse.text == ""`，`jsonl_server._chat:303-304` 会把这个空串写进 `session.messages`，前端 `assistant.finished` 携带空文本 → **用户看到空回答而非报错**。P4 之前 Anthropic 走 `base.stream_chat` → `chat()`，同一场景会拿到 thinking 文本，属行为回归。
- **建议修复**：流式结束后若 `parts` 为空，回落到 `get_final_message()` 的文本提取（或抛 `AIResponseFormatError`）。

### P2-6 `_result_store_payload` 会丢弃「显式钉死为平台默认」的 `db_path`

- **文件**：`config.py:1057-1069`（`_result_store_payload`）、`config.py:1042-1055`（`_derived_result_store_default`）
- **序列**【确证】：配置文件不在默认位置（如 `--config D:\ws\config.json`）且**显式**写了 `result_store.db_path` 等于平台默认值（`%LOCALAPPDATA%\ai-pr-review\results.db`，`config.py:71-79`）时：任一次 `save()` 会把 `db_path` 从 payload 中删掉（判据 `current == platform_default`）；下次 `load()` 因 `explicit_db=False` 改走派生分支，把库改到 `<配置目录>/results.db`（`:970-976`）——**用户的历史静默搬家**。判据「等于平台默认就可删」只在配置文件本身位于默认位置时成立。
- **可达性**【推理】：向导不写 `db_path`，需要手工编辑或用 `config import` 导入一个显式钉住默认路径的配置；`ResultStoreConfig.db_path` 默认值就是平台默认（`config.py:730`），因此旧版本 `save()` 会把它整体落盘（旧代码 `"result_store": asdict(self.result_store)`），升级用户天然带这个字段。低概率但语义确实反了。
- **建议修复**：只在 `_derived_result_store_default() is None`（即配置文件位于默认位置）时才允许 pop `db_path`。

### P2-7 F16 的两处尾差：派生路径不可写时硬失败 + 提示文案与真实来源不符

- **文件**：`result_store.py:47-80`
- **硬失败**【确证】：fallback 白名单只有「平台默认」与 legacy 字面量（`:67-71`），其余一律 `raise`。P3 新增的派生路径（`<配置目录>/results.db`）不属白名单，因此当 `--config` 指向只读目录/网络盘时，`/history`、`HybridReviewOrchestrator.__init__`（`hybrid_orchestrator.py:35`）会直接抛 `OSError`，而不再降级。比「静默改道」更响亮，但对用户是一条未分类的裸错误，且与「历史库可自动降级」的既有行为不一致。
- **文案**：平台默认触发的 warning 也是 `Configured result store is not writable: ...`（`:74-79`），而 `/history` 的提示是 `注意：配置的历史库不可写，实际使用 {path}`（`jsonl_server.py:411-416`）。当路径来自平台默认或派生（用户从未「配置」过）时，读者会被引导去找一个不存在的配置项。
- **是否刷屏**【确证】：正常（可写）环境不触发；触发时同一进程内默认 warning filter 按 (text, category, lineno) 去重，只打一行；仓库内无 `simplefilter` / `PYTHONWARNINGS` / `filterwarnings=error`（见下「确认无问题」）。**不是刷屏问题。**
- **附带**：CWD 兜底目录 `.ai_pr_review/` 未被 `.gitignore` 覆盖（只忽略了 `config.json` / `config.local.json`，`.gitignore:2-3`），TUI 后端 CWD 被固定为仓库根（`backend.ts:21`），降级产生的 `results.db` 会出现在 `git status` 里。

### P2-8 F13 的告警在 TUI 里不可见（未闭环）

- **文件**：`config.py:850-855`（warning）、`frontend/tui/src/backend.ts:103-118`（stderr 环形缓冲）、`:150-155`（仅在进程关闭时并入错误消息）
- **结论**【确证】：TUI 后端把 stderr 收进 `backendErrors`，**只在后端连接关闭时**（或重启）随 `Python backend connection closed` 一起显示，运行期完全不可见。因此 `AI_PR_REVIEW_PROVIDER=<typo>` 的用户会看到一个完全正常、跑在旧 provider 上的 TUI，没有任何「你的环境变量被忽略了」的反馈。执行状态表里的证据（`exit 0 且 provider=deepseek`）只覆盖了 CLI 直跑路径。
- **建议修复**：在 `health` / `config.snapshot` 回包里带上 `ignored_env_overrides: [...]`，由前端页脚或 `/status` 呈现；或发一条一次性 `config.warning` 事件。

### P2-9 双槽位读取点未同步（展示层与旧 Chat 上下文）

全部为 `config.provider`（远程槽位），在 `local_only` 下都会错误显示/归档：

| 位置 | 现象 |
|---|---|
| `cli.py:2513` → `_render_config_summary`（`:1184-1199`） | 向导选 local 后，配置摘要打印 `供应商 Anthropic / 默认模型 claude-sonnet-4 / 运行策略 local_only` —— 用户刚选的 Ollama 不出现在确认页上 |
| `cli.py:1382-1383` | 审查进度面板 `provider_label` 取远程槽位、`model_label` 取 `ai_client.model`（激活槽位）→ 显示 `Anthropic · qwen3.5:4b` |
| `cli.py:3439-3464` | `local_model` / `remote_model` 用 `config.provider.name` 分桶，local_only 下把**本地模型**记进 `remote_model`（`local_model=None`） |
| `cli.py:1693-1696` `_chat_title`、`chat_runtime.py:50`、`chat_commands.py:229`（旧 Chat `/status`） | 旧 Chat 标题/状态栏/`/status` 显示远程 provider + 本地模型 |
| `cli.py:1285`（`config show`）、`:2268`、`:1768-1773` | 配置展示/JSON 输出的 provider 字段取远程槽位 |

- **建议修复**：新增 `AppConfig.active_provider` 只读属性（内部调用 `_active_provider_config()`），把上述读取点与 `jsonl_server._config_snapshot` 统一到它上面。

### P2-10 `local_only` 在本地 provider 构造失败时静默回退云端

- **文件**：`model_selector.py:74-95`（`except Exception: pass`，且 `self.local_model` 预置为硬编码 `"qwen3.5:4b"`）、`:145-151`（`LOCAL_ONLY` 且 `local_provider is None` → 返回 **remote**）
- **后果**【确证】：① 本地 provider 构造异常（自定义 `api_format`、非法 base_url 等）时，策略 `local_only` 会把请求发给云端——与 `DEV_PLAN:96` 声明的「明确拒绝并提示，而不是静默切到一个不可用的 Provider」相反；② 因 `local_model` 被预置为 `"qwen3.5:4b"`，`hybrid_orchestrator.py:245` 上报的 `routing_model` 会记录一个从未使用的模型（原代码此处为 `None`，更诚实）。
- **建议修复**：`except` 分支记下原因并在 `local_only` 时抛错或发 warning；`local_model` 失败时保持 `None`。

### P2-11 `native_streaming` 是死代码，却被当作 P4 证据

- **文件**：`base.py:34`、`openai.py:46`、`anthropic.py:16` 三处赋值；全仓（含 `frontend/`、`docs/`）**零读取**（`DEV_PLAN:109` 把 `AnthropicProvider.native_streaming = True` 列为验收证据）
- **影响**：无运行时影响，但会让后续维护者以为该标志控制着回退路径。建议删除，或真的用它来挑选 `stream_chat` 实现。

### 其他小项（P2 边缘 / nit）

1. `cli.py:2791-2799`：`pr-review review --mode balanced|remote|quality` 直接改 `hybrid_strategy` 而**不做 key 检查**，与 `jsonl_server._apply_runtime_profile` 的「无远程 Key 拒绝切换」（`:80-86`）不一致。P3 之前远程槽位会被本地预设覆盖、请求落到本机；现在会落到未配置的云端点并 401。默认 `--mode auto` 不受影响。
2. `config.py:135-141`：`active_config_paths` 保留项目叠加的条件是 `user_config_path.parent in project_root.parents`，而 `Path.parents` 不含自身，故位于**仓库根**的 `--config X/config.json` 会丢掉 `.ai_pr_review/*` 项目叠加（放在子目录才保留）。
3. 旧版本 `/model local` 遗留的污染不会自愈（迁移缺口）【确证】：旧 `_sync_runtime_sections`（`git show HEAD:src/ai_pr_review/config.py:797-800`）执行 `api_key = provider.api_key or self.ai_client.api_key`，会把云 Key 复制进被替换成 Ollama 的 `config.provider`，旧 `save()` 再把它落盘。升级后该 Key 位于**主槽位**且 `same_provider` 为真，因此被当作「该槽位自己的 Key」保留并继续以 `Authorization: Bearer <云Key>` 发往 `127.0.0.1:11434`，模型状态页也会显示「API Key：已配置」。新代码只阻止了**新的**污染，没有清理存量。建议在 load 时对 `provider.name in {ollama, local}` 且 key 来源为本机云端 provider 的槽位做一次告警（或提供 `pr-review config key rotate` 提示）。

---

## 本次复核确认无问题的点

以下均已逐行核对代码（必要时对照已安装的第三方 SDK 源码），未发现缺陷：

1. **Anthropic 取消不留连接泄漏**【确证】。`anthropic.py:71-83` 的 `async with` 在 `break` 后必经 `__aexit__`；对照已安装 SDK（`anthropic/lib/streaming/_messages.py:228-245`）：`AsyncMessageStream.__aexit__` → `close()` → `await self._raw_stream.close()`，即关闭底层 httpx 响应。跳过 `get_final_message()` 的同时连接被释放，`text_stream` 也没有后台读任务残留。
2. **吞异常的边界正确**【确证】。`openai.py:166` 的 `except (ValueError, OSError)` 不会误吞 `AIResponseFormatError`——`exceptions.py:57-83` 显示 `AIClientError(Exception)`，与 `ValueError` 无继承关系；`HTTPError/URLError` 在更靠前的分支（`:156/:164`）已捕获，不会被 `OSError` 分支抢先。
3. **`future.result(timeout=10)` + `except TimeoutError` 的写法与 Python 版本匹配**【确证】。`pyproject.toml:10` 为 `requires-python = ">=3.12"`，3.11 起 `concurrent.futures.TimeoutError` 即内建 `TimeoutError` 的别名，故超时能被 `openai.py:70` 捕获；`future.cancel()` 对「已开始执行」的 task 返回 False（不中断已在投递的 delta），但 `jsonl_server` 的 `on_delta` 会在入口复查 `chat_stop_event`（`jsonl_server.py:576-577`），迟到 delta 被二次拦截。
4. **F17 尾窗确实已闭合**【确证】。两个编排器都在 `save_result` **之前**复查：`hybrid_orchestrator.py:226-230`、`review_orchestrator.py:235-237`；`save_result` 是全流程唯一的行写入点（grep 全仓 `save_result|record_feedback` 仅此两处）；`jsonl_server._run_review:391` 在 `build_report_payload` 与 `self.current_report = payload`（`:392-397`）之前再查一次，且 `build_report_payload` 内无任何文件写入。因此取消后既不落库也不留下报告。
5. **`cancel_check` 的透传链完整**【确证】。`cli.run_review(..., cancel_check=)`（`cli.py:1364`）→ `orchestrator.review(..., cancel_check=)`（`:1481`，两个编排器的 `review()` 都是关键字参数，签名匹配 `hybrid_orchestrator.py:37-46`）→ `stage()` 内在每次 `stage_callback` 前检查（`hybrid_orchestrator.py:56-58`），回调抛出的 `ReviewCancelled` 不被任何中间层 `except` 吞掉（`ReviewOrchestrator.review` 只有 `finally`）。
6. **子类化方向安全，未引入多捕/漏捕**【确证】。`jsonl_server.ReviewCancelled` ⊂ `review_orchestrator.ReviewCancelled` ⊂ `Exception`；`except ReviewCancelled`（`:778`）排在 `except Exception`（`:788`）**之前**，故 `run_review` 内部的取消会走 `review.cancelled` 分支，不会先被通用分支截走。全仓 `except ReviewCancelled` 仅两处（`jsonl_server.py:778`、`web_jobs.py:169`），后者捕获的是基类、运行在 Web 作业线程，与 TUI 子类无交叉；`cli.py` 只 import 不使用。`asyncio.wait_for` 的 `TimeoutError` 分支（`:762`）与 `ReviewCancelled` 无继承关系，不存在顺序冲突。
7. **`finally` 中的 pop 在异常路径一致**【确证】。`:757-814` 的 `try/except/else/finally` 中，四个分支（timeout / cancelled / failed / 正常）都会经过 `finally`；`review_session_id is not None` 守卫与注册条件（`:754-756`）对称；`event_counts` 一并清理，避免跨次审查累计。唯一缺陷是缺少身份校验（见 P2-1），而非路径不一致。
8. **槽位选择与命名归一化自洽**【确证】。`ollama|local` 两个别名在 `config.py:812`、`jsonl_server.py:60/78/99`、`model_selector.py:82/101`、`config_wizard.py:59` 六处保持一致的判定；`_infer_runtime_profile`（重启后由 `provider.name` + `hybrid_strategy` 反推）与 `/model local|cloud` 的写入相互可往返，配置文件里不存在 `local` 这个预设名（`MODEL_PROVIDER_PRESETS` 无 `local` 键），因此「provider 名恰好是 local」只能来自手写配置，且各处都按同一别名处理。
9. **向导选 local 一定落到激活槽位**【确证】。`cli.py:2476-2481` 与 `2504-2509` 在两处（`apply_wizard_configuration` 前后）都设置 `hybrid_strategy`，`save()` 时 `_active_provider_config()` 返回的正是刚写入 `local_provider` 的对象（`config_wizard.py:54-64`），不存在「写了但永不激活」的组合。
10. **Key 不会跨槽位串线（当前代码路径）**【确证】。`save()` 的 `payload_api_key = self.ai_client.api_key or active.api_key`（`config.py:1010`）与 `active.api_key = api_key`（`:987`）保证「槽位 ↔ ai_client 镜像」；`_sync_runtime_sections` 的 `same_provider` 守卫（`:821-822`）阻断旧 provider 的 Key 被复制到新 provider；`_apply_env_overrides:858` 在重建 provider 时先清空 `ai_client.api_key`。测试 `test_runtime_switch_does_not_carry_cloud_key_to_local` / `test_loading_local_provider_discards_stale_remote_client_key` 固定了这两条。**唯一例外是 P2-11-3 描述的存量污染。**
11. **F13 不会在同进程内刷屏，也不会让测试变红**【确证】。全仓无 `warnings.simplefilter` / `filterwarnings` / `PYTHONWARNINGS`（`pyproject.toml` 的 `[tool.pytest.ini_options]` 只有 testpaths/asyncio_mode/addopts），默认 filter 对同一 (message, category, 位置) 只打一次；`stacklevel=2` 指向 `load()` 内固定行，故断言 per-process 一行。非法值走 `except ConfigValidationError`（`config.py:846-855`）后 `provider_name` 回退为 `self.provider.name`（`:868`），随后 `:880-884` 只是把同名回写，不存在「回退成空名」或「回退到未定义 provider」的漏洞。
12. **`ConfigValidationError(ValueError)` 不会污染流式异常分类**【确证】。该异常只在 `config.py` 内的 provider 构造/校验路径抛出，`openai.py:166` 的 `except (ValueError, OSError)` 只在读流期间生效（此时 config 早已构造完成）。
13. **OpenAI 流式的请求体构造正确**【确证】。`"stream": True` 位于 `**self.config.extra_params` **之后**（`openai.py:96-102`），用户 extra_params 无法把它关掉；`[DONE]`、usage 帧、`choices[0].delta.content` 的 list 形态都做了处理；`think` 的透传位置与 `_chat_sync`（`:239-241`）一致；`OllamaProvider.stream_chat` 的 `think=False` 默认值与 `OllamaProvider.chat`（`ollama.py:24`）保持一致，不会造成 Ollama 侧行为分叉。
14. **F16 的告警在正常环境下不触发**【确证】。`warnings.warn` 只在 `except OSError` 分支内（`result_store.py:62-79`），平台默认可写时直接返回，日常运行零输出。
15. **P4 的 `assistant.started.streaming` 字段虽已过时但无功能影响**【确证】。`jsonl_server.py:569` 对 anthropic 仍上报 `streaming: false`（P4 之后不再准确），但 `frontend/tui/src` 中该字段零读取（`streamingAssistant` 是同名不同义的本地 signal），故不会抑制 Anthropic 的 delta 渲染。

## 复核范围与不确定项

1. 未运行任何命令/测试/TUI；以上「确证」均为静态代码与已安装 SDK 源码级别的确定，不包含运行时观测。
2. 未复核 P4 中纯前端的 4 项（`format.ts` 的 `truncateMiddle`/`compactPath`、`keymap.ts`、`commandEnterAction`、`Ctrl+C` 在弹窗下的处理）与 `tui_static` 重建产物的一致性——MiMo 的 PTY 实测覆盖该面，本次不在范围内。
3. P1-3 与 P2-11 的「修复前是否也失败」依赖 `git show HEAD:` 的历史代码推断，未构造运行时对照。
4. 未做密钥审计，未读取任何用户配置或会话内容。
