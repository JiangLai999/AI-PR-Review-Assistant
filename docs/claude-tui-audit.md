# Claude 后端审计报告

> 审计方式：全程只读（Read / Grep / `git diff --stat` / 目录列举），未修改、未创建、未删除任何文件，未运行 TUI、未运行任何写操作，未读取或输出任何密钥。下文所有结论均为**静态代码确证**；凡属推理而非确证者，均在"不确定项"中标注。

## 结论摘要

| # | 主题 | 结论 |
|---|---|---|
| 1 | `/history` 隔离 | **未生效**。`AppConfig.load(path)` 的绑定逻辑本身正确，但生产链路（TUI→后端）从不把配置路径作为 `Path` 传进去，只传环境变量，导致 `if path is not None` 分支永不执行。`/report`、`/export` 走内存态，不涉库。 |
| 2 | provider / 运行时切换 | 环境变量覆盖会正确整体重建 endpoint+模型（旧 bug 已修）；但 **`/model local` 会把远程 provider 配置与已落盘密钥从配置文件里抹掉**，且 `/model cloud` 随后拒绝切换 → 不可逆。`ModelSelector` 硬编码 Ollama，`ai_client.local_provider` 是死配置。 |
| 3 | TUI 后端重启 | 代次/session 重建/单次重试三项设计正确且被测试固定；缺口在于无请求超时、pending 清理是"一刀切"、`review.*` 事件完全不做归属过滤、stderr 从不读取。 |
| 4 | 真实流式 Chat | 单请求不会重复 `finished`；取消后 delta 被双重拦截、`session.messages` 不会被写脏。风险集中在：取消是协作式的（只在 stage/file 回调处检查）、跨线程 close 竞态、`emit().result()` 无超时。 |
| 5 | agent_bridge 总线 | 认领锁是原子 `O_EXCL`（正确）；但**锁永不过期**（崩溃即永久死锁）、`report` 无状态机校验、所有状态写入都是 `O_TRUNC` 非原子、读取端不处理损坏 JSON。 |

---

## 发现

### P0

#### F1. 显式 `config_path` 的 SQLite 隔离在生产链路完全失效（`/history` 读全局库）

- **问题**：`AppConfig.load(path)` 的隔离分支只在**传入 `Path` 实参**时生效；TUI 实际调用链只把配置路径塞进环境变量，`path` 恒为 `None`，分支被跳过，`result_store.db_path` 保持机器级默认值。
- **证据**：
  - `src/ai_pr_review/config.py:921-942` `AppConfig.load`，关键 `:935` `if path is not None:` / `:939` `config.result_store.db_path = str(Path(path).expanduser().parent / "results.db")`。
  - `src/ai_pr_review/backend/jsonl_server.py:34-41` `JsonlBackend.__init__`（`self.config = AppConfig.load(config_path)`）→ `:799-800` `serve()` → `:842-853` `main()`，**末行 `asyncio.run(serve())` 不传参**；该文件内无 `import os` / `os.environ` / `sys.argv` / `argparse`（grep 零命中，exit=1）。
  - `frontend/tui/src/backend.ts:20-27` `BackendClient.start`：`Bun.spawn([python, "-m", "ai_pr_review.backend.jsonl_server"], { cwd, stdin, stdout, stderr })` —— **无 CLI 参数**。
  - `src/ai_pr_review/cli.py:3328-3337` `_open_tui_frontend`：`if config_path is not None: env["AI_PR_REVIEW_CONFIG"] = str(config_path)` —— 唯一注入点，且只是环境变量。
  - 环境变量经 `resolve_config_path`（`config.py:82-92`）被读到 → **配置文件读对了，但 `db_path` 没跟着绑定**。`jsonl_server.py:486-489` `health` 回包却打印 `resolve_config_path(self.config_path)`，**视觉上像是已经隔离**。
  - `/history` 实际取库点：`jsonl_server.py:676` `store = ResultStore(self.config.result_store)`、`:384` `_history_text`、`:398` `_history_detail`；`self.config` 仅在 `__init__` 赋值一次，之后只被就地 `save()`，从不重新 `load()`。
  - 测试为何全绿：`tests/conftest.py:15,27-29` 把 `AI_PR_REVIEW_CONFIG` 列入 `_ISOLATED_ENV_VARS` 并全量 `delenv`；唯一断言隔离的用例 `tests/test_jsonl_backend.py:350-369` 传的是显式 `Path`。
