# 配置层交付报告：CHAT/REVIEW 双槽路由 + 仓库上下文配置项（任务 `claude-route-slots`）

**一句话结论**：`PreferencesConfig` 新增 6 个字段（全部有默认值，旧配置文件**零改动**可加载）——
双槽路由 `chat_slot` / `review_slot`（空串 = 跟随运行模式预设）+ 仓库上下文
`repo_context` / `repo_context_max_files` / `repo_context_budget_tokens` / `repo_cache_max_mb`；
新增模块级 `resolve_chat_slot()` / `resolve_review_slot()` / `sync_review_slot_to_strategy()`
与 6 个可独立调用的归一化函数。**非法值一律只告警回退、绝不抛异常**；`resolve_*` 是新旧两条
读取路径的唯一入口。本任务只交配置层与测试，**未接任何消费方**（`_chat` / `ModelSelector` /
`RepoContextProvider` 的接入是后续独立任务）。

- 任务类型：实现（写入范围：`src/ai_pr_review/config.py`、`tests/test_config.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**800 passed, 1 skipped in 74.12s**（全量，含并发任务的用例；同命令复跑三次为
  78.92s / 73.77s / 74.12s，均全绿）；
  本任务自己的文件 `tests/test_config.py`：**146 passed in 0.27s**
  = 既有 20 个用例（未改动一字）+ 本任务新增 **126 个用例**
- 未做：未读/打印凭据；未执行任何 git 操作；未改 `cli.py` / `jsonl_server.py` /
  `model_selector.py`（消费方接入属后续任务，且不在 write_scope）；未改 `frontend/tui`

> 并发提示：本任务运行期间，`mimo-repo-context` 任务正在并行写
> `src/ai_pr_review/services/repo_context.py` 与 `tests/test_repo_context.py`。全量数字因
> 此在两次运行间从 773 涨到 800（同一工作树、同一命令）。本任务自己的 146 个用例两次一致。
> 已核对：`repo_context.py` **尚未**读取本任务新增的配置字段（L1-a 只做 provider + 缓存 +
> 预取策略，配置接入是计划里的 L1-c），因此两者当前没有冲突。

## 1. 背景（两份定稿方案的公共依赖）

| 方案 | 本任务落地的部分 | 位置 |
|---|---|---|
| `docs/dual-model-roles-plan.md` | §3 数据模型：两个槽字段 + §3.3 读取规则 + §3.2 折算规则 | §2.1 / §2.3 |
| `docs/repo-aware-review-plan.md` | §4.6 配置项：4 个仓库上下文偏好 + 越界回退 | §2.2 |

两份方案在 §9.5 / §8 都写明"互相独立、可并行"，唯一的**公共依赖**就是这一层配置。
本任务把它一次性做完，后续两条线的消费方接入就不会各写一份字段解析。

改动前的状态：`PreferencesConfig` 只有 8 个字段，没有任何槽位概念，也没有仓库上下文开关；
一个 `hybrid_strategy` 同时决定聊天与审查，导致"聊天用云、审查用本地"这种组合**无法配置**
（方案 §1.2 列出的三个真实问题）。

## 2. 实现

### 2.1 字段（`config.py::PreferencesConfig`）

```python
chat_slot: str = ""                     # "remote" | "local" | ""           空=跟随运行模式预设
review_slot: str = ""                   # "remote" | "local" | "hybrid" | "" 空=跟随预设
repo_context: str = "tests+imports"     # off | tests | tests+imports
repo_context_max_files: int = 3
repo_context_budget_tokens: int = 4000
repo_cache_max_mb: int = 200
```

全部集中在 dataclass 末尾追加，且**全部有默认值**：既有代码全部用关键字构造
（已核对 `src/` 内 5 处构造点），位置参数兼容性不受影响；`_filter_dataclass_payload`
的"旧版本配置被新版本读"用例也自然覆盖。

新增的模块级常量（供后续消费方 import，避免各处硬编码）：

```python
CHAT_SLOT_VALUES = ("remote", "local")
REVIEW_SLOT_VALUES = ("remote", "local", "hybrid")
REVIEW_SLOT_TO_STRATEGY = {"remote": "remote_only", "local": "local_only", "hybrid": "balanced"}
REVIEW_STRATEGY_TO_SLOT = {"remote_only": "remote", "local_only": "local", "balanced": "hybrid"}
REPO_CONTEXT_MODES = ("off", "tests", "tests+imports")
REPO_CONTEXT_MAX_FILES_RANGE = (1, 10)
REPO_CONTEXT_BUDGET_TOKENS_RANGE = (500, 32000)
REPO_CACHE_MAX_MB_RANGE = (10, 10000)
```

本任务在 `config.py` 落地的符号与行号（供 review 与消费方定位）：

| 符号 | 行 | 说明 |
|---|---|---|
| `CHAT_SLOT_VALUES` … `REPO_CACHE_MAX_MB_RANGE` | 611-637 | 上表全部常量 |
| `_warn_invalid_preference` | 640 | 统一告警（不回显原值，`stacklevel=3`） |
| `normalize_chat_slot` / `normalize_review_slot` | 654 / 671 | 槽位归一化 |
| `normalize_repo_context` | 684 | 仓库上下文模式归一化 |
| `_normalize_bounded_int` | 695 | 上下界归一化的共享实现 |
| `normalize_repo_context_max_files` / `..._budget_tokens` / `normalize_repo_cache_max_mb` | 723 / 733 / 743 | 三个上限 |
| `PreferencesConfig`（含 6 个新字段与扩展的 `__post_init__`） | 754 | `__post_init__` 在 774 |
| `_preferences_of` / `_hybrid_strategy_of` | 790 / 801 | 内部 helper，同时接受 `AppConfig` 与裸 `PreferencesConfig` |
| `resolve_chat_slot` / `resolve_review_slot` / `sync_review_slot_to_strategy` | 806 / 822 / 834 | 三个公开入口 |

### 2.2 校验：6 个归一化函数（`__post_init__` 内调用）

沿用 `normalize_workbench_mode` 的既有惯例（`config.py:589-605`）：**只回退 + 告警，不抛异常**，
提示里不回显原值。校验放在 `__post_init__`，因而 `load` / `from_env` / 向导 / 测试四条路径
共用同一套规则，不会出现"某条路径漏校验"。

| 字段 | 合法取值 | 非法时 | 归一化行为 |
|---|---|---|---|
| `chat_slot` | `remote` / `local` / `""` | `""` + `RuntimeWarning` | 大小写/空白归一（`" Remote "` → `remote`） |
| `review_slot` | `remote` / `local` / `hybrid` / `""` | `""` + `RuntimeWarning` | 同上 |
| `repo_context` | `off` / `tests` / `tests+imports` | `tests+imports` + warning | 同上 |
| `repo_context_max_files` | 1..10 | `3` + warning | 接受 `int`、整值 `float`、整数字符串 |
| `repo_context_budget_tokens` | 500..32000 | `4000` + warning | 同上 |
| `repo_cache_max_mb` | 10..10000 | `200` + warning | 同上 |

**空串不是非法值**：`chat_slot=""` 的语义就是"跟随运行模式预设"，与非法值回退后的结果一致，
因此**不告警**（旧配置加载全程静默）。

**`bool` 显式判为非法**：`bool` 是 `int` 的子类，`True` 会被 `1 <= 1 <= 10` 放行——
"最大文件数 = True"不是用户能表达的意思，按非法值处理比静默当 1 安全（有用例钉住）。

### 2.3 解析：3 个模块级函数

```python
def resolve_chat_slot(config) -> str:      # "remote" | "local"
    explicit = normalize_chat_slot(getattr(_preferences_of(config), "chat_slot", ""))
    if explicit:
        return explicit
    return "local" if _hybrid_strategy_of(config) == "local_only" else "remote"

