# P6 交付报告：逐文件审查阶段可中断（任务 `claude-p6-cancel-interrupt`）

**目标**：用户按 Esc / `/cancel` 时，审查要在文件边界**甚至在飞的模型调用处**立即停下来，
而不是等这一次模型调用跑完。

**结论**：两个编排器的逐文件阶段现在都接受 `cancel_check`，每个文件开始前检查，并把
每次模型调用包成 `asyncio.Task` 按 0.25s 轮询取消标志；请求取消时 `task.cancel()`、等它
收尾、再抛 `ReviewCancelled`。取消后不写库、不为没有结论的文件伪造 `reviewed/failed/
skipped` 回调；后端沿用已有的 `except ReviewCancelled` 分支发出 `review.cancelled`，无需改动。

**验证**：`python -m pytest -q --no-cov` → **644 passed, 1 skipped**（定稿状态最后一次运行 69.43s，含新增 5 个用例）。
在飞取消耗时实测 0.37–0.57s（模型调用本身睡 30s）。

---

## 1. 缺陷（改动前实测）

| 证据 | 命令 / 位置 | 结果 |
|---|---|---|
| 逐文件阶段完全没有取消检查 | 改动前快照 `_p5_verify/venv/Lib/site-packages/ai_pr_review/services/review_orchestrator.py:374-382`（该一次性环境已于 2026-09-28 清理；同一份旧代码可用 `git show <改动前提交>:src/ai_pr_review/services/review_orchestrator.py` 复现）：`_review_file_contexts(...)` 参数表里没有 `cancel_check` | 并发跑完全部文件前不会看取消标志 |
| `cancel_check` 只在阶段边界被调用 | 同快照 `:142`（`stage()`）与 `:235`（写库前复查）；hybrid 同构 | 一次模型调用（默认超时 120s）内不生效 |
| 文档自述无法中断在飞调用 | 改动前 `review_orchestrator.py` 的 `ReviewCancelled` docstring：「停止发生在文件之间，无法中断在飞的模型调用」；`review()` docstring 同义 | 与用户实测「按 Esc 要么失败、要么等很久」一致 |
| 同批任务不会被取消 | `asyncio.gather` 语义：只抛第一个异常，同批任务继续跑 | 取消后其余文件的模型调用仍在后台继续 |

## 2. 实现

### 2.1 在飞的模型调用可被取消（`review_orchestrator.py:48-52,126-164`）

新增 `call_with_cancellation(call, cancel_check)`：

- 调用被包成 `asyncio.Task`，`asyncio.wait({task}, timeout=0.25)` 轮询取消标志
  （`CANCEL_POLL_INTERVAL_SECONDS = 0.25`，`review_orchestrator.py:48`）；
- 已请求取消 → `task.cancel()`，**等任务真的结束**（`CANCEL_SETTLE_TIMEOUT_SECONDS = 1.0`，
  `:52`）再抛 `ReviewCancelled`——这样异常的语义是"没有调用还在跑"，而不是"我先走了"；
- 调用方自己被取消（超时 / 退出）时，先 `task.cancel()` 停掉在飞调用，再把
  `CancelledError` 原样抛出（`:156-164`），不吞、不转成失败。

### 2.2 逐文件阶段：每个文件前检查 + 同批任务收尾（`review_orchestrator.py:553-629`）

- `_review_file_contexts(..., cancel_check=None)` 新增参数，`review()` 透传（`:323`）；
- 调度循环里每个文件开始前检查一次：已取消则**立即抛 `ReviewCancelled` 且不再调度后续文件**（`:620-624`）；
- 每个文件真正拿到并发额度后再检查一次（`:573-575`）：排队期间被取消的文件不会发起调用；
- 任务改为显式 `asyncio.create_task`（`:618,624`），取消/自身被取消时调用
  `_cancel_in_flight`（`:167-189`）把同批任务全部取消并等它们结束——`gather` 不会做这件事；