- **影响**：不同 `--config` 工作区共用 `%LOCALAPPDATA%\ai-pr-review\results.db`（`config.py:71-79` `_default_result_store_path`）。跨工作区历史互相可见；`result_store.py:369-385` `_prune_old_results`（`max_results=1000`）会**互删**对方的审查记录。这也正是 `docs/AGENT_COLLABORATION_BRIEF.md:9` 记录的"已知缺陷"，本轮修复**未在生产路径生效**。
- **复现**（只读，不写任何文件）：
  ```powershell
  # A) 显式 Path（CLI 命令走的路）
  python -c "import pathlib;from ai_pr_review.config import AppConfig;print(AppConfig.load(pathlib.Path(r'C:\tmp\ws\config.json')).result_store.db_path)"
  # B) 只给环境变量（TUI 后端实际走的路）
  $env:AI_PR_REVIEW_CONFIG='C:\tmp\ws\config.json'; python -c "from ai_pr_review.config import AppConfig;print(AppConfig.load(None).result_store.db_path)"
  ```
  预期：A 打印 `<tmp>\ws\results.db`，B 打印 `...\AppData\Local\ai-pr-review\results.db`（两者不等即复现）。
- **最小修复**：在 `jsonl_server.main()`（`:842-853`）里把"仅环境变量存在时"的路径显式传下去，避免把默认路径也误判为显式路径：
  ```python
  resolved = os.environ.get(CONFIG_PATH_ENV_VAR, "").strip()
  asyncio.run(serve(Path(resolved).expanduser() if resolved else None))
  ```
  （等价方案：把 `config.py:935` 的判据从 `path is not None` 改为"解析出的有效配置路径来自显式/env 覆盖"。）

---

### P1

#### F2. `save()` 把 `db_path` 回写进配置文件，使显式路径隔离变成"一次性"

- **问题**：任何 `/model`、`/model local|cloud`、切模型都会 `save(save_key=True)`，而 `save()` 会把 `result_store` 整体落盘。此后该配置文件含 `db_path` → 再次 `AppConfig.load(path)` 时被判为"用户显式指定"（`:937` `explicit_db=True`）→ 派生分支永久失效。
- **证据**：`config.py:983` `"result_store": asdict(self.result_store)`；触发点 `jsonl_server.py:79`（`_apply_runtime_profile`）、`jsonl_server.py:105`（`_apply_model`）；判据 `config.py:936-939`。
- **影响**：① 生产（env 路径）下会把机器级绝对路径写死进用户配置；② 显式路径场景下派生值被写死，配置目录被整体拷贝/移动后历史指向旧位置；③ 若 `--config` 给的是**相对路径**（如 `cfg/config.json`），落盘的是相对路径 `cfg/results.db`，之后由 `sqlite3.connect`（`result_store.py:333`）按**当时 CWD** 解析——TUI 的 CWD 被固定为仓库根（`backend.ts:21`），CLI 则是 shell CWD，两处可能落到不同文件。
- **复现**：对任意临时配置执行一次 `config.apply`（见 F3 脚本）后 `cat config.json | findstr result_store`，可见 `db_path` 被写入。
- **最小修复**：`save()` 时若 `db_path` 等于"未显式配置时的派生/默认值"，则不写入 `result_store.db_path`（或额外持久化一个 `db_path_auto: true` 标记，加载时据此重新派生）。

#### F3. `/model local` 会摧毁远程 provider 配置与已保存密钥，且 `/model cloud` 拒绝回切