def resolve_review_slot(config) -> str:    # "remote" | "local" | "hybrid"
    explicit = normalize_review_slot(getattr(_preferences_of(config), "review_slot", ""))
    if explicit:
        return explicit
    return REVIEW_STRATEGY_TO_SLOT.get(_hybrid_strategy_of(config), "remote")

def sync_review_slot_to_strategy(config) -> None:
    explicit = str(getattr(_preferences_of(config), "review_slot", "") or "").strip().lower()
    strategy = REVIEW_SLOT_TO_STRATEGY.get(explicit)
    if strategy is not None:
        preferences.hybrid_strategy = strategy
```

推导规则逐字对齐任务描述与方案 §3.3 / §3.4：

| `hybrid_strategy` | `resolve_chat_slot` | `resolve_review_slot` |
|---|---|---|
| `local_only` | `local` | `local` |
| `remote_only` | `remote` | `remote` |
| `balanced` | `remote` | `hybrid` |
| 未知（`quality_first` / `cost_optimized` / `offline` / 空串） | `remote` | `remote` |

**函数放在模块级而不是 `AppConfig` 方法**（任务允许二选一，这里说明理由）：
① 方案 §5.1 第 2 行明确写的是"`config.py`（模块级函数）"；
② 消费方 `ModelSelector` 拿到的 `config` 与 `_chat` 拿到的 `AppConfig` 类型不同，
模块级函数用 `_preferences_of()` 同时接受 `AppConfig` 与裸 `PreferencesConfig`，
两处接入不必各自适配；③ 不依赖实例状态，单测可以直接构造最小对象调用。

## 3. 语义选择（可复核的取舍）

1. **告警点唯一**：`resolve_*` 内部调用与 `__post_init__` 相同的归一化函数，因此
   "构造期告警"与"resolve 告警"是**同一份实现、同一条文案**，不会各写一套而漂移。
   正常路径只告警一次：构造时坏值已被归一化为 `""`，resolve 再看到的就是合法空串。
2. **`resolve_*` 是只读的**：遇到构造之后被直接赋的坏值，它告警 + 回退，但**不改写配置**。
   若顺手改写，第二次调用就不会再告警，用户也就看不到线索了（有用例钉住"赋值后仍是原值"）。
3. **为什么槽位归一化到 `""` 而不是原地保留坏值**：`config.py:775` 的既有不变量是
   "属性一旦构造出来就保证合法"。保留坏值会让属性在构造后仍可能非法，与该不变量冲突。
   代价是磁盘上的手写坏值在下次 `save()` 时被写成 `""`（语义等价于"跟随预设"，即回退本身），
   与 `workbench_mode` 的既有行为一致。
4. **`sync_review_slot_to_strategy` 不告警**：空值/非法值一律不动 `hybrid_strategy`
   （"用户没细化路由时，预设就是唯一事实来源"）。告警点已经在 `resolve_review_slot`，
   两处都发会让同一次读取重复告警。**合法值匹配大小写不敏感**（`" Hybrid "` → `balanced`），
   与 `resolve_*` 的归一化口径一致。
5. **聊天槽不参与折算**：聊天只从预设**推导**（`balanced` → 聊天走远端，方案 §3.4 明确
   "不变（聊天仍走远程入口）"），从不反向写回 `hybrid_strategy`。因此
   `sync_*` 只看 `review_slot`，`chat_slot` 改了不会污染预设。
6. **未知预设不告警，一律落远端**：`quality_first` / `cost_optimized` 是 `cli.py` 的真实取值
   （`--mode quality` / `--mode cost` 会写入 `hybrid_strategy`）。任务描述把"未知"与
   `remote_only` 并列为 `-> "remote"`，这里**照做且不额外告警**——见 §7.2 的遗留讨论。

## 4. 测试（`tests/test_config.py`，新增 126 个用例）

既有 20 个用例**一字未改**；新增用例追加在文件末尾，并新增
`ROUTE_SLOT_KEYS` / `REPO_CONTEXT_KEYS` / `NEW_PREFERENCE_KEYS` 三个常量与两个 helper
（`_preference_warnings` / `_legacy_config`）。

| 任务要求的覆盖点 | 对应用例 |
|---|---|
| 6 个新字段默认值 | `test_route_slot_and_repo_context_defaults_match_the_plan`（+ `..._constants`） |
| 旧配置（JSON 里完全没有新字段）加载后，三种 `hybrid_strategy` 的 `resolve_chat_slot` / `resolve_review_slot` 推导各一例 | `test_legacy_config_derives_slots_from_strategy[remote_only/local_only/balanced]`——helper 额外断言**旧配置静默加载** |
| 显式 slot 优先于推导（含 `chat=local` + `remote_only`） | `test_explicit_slots_win_over_strategy_derivation`（10 组）+ `test_chat_local_with_remote_only_strategy_is_the_configured_combination` |
| 非法显式值回退 + warning | 构造期 3 个、加载期 2 个、构造后赋值 1 个，共 6 个用例（20 组输入） |
| `sync_review_slot_to_strategy` 三种折算正确 + `review_slot` 为空时 `hybrid_strategy` 不变 | `test_sync_review_slot_folds_into_hybrid_strategy`（3）+ `test_sync_review_slot_leaves_strategy_untouched_without_explicit_slot`（4） |
| save/load 往返保留 6 个新字段 | `test_route_slot_and_repo_context_fields_survive_save_load_roundtrip`（+ 快照视图用例） |

额外补充的边界用例：`hybrid` 对聊天槽非法而对审查槽合法、告警不回显原值（防止把密钥或
终端控制字符回显到终端）、resolve 永不抛异常（`None`/`{}`/`object()`）、接受裸
`PreferencesConfig`、归一化函数可独立调用、`bool` 判非法、三个上限的上下边界与整值浮点/字符串
输入、折算幂等与"折算→再推导"往返闭合、6 个字段进入 `__dict__` / `asdict` 快照视图。

## 5. 变异检查（防止用例假绿）

用 `sha256` 备份 → 改一处 → 只跑 `tests/test_config.py` → 逐字还原 → `sha256sum -c` 校验
字节级一致（`grep -rn MUTATION-M src/ tests/` 无残留）。

| 变异 | 结果 | 是否被抓 |
|---|---|---|
| M1：`__post_init__` 去掉 `chat_slot`/`review_slot` 归一化 | **22 failed, 124 passed** | ✅ |
| M2：`resolve_chat_slot` 改成显式槽位不优先（`if False:`） | **7 failed, 139 passed** | ✅ |
| M3：`sync_*` 改成"空值也写 `balanced`"（去掉 `if strategy is not None`） | 首轮 **146 passed** ❌ → 修用例后 **4 failed, 142 passed** | ⚠️→✅ |
| M4：`REVIEW_STRATEGY_TO_SLOT["balanced"]` 改成 `"remote"` | **2 failed, 144 passed** | ✅ |

**M3 首轮没被抓到，是本任务发现的一个真实测试缺陷**：原用例把哨兵值设成 `balanced`，
而变异恰好也写 `balanced`，两者无法区分。已把哨兵改成 `remote_only` 并在用例里写明理由
（`tests/test_config.py::test_sync_review_slot_leaves_strategy_untouched_without_explicit_slot`），
复跑变异即被抓住。还原后全量复跑仍全绿。

## 6. 本地端到端实测（离线、无网络、无真实凭据）

`.pytest_x/route_slots_sample.py`（产物 `.pytest_x/route_slots_sample.txt`）：全程走真实组件——
`AppConfig.load` / `save` / `PreferencesConfig` 构造 / `resolve_*` / `sync_*`，无任何桩。
只打印路由与仓库上下文字段，不打印任何 Key（样例用的是假 Key）。

```text
== 1. 旧配置（磁盘上完全没有新字段）→ 三种运行模式预设的等价映射 ==
  hybrid_strategy=remote_only  -> CHAT=remote  REVIEW=remote  期望=('remote', 'remote') 一致=True
    落盘 preferences 键含新字段=False  加载告警=[]
    磁盘未被改写（惰性迁移，方案 §3.4）: chat_slot 仍缺失=True
  hybrid_strategy=local_only   -> CHAT=local   REVIEW=local   期望=('local', 'local') 一致=True
  hybrid_strategy=balanced     -> CHAT=remote  REVIEW=hybrid  期望=('remote', 'hybrid') 一致=True