- 取消不走 `failed` 上报、也不触发 `file_done`（`:587-591,614-616`）：没有结论的文件不产生任何
  `file_result` 回调（契约 §10.2 只在 reviewed/failed/skipped 三种结论下发结果，取消不属于任何一种）。

跨文件审查也是一次整轮模型调用，同样接入 `call_with_cancellation`（`:657-659`，调用点
`:364-370`），避免"逐文件阶段能取消、跨文件阶段又要等满一轮"。

### 2.3 hybrid 编排器（`hybrid_orchestrator.py:161-163,216-219,224-226`）

- 逐文件循环开头检查取消标志，已取消立即抛 `ReviewCancelled`，剩余文件不再发起调用；
- 模型调用走 `standard_review.call_with_cancellation`；
- 新增 `except ReviewCancelled: raise` 排在原有 `except Exception` **之前**：否则取消会被
  "该文件审查失败"的兜底分支接走，报成 `failed` 并继续下一个文件。

### 2.4 取消后不落库、后端发 `review.cancelled`（无需改后端）

- 两个编排器原有的"写库前复查 `cancel_check`"原样保留（`review_orchestrator.py:396-397`、
  `hybrid_orchestrator.py:317-318`）；取消在逐文件阶段就抛出，写库路径根本不会走到。
- 后端 `jsonl_server.py:35-39` 直接复用编排器的 `ReviewCancelled` 类，`_run_review` 的
  `except ReviewCancelled`（`:1051-1053`）→ `/review` 命令的 `except ReviewCancelled`
  （`:1705-1715`）发布 `review.cancelled` 并返回 `{"cancelled": true}`；`/cancel` 命令
  （`:1620-1643`）设置的就是同一个 `asyncio.Event`。**本次改动全在 write_scope 内，
  没有触碰 `backend/jsonl_server.py`。**

### 2.5 `ai_client.py`：取消不泄漏额度预留（`ai_client.py:150-158`）

`_release_cost` 改为不取额度锁：释放发生在取消路径的 `finally` 里，去等锁会被（收尾期间的）
第二次取消打断，`_reserved_cost` 会永久留高，之后同一客户端的调用都误判预算已占满。
读改写过程不含 `await`，在单线程事件循环里本身就是原子的，不会与 `_reserve_cost` 的临界区交错。
`review_code` 的重试循环处补注释（`:129-131`）：`CancelledError` 是 `BaseException`，不得被
映射成 `AIServiceError` 再重试。

## 3. 测试

| 文件 | 用例 | 断言 |
|---|---|---|
| `tests/test_review_orchestrator.py:1205` | `test_cancel_interrupts_a_file_review_in_flight` | 每文件睡 30s 的桩；0.3s 置标志 → `ReviewCancelled` 在 1s 内抛出（实测 0.57s）；`sorted(cancelled) == sorted(started)`（每个已发起的调用都收到取消）；`save_result` 零调用；`file_result_callback`/`file_done_callback` 零回调 |
| `tests/test_review_orchestrator.py:1258` | `test_cancel_between_files_does_not_start_further_reviews` | 并发 1；第一个文件的调用里置标志 → 桩只被调用 1 次（`["src/file_0.py"]`），未落库，已完成文件仍照常报 `reviewed` 且触发 `file_done` |
| `tests/test_review_orchestrator.py:1304` | `test_hybrid_cancel_interrupts_a_file_review_in_flight` | 同上（hybrid）：0.37s 内抛出；`started == cancelled == ["src/file_0.py"]`；不落库、不报 `failed` |
| `tests/test_review_orchestrator.py:1350` | `test_cancelled_review_releases_its_cost_reservation` | 取消 + 收尾期间第二次取消（额度锁被别的请求持有）后 `reserved_cost == 0` |
| `tests/test_jsonl_backend.py:1783` | `test_cancel_command_interrupts_a_review_that_is_inside_a_model_call` | 真实编排器接在 `cli.run_review` 后面走 `backend.handle()`：等文件进入模型调用后发 `/cancel` → 命令返回 `cancelled: true`；`/review` 返回 `cancelled: true`；事件里有 `review.cancelled`、没有 `review.failed`/`review.completed`；`cancelled == started`；无 `review.file_done`；无落库；耗时 < 1s（实测 0.27s） |