- **问题**：切到 local/offline 时，`self.config.provider` 被**整体替换**为 Ollama 预设（api_key 为空），随后 `save(save_key=True)` 把这个空 provider 写盘，并在 `payload_api_key` 为空时**主动 pop 掉 `api_key`**。远程 provider 的 name / base_url / models / api_key 全部从配置文件中消失。
- **证据**：`jsonl_server.py:64-80` `_apply_runtime_profile`（`:68-69` 替换 provider，`:79` `save(..., save_key=True)`）；`config.py:192-198` `MODEL_PROVIDER_PRESETS["ollama"]["env_var"] = ""` → `config.py:421` `api_key = os.getenv("", "")` = `""`；`config.py:986-988` `if not payload_api_key: payload["provider"].pop("api_key", None) ...`；回切被拒：`jsonl_server.py:73-74` `raise ValueError("请先配置远程 Provider，再选择 Cloud 或 Hybrid。")`。
- **影响**：一次误点 `/model local` 即不可逆地丢失云端 Key、自定义 Endpoint 与模型清单（除非 Key 也在环境变量里）。反向的"旧密钥残留"**已被正确防护**（见已验证项 V4），此处是相反方向的**静默数据丢失**。
- **复现**（只写系统临时目录，使用假 Key，不触碰真实配置）：
  ```powershell
  python -c "import asyncio,tempfile,pathlib,json;from ai_pr_review.backend.jsonl_server import JsonlBackend;d=pathlib.Path(tempfile.mkdtemp());c=d/'config.json';c.write_text(json.dumps({'provider':{'name':'deepseek','display_name':'DeepSeek','base_url':'https://api.deepseek.com/v1','api_format':'openai','models':{'deepseek-chat':{'name':'deepseek-chat'}},'default_model':'deepseek-chat','api_key':'sk-TEST-NOT-REAL'}}),encoding='utf-8');b=JsonlBackend(c);print('BEFORE',b.config.provider.name,b.config.provider.base_url);asyncio.run(b.handle({'id':'1','method':'config.apply','params':{'section':'runtime','value':'local'}}));print('AFTER',json.loads(c.read_text(encoding='utf-8'))['provider'])"
  ```
- **最小修复**：切到 local/offline 时不要用 Ollama 预设覆盖 `self.config.provider`，而是保留用户已配置的远程 provider 作为持久化字段，仅在运行时把 `ai_client` 指向本地（或新增 `providers: {"remote": {...}, "local": {...}}` 双槽位，`preferences.hybrid_strategy` 决定激活槽位）。

#### F4. `ModelSelector` 硬编码 Ollama、不做健康检查，`ai_client.local_provider` 是死配置

- **问题**：本地 provider 无条件由 `from_name("ollama")` 构造，端点写死 `http://127.0.0.1:11434/v1`；`local_model` 只被当作"标签"返回，实际请求用的是 provider 自带的 `config.model_name`。`local_provider` 字段全仓从未被读取。
- **证据**：`services/model_selector.py:78-85`（`local_config = ModelProviderConfig.from_name("ollama")`；`self.local_model = getattr(self.ai_config, "local_model", ...)`）；`:130-146`（只要策略不是 `remote_only` 且 `local_provider` 非 None 就可能路由到本地，而该对象**从未做过 health_check**）；`config.py:650-651` 定义 `local_model` / `local_provider`；grep 全 `src/` 显示 `local_provider` 仅有定义处一行命中；`services/model_providers/openai.py:72` `"model": self.config.model_name` 才是真正上线的模型；`services/hybrid_orchestrator.py:240` 却把 `self.model_selector.local_model` 作为 `routing_model` 上报。
- **影响**：① 默认 `hybrid_strategy="balanced"`（`config.py:562`）下，即使 Ollama 没启动，选择器仍会把 TRIVIAL/SIMPLE 任务派给本地 → 失败点从"路由前"推迟到"请求时"；② 用户若把本地模型指向 LM Studio/vLLM 等兼容端点，请求仍打到 Ollama 默认端口；③ 上报的 `routing_model` 与实际上线模型可能不一致。
- **复现**：`python -c "from ai_pr_review.services.model_selector import ModelSelector;from ai_pr_review.config import AppConfig;m=ModelSelector(AppConfig.load());print(m.local_provider.config.base_url, m.local_provider.config.model_name, m.local_model)"`（本地 endpoint/model 与 `ai_client.local_model` 不一致即复现）。
- **最小修复**：用 `ai_client.local_provider`/`local_model` 构造本地 provider，并在 `__init__`（或首次路由前）做一次带缓存/短超时的健康探测，失败时把 `local_provider` 置 `None` 走既有的远程降级分支（`:143-145`）。