== 2. 组合 3（隐私+质量）：CHAT=local, REVIEW=remote —— 旧架构无法表达 ==
  sync 折算后 hybrid_strategy = remote_only (期望 remote_only)
  resolve_chat_slot   = local (期望 local)
  resolve_review_slot = remote (期望 remote)

== 3. 仓库上下文配置项：合法值落盘 / 越界回退 ==
  合法值往返: ['off', 5, 8000, 500] (期望 ['off', 5, 8000, 500])
  越界回退: ['tests+imports', 3, 4000, 200] (期望 ['tests+imports', 3, 4000, 200])
  告警 4 条（每条一个字段，文案见下）

== 4. 坏槽位值：加载回退 + resolve 回退，均不抛异常 ==
  加载: chat_slot='' review_slot='' (期望均为 '')
  resolve -> CHAT=remote REVIEW=hybrid
  坏值不回显在告警里: True
  直接赋值绕过构造 -> 仍不抛异常: remote

== 6. 三个合法 review_slot 折算后再推导，回到原槽位（往返闭合） ==
  review_slot=remote  -> hybrid_strategy=remote_only  -> 再推导=remote
  review_slot=local   -> hybrid_strategy=local_only   -> 再推导=local
  review_slot=hybrid  -> hybrid_strategy=balanced     -> 再推导=hybrid