全量：`New-Item -ItemType Directory -Force -Path .pytest_x` + `TEMP/TMP` 指向它 +
`python -m pytest -q --no-cov` → **644 passed, 1 skipped**（定稿状态 `69.43s`；改动还原后的两次
复跑分别为 `87.27s` / `71.44s`）。

## 4. 变异检查（证明新用例确实能测出旧行为）

| 变异 | 结果 |
|---|---|
| `call_with_cancellation` 不再轮询标志（等模型调用自然返回） | `test_cancel_interrupts_a_file_review_in_flight` 与 hybrid 同名用例双双失败：`AssertionError: 取消用了 2.10s`（桩睡 2s 的加速版） |
| 去掉两处"文件开始前"的 `cancel_requested()` 检查 | `test_cancel_between_files_does_not_start_further_reviews` 失败：`calls == ['src/file_0.py', 'src/file_1.py', 'src/file_2.py', 'src/file_3.py']` |

两次变异均已还原（`grep -n "MUTATION\|if False" src/…/review_orchestrator.py tests/…` 无命中），
还原后重跑全量为上述 644 passed。

## 5. 离线端到端实测（真实 hybrid 编排器，无网络）

```
$ python - <<'PY'   # 真实 HybridReviewOrchestrator + 每文件睡 30s 的桩客户端，0.3s 时取消
ReviewCancelled 在 0.53s 抛出
发起调用 ['src/file_0.py'] / 收到取消 ['src/file_0.py']
落库次数 0；取消 == 发起: True
```

## 6. 未决项 / 边界

1. **线程里的阻塞 HTTP 不是"立刻断开"**：`AIClient.review_code` 走
   `provider.chat`，OpenAI 兼容 provider 的实现是 `await asyncio.to_thread(self._chat_sync, ...)`
   （`model_providers/openai.py:80`）。取消会把 await 侧的调用真正中止（`wait_for` 随之取消
   provider 协程），但那个工作线程要等自己的 socket 超时才结束——要按取消关闭连接需要改
   `model_providers/openai.py`（`stream_chat` 已有 `cancel_event` + 关连接的写法可参考），
   该文件不在本任务 write_scope 内。**默认 provider（Anthropic SDK 异步客户端）不受此限制：
   请求会随任务取消真正中止。** 用户可见行为已达成（≤1s 返回，不再等待调用跑完）。
2. **取消后的 `file_done` 语义**：取消发生在文件内部时不再触发 `file_done_callback`
   （该文件确实没有跑完，后端 `_run_review` 的 `file_done` 本来也会 `check_cancelled()` 抛错、
   不发事件）。契约 §10.2 的"`file_done_callback` 必须照旧触发"针对的是 reviewed/failed 两条
   正常路径，这两条路径的触发时机与顺序（先 result 后 done）逐字未变。
3. **取消标志必须"返回 bool"**：`cancel_check` 的契约是返回布尔值（全仓三个生产者
   `cli.py:1400`、`jsonl_server.py:1042`、`web_jobs.py:204` 都是返回 bool 的 lambda）。
   若某个调用方改成"抛异常式"检查，`call_with_cancellation` 会让在飞调用变成脱手任务——
   本次未为此加固，留作契约约束。
4. **收尾等待有上限**：底层客户端若完全无视取消，最多等 `CANCEL_SETTLE_TIMEOUT_SECONDS = 1.0s`
   即按已取消返回（不会挂死 UI，但那次调用可能仍在背景里跑，见第 1 条）。