#### F5. `agent_bridge.py`：锁永不过期 + `report` 无状态机校验 → 永久死锁与状态回退

- **问题**：`claim` 先原子建锁（`:78`），随后**非原子**重写任务文件（`:83`）。若在两步之间崩溃，锁在而状态仍 `pending` → 该任务永久不可认领。全脚本**无 release / unclaim / 锁超时 / 过期回收**。`report` 只校验归属，不校验是否已认领、不校验当前状态，可任意重复上报造成状态回退。
- **证据**：`scripts/agent_bridge.py:69-84` `claim`（`:78` `write_json(lock_path, lock, exclusive=True)`、`:79-80` `except FileExistsError → SystemExit`、`:81-83` 状态改写）；`:87-107` `report`（`:91-92` 只校验 `task["agent"] != agent`；`:103` 先写报告、`:106` 再写任务状态）；`:110-140` `main()` 仅注册 `init/dispatch/claim/report`，无释放/续租子命令；`:76` 已记录 `claimed_at` 但无任何过期判定。
- **影响**：① 崩溃/强杀后任务永久卡死且无补救命令（只能手工删锁文件）；② 报告已写但状态未更新的不一致窗口（`:103` 与 `:106` 之间）；③ `completed → blocked` 等非法回退；④ 任意进程可用 `--agent <同名>` 冒充归属（`:115` 对 `dispatch` 限定了 agent，`:121/:124` 对 `claim/report` **未限定**，仅靠字符串比对）。
- **复现**（只读推理，建议在临时副本上验证）：
  ```powershell
  python scripts/agent_bridge.py claim --agent claude claude-backend-audit   # 建锁
  python scripts/agent_bridge.py report --agent claude --status blocked --summary x claude-backend-audit
  python scripts/agent_bridge.py report --agent claude --status completed --summary y claude-backend-audit  # 状态回退，无任何拦截
  ```
  （注意：这会写 `.agent-bus/`，属破坏性操作，本次未执行。）
- **最小修复**：① `write_json` 改为同目录 `tempfile` + `os.replace` + `fsync`；② 新增 `release` 子命令与"`claimed_at` 超过 TTL 视为可回收"的分支；③ `report` 增加状态白名单（仅允许 `claimed → completed|blocked|needs-review`）；④ `task_id` 加 `^[A-Za-z0-9_-]+$` 校验（详见 F12）。

---

### P2

#### F6. `agent_bridge` 全部状态写入非原子，且读取端不处理损坏 JSON
- **证据**：`scripts/agent_bridge.py:38-43` `write_json`（`O_TRUNC` 直写、无 `fsync`、无 `os.replace`；全仓无 `os.replace`，`tempfile` 仅出现在 `scripts/verify_tui_stream.py:14,27`）；`:72`、`:90` 的 `json.loads(task_path.read_text(...))` **未捕获** `JSONDecodeError` / `FileNotFoundError` / `KeyError`；`dispatch` 的 `FileExistsError`（`:65`）也未捕获，与 `claim` 的处理不一致。
- **影响**：掉电/崩溃留下半截 JSON → 之后所有 `claim`/`report` 直接抛栈，任务不可恢复；并发 `write_json` 同一路径时两个写者偏移交错，可产生混杂内容。
- **复现**：`python -c "import pathlib;p=pathlib.Path('.agent-bus/tasks/claude-backend-audit.json');p.write_text('{\"a\":')"` 后再 `claim` → traceback（属破坏性操作，未执行）。
- **修复**：`tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` + `os.replace`；读取端统一捕获并给出可读错误；`ensure_bus()` 幂等化（`:32-35` 每条命令都无条件重写 `.gitignore`，`:47/:70/:88` 调用）。