```

第 1 段额外验证了方案 §3.4 的"迁移在读取时惰性完成，**不强制改写磁盘**"：
`resolve_*` 跑完之后重新读文件，`chat_slot` 键**仍然缺失**——即旧配置不会被静默升级写盘。

越界回退的实际告警文案（与 `workbench_mode` 同格式，且都不含原值）：

```text
配置项 preferences.repo_context 的值不受支持，已回退为 tests+imports（可选值：off、tests、tests+imports）。
配置项 preferences.repo_context_max_files 的值不受支持，已回退为 3（允许范围：1..10）。
配置项 preferences.repo_context_budget_tokens 的值不受支持，已回退为 4000（允许范围：500..32000）。
配置项 preferences.repo_cache_max_mb 的值不受支持，已回退为 200（允许范围：10..10000）。
```

## 7. 未决项 / 边界（需要后续任务处理）

### 7.1 ⚠️ `cli.py` 的两处整体重建会重置这 6 个字段（**本任务不能改，必须由后续任务补**）

`cli.py` 有**两处**逐字段重建 `PreferencesConfig`，且都不在本任务 write_scope：

| 位置 | 影响 |
|---|---|
| `cli.py:1117-1128`（`_prompt_interface_preferences`，向导第 2 阶段） | 不带回 6 个新字段 |
| `cli.py:1207-1216`（`_prompt_preferences`，向导第 6 阶段） | 同上 |

这两处的既有注释已经写明了这个陷阱：

> `# 本阶段不提问，但必须原样带回：PreferencesConfig 是整体重建的，`
> `# 漏掉一个字段就等于每次跑向导都把它悄悄重置成默认值。`