#### F7. 后端 stderr 被 `pipe` 但从不读取（反压死锁 + 诊断信息不可见）
- **证据**：`frontend/tui/src/backend.ts:26` `stderr: "pipe"`；`readOutput`（`:80-113`）只消费 stdout，`frontend/tui/src` 中 `stderr` 仅此一处命中。Python 侧确有写 stderr：`src/ai_pr_review/backend/jsonl_server.py:779` `print(f"backend request failed: {exc!r}", file=sys.stderr, flush=True)`，另有 `config.py:959-965` 的 `RuntimeWarning` 与 `services/pr_fetcher.py` 的 `logger.warning`（审查期间会触发）。前端仅能看到 `app.tsx:973-975` 的"Python 后端启动失败：Python backend connection closed"，**看不到真实堆栈**。
- **影响**：① stderr 写满管道缓冲后子进程阻塞、后端假死（无超时兜底）；② 启动失败/请求失败的真实原因对用户与开发者完全不可见。
- **修复**：`readOutput` 增加 stderr 排空协程（有界环形缓冲 + 出错时附加到错误消息），或改 `stderr: "inherit"` 便于调试。

#### F8. 前端请求无超时；`request()` 存在 pending 条目泄漏/脏报错窗口
- **证据**：`frontend/tui/src/backend.ts:41-60` `request()` 无 timeout / AbortSignal；`:51` `const stdin = this.process!.stdin` 使用非空断言；`:50` 已把条目写入 `this.pending`。`readOutput` 的 `finally`（`:105-111`）只在 `this.process === spawned` 时 `rejectPending`，而 `rejectPending`（`:75-78`）**不区分代次**、一刀切清空。
- **影响**：进程若在 `await start()` 返回后、`:51` 执行前被置为 `undefined`，会抛出 `Cannot read properties of undefined` 这类脏错误，且 `:50` 注册的条目再无人 settle（泄漏）；无超时意味着任何"后端不回应"都会让 UI 永久挂起。
- **修复**：`const proc = this.process; if (!proc) { this.pending.delete(id); throw new Error("backend not running") }`；为 `request()` 增加超时与按 generation 标记的 pending 桶。

#### F9. `review.*` 事件完全不做归属过滤（`assistant.*` 做了）
- **证据**：`frontend/tui/src/protocol.ts:17-29` `isCurrentAssistantEvent` 只在 `app.tsx:891` 被调用一次，仅覆盖 `assistant.` 前缀；`app.tsx:896-952` 的 `review.started/stage/file_started/file_done/completed/failed/cancelled` 分支不比较 `event.session_id`，而事件是带 `session_id` 的（`jsonl_server.py:318、327-334、337-354、725、736、746、757`）。另：`_publish` 的每 session 计数（`jsonl_server.py:290-306`）只在 review 分支复位（`:769`），**chat 产生的 delta 会把计数推向 2048 上限**，之后同一 session 内的 `review.stage / file_started / file_done` 会被静默丢弃（进度条冻结，但 `review.completed` 仍会到达）。
- **修复**：把过滤扩展到 `review.*`（按 `session_id`），或统一给所有事件加 `request_id`；`event_counts` 在 chat 结束/新对话时复位。

#### F10. 普通聊天只依赖 `assistant.finished`，无 `result.text` 兜底
- **证据**：`app.tsx:261-264` 只在 `text.startsWith("/")` 时才把 `response.result.text` 追加进消息；`app.tsx:956-961` `assistant.finished` 是唯一写入点。归属过滤需要 `request_id` 非空（`protocol.ts:22-28`），任何一次过滤/丢帧都会让回答**静默消失**（UI 只把状态改回 READY）。
- **修复**：非命令分支在 `response.ok` 且消息未被 finished 写入时，用 `response.result.text` 兜底。

#### F11. openai 流式：`emit().result()` 无超时 + 跨线程 close 竞态
- **证据**：`services/model_providers/openai.py:48-51` `asyncio.run_coroutine_threadsafe(on_delta(delta), loop).result()`（worker 线程无超时阻塞事件循环）；`:57-61` 在事件循环线程 `active_response[0].close()`，而同一 response 对象正被 worker 线程在 `:98` `for line in response` 迭代，`:141-142` 才 `active_response.clear()`；`ollama.py:31-33` 直接透传给父类，无额外取消处理；`base.py:36-46` 的非流式回退**完全不处理 cancel_event**（Anthropic 走此路径）。
- **影响**：取消瞬间可能让读线程抛 `ValueError`（结果被 `to_thread` 的已取消 future 吞掉，用户不可见）；事件循环繁忙时 delta 投递会反压 worker 线程；Anthropic 路径下取消要到整段响应返回后才在 `jsonl_server.py:284-285` 生效。
- **修复**：`.result(timeout=...)`；`close()` 改为置 `cancel_event` 后由 worker 线程自行退出并 close（用锁保护 `active_response`）。