**后果**：用户手工设置 `chat_slot=local` / `repo_context=off` 之后，只要跑一次
`pr-review config`（向导），这 6 个字段就会被静默重置为默认值。**这正是本任务
必须上报而不是自行修复的点**——`cli.py` 不在写入范围内。

建议后续任务在两处各补 6 行 `getattr(current, ...)`（与 `workbench_mode` 的写法一致），
或改为 `dataclasses.replace(current, **{改动字段})` 以避免"新增字段必漏"的结构性缺陷。
本任务已用测试钉住配置层本身（save/load 往返无损），但**无法**覆盖向导这条路径。

`src/` 内共 5 处 `PreferencesConfig(` 构造点：cli.py 2 处（上表）、config.py 2 处
（`from_env` / `_apply_payload`，均安全）、`config_entry.py:117`（`config import`）——最后这处
`PreferencesConfig(**preferences_payload)` 是**按文件内容照实导入**，导入文件里没有的键自然取
默认值，属于 import 的既定语义，与本条的"静默重置"不是一回事，这里一并对齐口径。

### 7.2 `quality_first` / `cost_optimized` 被推导成"远端"（照任务描述执行，但值得复核）

`cli.py:2913-2919` 的 `--mode` 会把 `quality_first` / `cost_optimized` 写进
`hybrid_strategy`，而它们是 `HybridStrategy` 的合法成员（`model_selector.py:23-30`）。
任务描述把"未知"与 `remote_only` 并列为 `-> "remote"`，本任务**逐字照做**，因此：

- `--mode cost`（成本优先）的审查槽推导结果也是 `remote`，直觉上应偏本地；
- 但 `ModelSelector` 目前把 `cost_optimized` 判为 `HybridStrategy.COST_OPTIMIZED`
  （既非 `LOCAL_ONLY` 也非 `REMOTE_ONLY`），走的是自己的分流逻辑，**不是**纯远端。

所以这**不是**本任务引入的回归（本任务没有接任何消费方），但
`docs/dual-model-roles-plan.md` §5.1 第 7 行"`_get_strategy` 改为读 `resolve_review_slot()`"
落地时，`cost_optimized` 的行为会从"成本分流"变成"全远端"——**这是一次真实的行为变更**。
建议在接入任务里把 `REVIEW_STRATEGY_TO_SLOT` 补上
`cost_optimized -> local`（或保留 `hybrid`），并把该决策写进方案文档；本任务不擅自扩充
任务描述给出的映射表。

### 7.3 消费方一个都没接（按任务要求）

`_chat` / `ModelSelector._get_strategy` / `RepoContextProvider` /
`JsonlBackend._config_snapshot` / `config.options` / TUI 状态栏全部**未改**。因此：

- 本任务落地后**运行时行为与改造前完全一致**（新字段只被存储和解析，没人读）；
- `config.snapshot` / `config.options` 里还看不到 `routing` 段
  （方案 §5.4 的契约属 P2/P3）；
- `repo_context` 的 4 个字段已经可以被 `RepoContextProvider` 直接读取
  （`normalize_*` 也可独立调用），但该模块当前尚未接入（见第 1 页并发提示）。

### 7.4 未验证

`frontend/tui` 未构建、未跑测试、未截图（不在写入范围，且本任务不含 UI 改动）；
未跑 `mypy` / `black`——两者在 `pyproject.toml` 里已配置（`line-length = 100`，
`python_version = "3.12"`）但当前环境**未安装**（`python -m mypy` / `python -m black`
均不可用），因此**未经工具校验**。

作为替代，已用脚本按 **black 的口径（字符数，而非字节数——中文按 1 字符计）**核对：
`config.py` 新增块（611-845 行）**0 行超 100 字符**；`tests/test_config.py` 新增用例
**0 行超 100 字符**（修复了 1 行 105 字符的 `parametrize` 装饰器）。全文仅剩
`config.py:482` 一行 124 字符，是**改动前既有**的英文字符串字面量（black 不会拆分
字符串），非本任务引入。无行尾空白。