#### F12. `agent_bridge` 的 `task_id` 未做路径净化
- **证据**：`scripts/agent_bridge.py:65,71,75,89,103` 全部形如 `TASKS / f"{task_id}.json"`。pathlib 语义下 `--task-id ../../evil` 会写出总线之外；Windows 下若 `task_id` 是绝对路径，`TASKS / "C:/tmp/x.json"` 会整体替换路径，`report`（`:103`）还会以 `O_TRUNC` 覆盖同名 `.json`。
- **影响**：本地工具被误用/滥用时可写入或覆盖任意 `.json`（含读取任意 JSON 文件，`:72/:90`）。属安全加固项。
- **修复**：`re.fullmatch(r"[A-Za-z0-9_-]{1,64}", task_id)` 校验后再拼路径。

#### F13. 环境变量 `AI_PR_REVIEW_PROVIDER` 取值非法会让后端启动即崩
- **证据**：`config.py:827-834` `_apply_env_overrides` 直接 `ModelProviderConfig.from_name(provider_override)`，而 `from_name` 对未知名字抛 `ConfigValidationError`（`:418-419`）；该调用**没有**像 `AIClientConfig.__post_init__`（`:654-656`）那样包 try/except。异常沿 `AppConfig.load` → `JsonlBackend.__init__` 冒泡，进程退出。
- **影响**：`AI_PR_REVIEW_PROVIDER=typo pr-review chat` → 后端进程直接退出；前端只显示"connection closed"（叠加 F7 后完全无法定位）。
- **修复**：捕获 `ConfigValidationError` 并降级为"忽略该覆盖 + stderr 明确提示"；或在 `main()` 里包一层把启动异常写成一条 `ok:false` 协议帧。

#### F14. 运行时 profile 不可往返；`save()` 失败会留下内存/标志不一致
- **证据**：`jsonl_server.py:51-58` `_infer_runtime_profile` 只可能返回 `local|cloud|hybrid`，`offline` 永不出现（`:62` 将 `offline` 并入 local 分支）；`:78` `self.runtime_profile = profile` 在 `:79` `save()` **之后**执行——若 `save()` 抛异常（目录只读、磁盘满），配置已改而标志未更新。
- **修复**：把 `runtime_profile` 一并持久化到 `preferences`，先从持久值推断；`save()` 放到状态更新之后或用 try/finally。

#### F15. `ResultStore` 构造期的 `.write-probe` 探测与非预期建库
- **证据**：`services/result_store.py:55-61` `_resolve_db_path`：`requested.parent.mkdir(parents=True, exist_ok=True)` + `probe.touch(exist_ok=False)` + `probe.unlink()`。残留的 `.write-probe`（崩溃窗口）会让 `touch` 抛 `FileExistsError`；对非默认路径 `:71-72` 会**直接 `raise`** → `/history` 整体失败。同一路径的两个 `ResultStore` 并发构造（例如 review 的 `HybridReviewOrchestrator.__init__`：`services/hybrid_orchestrator.py:35`，与 `/history` 的 `jsonl_server.py:384/398/676`）存在极小概率的竞态。
- **影响**：只读的历史查询会产生目录创建与库文件创建副作用；极端情况下 `/history` 报"请求失败"。
- **修复**：用唯一名探测（`tempfile.mkstemp(dir=parent)`）或改为 `os.access` 判断并接受 TOCTOU。

#### F16. 结果库路径的静默 CWD 回退
- **证据**：`services/result_store.py:62-82`：路径不可写且等于平台默认时，改道 `Path.cwd()/".ai_pr_review"/"results.db"`（`:73`），且**平台默认这一支不发任何警告**（`:75-81` 只为 legacy 字面量 warn）；`jsonl_server.py` 从不读取 `using_fallback_path`（该属性只被 `web_server.py:615` 与 doctor 使用）。
- **影响**：受限环境下历史会落到 CWD 相对目录，用户看到"历史记录消失"而无任何提示；叠加 F1 放大"同一配置多方落库"。
- **修复**：`_publish`/`_history_text` 检查 `using_fallback_path` 并在回包中提示实际路径。

#### F17. 取消是协作式的：长任务期间不生效，尾窗取消后仍会落库
- **证据**：`jsonl_server.py:320-357` 的 `check_cancelled()` 只挂在 `stage_callback` / `file_started` / `file_done` 三个回调上；`_run_review` 在 `:359-379` `await run_review(...)` 返回后**再无取消检查**，直接返回并发布 `review.completed`。落库点在其内部：`services/hybrid_orchestrator.py:184` `stage("persisting", ...)`（→ 触发一次 `check_cancelled`）紧接着 `:225` `save_result`。因此：取消若发生在最后一个回调之后，审查仍会完整完成、写库并发布 `review.completed`；同时 `command == "cancel"` 已先返回"已请求取消当前审查"（`:695`）。
- **影响**：用户看到"已取消"但结果仍落库并入历史；单文件的长 AI 调用期间取消无即时响应。
- **修复**：在 `run_review` 返回后、写库前再查一次取消；或把取消检查下沉到每个文件的 AI 调用边界。
- **补充**：`jsonl_server.py:685-697` 的 `cancel` 用 `if chat_task ... elif review_event` 顺序判断——当同一 session 上 chat 与 review 并存时，**只能取消 chat**，review 无取消入口。

#### F18. `AIClientConfig.model_provider` 属性被重复定义（前一份为死代码）
- **证据**：`config.py:678-690` 与 `config.py:692-705` 同名 `@property model_provider`，后者覆盖前者；两者差异仅在 `display_name`（硬编码 `self.provider` vs 查 `MODEL_PROVIDER_PRESETS`）。`_apply_payload:919` 与 `save():951`、`jsonl_server.py:109/266` 使用的都是后者。
- **影响**：无运行时错误，但阅读与维护风险高（改错"那一份"不会生效）。
- **修复**：删除 `:678-690`。

#### F19. Web 侧同类隔离缺口（附带发现）
- **证据**：`web_server.py:77` `config_path: Path | None = None` 类属性，`serve(config, host, port)`（`:599`）**从不给它赋值**；`web_config.py:85`/`:121` 用 `config_path or DEFAULT_CONFIG_PATH` 兜底。因此 `pr-review --config X serve` 的配置页会显示/保存到默认路径（且忽略 `AI_PR_REVIEW_CONFIG`）。
- **影响**：Web 设置页保存会写到非预期文件。
- **修复**：`serve()` 增加 `config_path` 参数并由 CLI 传入（`cli.py:3950` 调用处）。

---

## 已验证正常项

- **V1 显式 `Path` 的隔离逻辑本身正确**：`config.py:935-939` 把 `db_path` 绑定到 `Path(path).parent / "results.db"`，且文件里显式 `db_path` 优先（`:936-937`），有测试固定（`tests/test_jsonl_backend.py:350-369`、`:372-381`）。缺陷只在调用方（F1）。
- **V2 `/report`、`/export` 不触碰 SQLite**：`jsonl_server.py:434-465` `_export_text` 与 `:640-666` `report/export` 只读 `self.current_report`（`:45` 初始化，仅 `:372` 赋值）→ 天然无跨库串线；代价是重启即丢（`:641-642` 会提示"当前会话还没有审查报告"）。
- **V3 无 `ResultStore` 单例/缓存**：全 `src/` 无 `lru_cache` / 模块级 store / 全局 DATABASE 常量；每次请求新建，`_connect` 用后即关（`result_store.py:331-342`）。共享只通过相同的 `db_path` 字符串隐式发生。
- **V4 旧密钥不会跨 provider 残留**：`config.py:807-810` `same_provider` 判定 + `:816-825` 用 `provider.api_key` 重建 `AIClientConfig`，使"deepseek→ollama"切换后旧 Key 一定被清空；`tests/test_jsonl_backend.py:340-348` 断言切回后 `ai_client.api_key == ""`。
- **V5 环境变量覆盖会整体重建 endpoint/模型**：`config.py:828-834` 在 provider 变化时重建整个 `ProviderConfig`（含 base_url / api_format / default_model），不再残留旧 endpoint——与 `:830-831` 的注释一致，属已修复项。
- **V6 agent_bridge 认领锁是原子的**：`agent_bridge.py:39` `os.O_EXCL` + `:78` 独占创建 + `:79-80` `FileExistsError` → 本机文件系统上两个活进程无法同时认领同一任务。
- **V7 取消后不会写入半截回答**：`jsonl_server.py:284-287` 在 `stream_chat` 返回后、写 `session.messages` 之前检查 `cancel_event`；delta 被 `openai.py:49` 与 `jsonl_server.py:542-543` 双重拦截（两处是**同一个** `threading.Event` 对象，经 `_chat(... cancel_event=...)` → `stream_chat(cancel_event=...)` 传递）。
- **V8 单请求不会重复 `assistant.finished`**：发布点唯一（`jsonl_server.py:578-587`），与 `except`（`:556` / `:567`）互斥；全仓 grep 仅 5 处 `assistant.*` 发布点，且都在该 `try` 结构内。
- **V9 前端归属过滤对聊天有效且不可能串号**：`protocol.ts:17-29` 同时校验 `session_id` 与 `request_id`；`backend.ts:5/47-48` 的 `nextId` 单调递增且**从不重置**，旧进程不可能用同 id 命中新 pending。
- **V10 `not_found` 重试结构上只执行一次且不会重复执行消息**：`session-recovery.ts:8-11` 无循环；`jsonl_server.py:518-525` 的 `not_found` 分支在**任何副作用之前**返回（不写 session、不发 `assistant.started`），故重放安全；`session-recovery.test.ts:4-19`（只重试一次）与 `:21-29`（`backend_error` 不重放）固化了该语义。
- **V11 session 重建按进程代次绑定**：`app.tsx:833/838/849` 用 `boundGeneration === backend.generation` 判定复用，重启后**不会**复用旧 session id；`backend.ts:107-110` 的 `this.process === spawned` 守卫防止旧 reader 清掉新一代 pending。
- **V12 审查取消链路能干净抛出**：`check_cancelled`（`jsonl_server.py:320-322`）→ `ReviewCancelled` → `:733-742` 发布 `review.cancelled`；`cli.py` 的回调不吞异常，`run_review` 只有 `finally` 无 `except`。

---

## 不确定项

1. **未做任何运行时验证**：本次未执行 Python、Bun、TUI 或任何写操作；F1/F3/F17 的"复现命令"是**建议执行路径**，我没有运行。所有行号基于当前工作区内容。
2. **F7 的反压死锁**是风险而非确证：取决于 stderr 实际流量与管道缓冲大小，我未实测触发阈值；但"stderr 内容对用户完全不可见"是确定性结论。
3. **F11 的跨线程 close 竞态**：能否真正让读线程抛异常取决于 `HTTPResponse.close()` 与阻塞读的时序，未构造验证。
4. **F9 的 review 事件串线**：代码层确实缺少过滤，但触发需要一个"旧 session 的 review 仍在跑、前端已换绑 session"的场景；后端重启会同时杀掉审查，因此**是否可复现存疑**（我按代码缺口上报）。
5. **F15 的 `.write-probe` 竞态**：残留概率极低、并发构造窗口为微秒级，未实测；"非默认路径不可写时直接抛错"则是确定性行为。
6. **F2 的相对路径分支**：依赖 `--config` 传入的是相对路径且两次运行的 CWD 不同；我未构造验证该组合。
7. **`write_json` 的 `O_EXCL` 原子性**：在 NTFS 本地盘上成立；若 `.agent-bus` 落在 OneDrive/网络盘，脚本未做任何平台或文件系统判断，我未实测。
8. **文档漂移**：`docs/modern-tui-migration.md`（后端重启/会话重建设计说明）与 `docs/FIX_REPORT.md:26-50`（描述的是已不存在的 `ResultStore.from_env()` + `platformdirs` 设计）我未逐行核对，仅作背景参考，未作为任何结论的依据。
9. **未覆盖**：本次审计未涉及 `chat_runtime.py` / `chat_commands.py` 的旧版纯 Python Chat 路径、`web_jobs.py` 的作业并发，以及 `report_renderer.py` 的渲染正确性——它们不在本次五个主题范围内。
