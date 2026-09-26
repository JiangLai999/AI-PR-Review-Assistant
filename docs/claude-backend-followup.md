# 后端收尾：测试归位 + max_tokens 跟随 max_output + 未知键过滤 + chat 预算联动

- 任务：`claude-backend-followup`（上游未决项：`docs/claude-b2b3-impl.md` §5 第 3/5 条、设计
  `docs/b2b3-wiring-design.md` §5 风险 2、§6.5）
- 写集：`config.py`、`config_entry.py`、`backend/jsonl_server.py`、`tests/test_config.py`、
  `tests/test_cli.py`、`tests/test_jsonl_backend.py`、本文件
- 验证环境：`TEMP`/`TMP` = `<repo>\.pytest_claude`，逐条 `--no-cov`
- 结论：四项全部落地；两处**刻意的不作为**（review 链路不动、预设表不参与预算放大）与其
  理由见 §2.5 / §4.3；全量 **1143 passed, 1 skipped**（§5）

---

## 1. 测试归位（设计 §4.1 的 C/D 两组，5 条）

`claude-b2b3-impl` 因写集限制把 C/D 组按同名塞进了 `tests/test_jsonl_backend.py`；本轮把
它们放回设计点名（也是 `--blocker` 里点名）的文件，**判据一字未改**：

| 组 | 用例 | 原位置（已删） | 现位置 |
|---|---|---|---|
| C | `test_set_model_spec_touches_only_the_target_model` | `test_jsonl_backend.py:6310` | `test_config.py:706` |
| C | `test_model_spec_bounds_are_sane` | `test_jsonl_backend.py:6348` | `test_config.py:742` |
| D | `test_config_show_and_export_keep_model_specs` | `test_jsonl_backend.py:6364` | `test_cli.py:2628` |
| D | `test_config_import_round_trips_a_relay_spec` | `test_jsonl_backend.py:6402` | `test_cli.py:2661` |
| D | `test_config_health_reports_the_effective_spec_and_source` | `test_jsonl_backend.py:6443` | `test_cli.py:2740` |

**为什么这样选**：设计与 blocker 点名的归属就是"配置层的事归 `test_config.py`、CLI 出口归
`test_cli.py`"，同名的先例（`test_symbol_locate_vocabulary_matches_the_config_layer` 留在
jsonl）只是上一轮的权宜。D 组继续用 `CliRunner` + 全局 `--config <path>` 跑**真实 CLI**
（不是直接调 `config_entry`），这样才真正覆盖"导入/导出/health 三个出口"而不是函数本身。

顺带处理的两件小事：

1. `test_jsonl_backend.py` 顶部只剩 `AppConfig` 一个 config 导入——`CONTEXT_WINDOW_RANGE`
   等 5 个常量 + `ProviderModelConfig` 随 C 组一起迁走，留着就是死导入（附注释说明去向）。
2. 移动后 `test_jsonl_backend.py` 的 B 组小节注释补了 C/D 的去向，避免下一个人再找一遍。

**数字**：三个受影响文件改造前 `456 passed`，改造后 `466 passed`（+3 config / +4 cli /
+3 jsonl，见 §5 明细）。

---

## 2. 未决项：`max_tokens` 跟随 `max_output`（只改 chat）

### 2.1 现状（评估结论）

| 链路 | 额度来源 | 改造前行为 |
|---|---|---|
| review | `config.ai_client.max_tokens`（`jsonl_server.py` 的 review 分支、`AIClient`） | 与模型规格无关 |
| chat 本体 | 同上 + 思考档位预留 `CHAT_REASONING_TOKEN_BUDGETS[effort]`（改造前在 `chat_options` 里直接累加） | `4_096 + 12_000 = 16_096` 直接上线 |
| chat `/compact` | 同上，无预留 | `4_096` 直接上线 |

规格落地（B2/B3）之后这两者会互相打脸：Anthropic 对 `max_tokens` 超过模型输出上限的请求
**直接 400**（`services/model_providers/anthropic.py:51` 原样透传），OpenAI 兼容端点同样按
模型上限拒收（`.../openai.py:160`、`:383`）。也就是说"规格改了但请求体没变"不是体验问题，
是硬失败。

### 2.2 修法：封顶**总额度**（与设计建议等价）

```python
requested = ai_client.max_tokens + reasoning_budget      # 现状的算法
sent      = min(requested, max_output)                   # 新增：规格封顶
```

题目建议的写法是 `effective = min(max_tokens, max_output - 思考预算)` + 思考预算。两者
**恒等**（`b + min(a, M - b) == min(a + b, M)`），取总额度写法只是因为它在
`max_output < 思考预算` 时不会先算出负数再靠加法绕回来。实现见
`jsonl_server.py:2059`（`_chat_max_tokens`），两个调用点：`_chat`（`:2681`）、`/compact`
（`:2940`，无预留、同样不该越过规格）。

**`max_output` 取哪一份**（`_chat_max_output`，`jsonl_server.py:1991`）——"谁背书就用谁的数字"：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | 用户写过的条目（`_user_written_spec`） | 用户在配置助手/`config import` 里填的 `max_output` |
| 2 | 本次进程同步到的**目录**（models.dev） | 实时数据，且**比预设保守**时更该听它的 |
| 3 | 内置**预设**表 | 仓库里唯一可引用的厂商数值（`PROVIDER_MODEL_PRESETS`）；不是运行时探测出来的 |

三条都不成立（模型未知）→ `None` → 请求体与改造前逐字节一致。

### 2.3 两条例外（哪里**不**封顶）

| 例外 | 判据 | 为什么 |
|---|---|---|
| 本地端点 | provider ∈ `CHAT_LOCAL_PROVIDER_NAMES`（`ollama`/`local`，`:295`） | Ollama 不会因超限报错；预设表里本地模型的 `max_output`（如 `qwen3.5:4b` 的 1_024）**是我们自己写死的猜测**，不是厂商限制。§C6 的实测结论（预留不足 → 思考吃满额度 → 答案为空，`docs/model-reasoning-probe.md` R3）正是靠这份预留换来的，按 1_024 封顶等于把它推翻 |
| 规格不可信 | `_chat_max_output() is None` | `from_model_provider` / `ensure_default_model_present` 会给**每个**它不认识的模型写 `32_768/4_096`（`config.py` 的字段默认值）。那不是"知道这个模型"，拿它封顶会让 `deepseek-chat` 这类默认配置的回答额度凭 4_096 缩水。**dataclass 兜底那组数字在任何路径上都不算规格**（含"条目被 `ensure_default_model_present` 补过、但同时有预设"的情形——那时改用预设值，见 §2.4 第 5 行） |

封顶只会**降低**额度、避免硬失败，所以这里信任预设/目录；预算（只增不减、要多花钱的那一侧）
用的是更严的口径，见 §4.3。

### 2.4 边界

| 情形 | 结果 |
|---|---|
| `max_output` 很小（3_000）、预留 8_000 | 发 3_000（`min(4_096+8_000, 3_000)`） |
| 思考预算 > `max_output`（6_000 vs 12_000） | 发 6_000；思考可能吃满额度 → 这是"档位 vs 规格"本身的矛盾，不假装能两全，用户可下调 `/think` 或修规格 |
| 规格足够大（64_000） | 发 4_096 + 12_000 = 16_096，预留全额生效（不封顶 ≠ 一律压低） |
| `max_output` 非法（`null`/0/负数，手改配置可能出现） | 按"不可信"处理 → 退回现状；**不会**抛异常（`_positive_int` 收口，回归用例 `test_chat_spec_never_trusts_auto_written_or_malformed_entries`）。改造前这类值是"只读展示"的，现在会进请求体，所以必须收口 |
| 预设模型 + 兜底条目（`config import` 的 payload 没带 `models` → `ensure_default_model_present()` 补 `32_768/4_096`） | 兜底条目不算数 → **改用预设值**（`claude-sonnet` 例子：封顶 8_192，不是 4_096） |

**对默认安装（anthropic 预设，`max_output = 8_192`）的实际影响**：`/think high|max` 从
"发 12_096 / 16_096" 变成"发 8_192"——这正是改造前会被 Anthropic 按模型输出上限 400 拒收
的那一档（`4_096 + 12_000 > 8_192`），代价是思考预留被规格吃掉一部分，回答的可用额度从
4_096 起算。默认不思考时（`auto`/`off`）请求体不变。

### 2.5 为什么 review 链路不动

`config.ai_client.max_tokens` 在 review 侧承担的是"每条 finding 的输出预算"，与
`review_concurrency`、成本控制（`max_cost_per_run`）耦合；审查模型与聊天模型**可以不是同一个**
（双槽路由），拿聊天槽的规格去改审查请求是跨槽串味。按任务要求"避免改审查行为"：本轮
review 一个字节都没动，规格只在 chat 链路生效。

---

## 3. `config_entry.py:119` 未知键过滤（既有缺陷）

### 3.1 缺陷

`config import` 的偏好分支直接 `PreferencesConfig(**preferences_payload)`：`config export`
**每次都写全量 preferences**，所以新版本导出的文件一定带旧版本不认识的键，旧版本一导入就
`TypeError`——用户连"先导入再升级"的退路都没有。设计 §5 风险 2 记的就是这一条。

### 3.2 修法：把过滤提升为**共用实现**

`config.py` 里已有的 `AppConfig._filter_dataclass_payload` 是私有静态方法。本轮把它提成
模块级 `filter_dataclass_payload(config_type, payload)`（`config.py:1300`），静态方法保留旧
名字转调（`config.py:1470`），`config_entry.run_config_import` 直接用模块级函数
（`config_entry.py:124`）。

**为什么这样选**：过滤规则本身就是"新旧版本的兼容契约"，加载路径（`AppConfig._apply_payload`）
与导入路径是同一件事的两个入口，各写一份迟早各漏各的键（`model_catalog_fetch` 就是那种新键）。
提升为公共函数比跨模块调私有方法干净，也不动任何既有调用点。

### 3.3 回归测试

| 用例 | 位置 | 判据 |
|---|---|---|
| `test_config_import_ignores_unknown_preference_keys` | `tests/test_cli.py:2697` | 导入带 `future_preference_from_a_newer_release` 的 payload → `exit_code == 0`；认识的键照旧生效、不认识的键不进 `preferences.__dict__` |
| `test_filter_dataclass_payload_is_shared_by_load_and_import` | `tests/test_config.py:758` | 模块级函数与私有静态方法同一结果；`AppConfig.load` 读同一份 payload 不炸、合法键生效 |

**仍未修（相邻风险，明确记在 §6）**：`ProviderConfig.from_dict` →
`ProviderModelConfig(**model_data)` 同样不过滤（设计 §5 风险 1）。它没被本轮点名，且"给
`ProviderModelConfig` 加字段"目前没人做；修它的正确时机是"真要加字段"的那一刻——顺手过滤会
静默吞掉用户手写的模型键。

---

## 4. chat 上下文预算与 `model_spec.context_window` 联动

### 4.1 现状

`_chat_context_budget` 固定读 `preferences.chat_context_budget`（默认 8_000），用它做三件事：
注入审查上下文的裁剪预算（`_review_context_for_chat`）、`/context` 的展示、以及
`used_percent`/`over_budget` 的计算。与模型真实窗口无关——一个 1M 窗口的模型和一个 8k 窗口
的模型拿到的注入额度完全一样。

### 4.2 规则（三项，来源常量 `CHAT_BUDGET_SOURCES`，`jsonl_server.py:303`）

| 来源 | 触发条件 | 预算 |
|---|---|---|
| `config` | `chat_context_budget` 是**非默认值** | 用户的值 |
| `model_spec` | 否则，聊天槽模型的窗口有**背书来源**（用户真写过的规格条目 → 本次进程的目录命中） | `min(context_window × 0.5, 200_000)` |
| `fallback` | 其余（含配置值非法/读不懂） | `DEFAULT_TOKEN_BUDGET` = 8_000（改造前的固定值） |

实现：`_chat_context_budget_plan()`（`jsonl_server.py:2011`，返回 `(预算, 来源)`），
`_chat_context_budget()` 保留旧签名只取数字。

**"显式配置"为什么按值判定**：`save()` 每次都写全量 preferences，`chat_context_budget` 这个
键**永远在文件里**（哪怕用户从没选过），所以"键存在"不能当信号，只有"值 ≠ 默认值"才算用户
的选择。

### 4.3 窗口数字从哪来：**数字必须来自为它背书的那份数据**

`_chat_context_window()`（`jsonl_server.py:1970`）只有两个来源，顺序固定：

| 顺序 | 来源 | 判据 |
|---|---|---|
| 1 | 用户真写过的规格条目 | `_user_written_spec`（`:1947`）：与我们会自动写入的那两份（预设值 / `32_768`+`4_096` 兜底）都不同 |
| 2 | 本次进程同步到的**目录**（models.dev） | `_catalog_state.lookup()` 命中——只读索引，绝不取数 |

两者都没有 → `None` → 预算退回 8_000。**内置预设不参与放大**：那是我们自己填的数字
（`PROVIDER_MODEL_PRESETS`），把它当用户规格，等于让**所有**既有用户在升级后从 8_000 一夜
变成 100_000——每轮注入的上下文更多、花的钱更多，而用户什么都没改、也没有任何界面提示过他。

> 题面写的是"用 `model_spec.context_window` 推算"。落地时**没有**直接用
> `config.snapshot.model_spec` 的生效值：目录与生效值不一致时（§2.8 会标
> `needs_verification`），生效值是那份过期的预设/落盘值，按它算会"按 1M 的预设往实际只有
> 8k 的模型里塞上下文"（超窗 → 硬失败）；按目录值算最坏只是少注入一点。宁可保守。

第 3 个理由（为什么连"默认即放大"都不做）：组 C 的契约用例
`tests/test_chat_contract_events.py`（**不在本任务写集内**）断言短消息下
`used_percent > 0`——预算是 8_000 时短消息约 0.2%，抬到 100_000 就四舍五入成 `0.0` 而失败；
`docs/chat-contract-verification.md` 的验收样例也把 `"budget_tokens": 8000` 记录在案。契约
只钉住"五键 + `budget_tokens > 0` + `used_percent > 0`"，并没有钉死具体数值，但那条
`used_percent` 断言已经足够让"默认即放大"在本任务里不可行。

代价是会话内依赖性：同一个配置文件，**没**同步过目录的进程按 8_000，同步过的按真实窗口。
这是"不猜测"与"感知真实窗口"之间能同时保住既有契约的唯一口径；要彻底确定化，需要把"用户
在某次助手里采用过的目录值"落进规格条目（B3 已经有了这条路径：`config.setup` 写
`ProviderModelConfig`，之后就走"用户规格"这一档）。

### 4.4 为什么非法值退回默认而不是按规格算

`PreferencesConfig` 在加载时会把非法值（0/负数/字符串/`null`/**越界**）静默归一化成默认值
8_000，`preferences` 里就再也看不出"配坏了"。本轮额外读一次**文件字面量**
（`_config_preference_literal(..., _MISSING)`，哨兵用来区分"没有这个键"和"键的值是 null"）
只为分辨这两种情况：**配坏了就退回 8_000**，绝不因为读不懂配置反而把预算放大——这是 A3
（`docs/chat-experience-plan.md` §A3）留下的防御语义，`test_chat_context_budget_can_be_set_in_the_config_file`
逐个坏值钉住。字面量的合法性用 `_budget_literal`（`jsonl_server.py:265`）判定，尺子是
`config.CHAT_CONTEXT_BUDGET_RANGE`（`config.py:747`，与 `PreferencesConfig` 的归一化共用
同一份，不再写第二套数字）。显式配置的常见情形不读盘（先判 `preferences` 的值，命中就直接
返回）。

两个附带的口径：

- 推算出来的预算有下界 `max(1, ...)`（`:2050`）：`context_window = 1` 这种手改值会让
  `int(1 × 0.5) = 0`，而 0 会在 `used_percent` 里触发 `ZeroDivisionError`；
- `_chat_context_budget_plan` 里那条"preferences 没有这个字段就去读文件"的分支是**防御
  路径**：现版本的 `PreferencesConfig` 一定有这个字段（构造时补默认值），它只在将来字段被
  移出、或偏好对象换成别的形状时才可能生效，`_chat_context_budget` 的旧实现同样保留着这条
  退路。

### 4.5 为什么"预算来源"不进 `assistant.finished.context`

任务原文是"把预算来源暴露进 `context` 字段"。落地时**没有**加在
`assistant.finished.context` 里：那个对象是契约 v1 冻结的**恰好五键**
（`docs/chat-contract-verification.md` 第 38/95-99 行；`tests/test_chat_contract_events.py:204`
用 `set(...) == {...}` 精确钉住），加键即撕契约，而该测试文件不在本任务写集内。所以来源改走
两处同样面向"上下文"的出口：

| 出口 | 键 | 用途 |
|---|---|---|
| `/context` | `budget_source`（`jsonl_server.py:2552/2580/2597`） | 用户直接看得见"这个预算从哪来" |
| `config.snapshot` | `chat_context_budget_source`（`:875`） | 与既有的 `chat_context_budget` 并列，TUI 状态栏后续可标注来源（**新**键，不占用任何既有标量名） |

`context` 本体只保留数字，并在代码里写了为什么（`jsonl_server.py:2824-2827`），免得下一个人
"顺手补上"。

### 4.6 系数 0.5 与上限 200_000 的理由

- **0.5**：这个预算是"注入**审查上下文**"的额度，但同一个窗口还要装 system prompt 骨架、
   对话历史（窗口 80 条）、仓库文件注入（总量 12k 字符）、以及回答本身。给一半是"上下文 ≤
   窗口一半"的经验分界，超过它就该靠 `/compact` 而不是继续塞。
- **200_000**：直接取 `CHAT_CONTEXT_BUDGET_RANGE[1]`（`config.py:747`，与
   `preferences.chat_context_budget` 的合法上界同一份数字），用户手填得出来的最大值就是它；
   再大的窗口（1M/2M）按它截断——每轮多注入的收益递减、成本线性增长。
- 小窗口模型会算出**比 8_000 更小**的预算（8_192 → 4_096）：这是修正而不是回归，8_000 的
   上下文塞进 8k 窗口本来就会连回答一起挤掉。

---

## 5. 验证记录（真实数字）

> 仓库根目录、PowerShell，`TEMP=TMP=<repo>\.pytest_claude`，逐条 `--no-cov`。

| # | 验证对象 | 命令 | 实测 |
|---|---|---|---|
| 1 | 三个受影响文件（改造前基线） | `python -m pytest tests/test_config.py tests/test_cli.py tests/test_jsonl_backend.py -q --no-cov` | **456 passed, 1 warning in 22.52s** |
| 2 | 同上（交付态） | 同上 | **466 passed, 1 warning in 38.32s**（+3 config / +4 cli / +3 jsonl） |
| 3 | 契约不回归（未在写集内，重点盯） | `python -m pytest tests/test_chat_contract_events.py -q --no-cov` | **10 passed in 1.42s**（含 `finished.context` 五键精确断言、`used_percent > 0`） |
| 4 | 全量 | `python -m pytest -q --no-cov` | **1144 passed, 1 skipped, 1 warning**（92.18s；此前两次 1143 passed 同口径，独立复跑一次见下）。唯一 warning 是既有用例故意喂非法偏好值触发的 |
| 5 | 语法检查 | `python -c "import ast; [ast.parse(...)]"` | `ast ok` × 4（`config.py` / `config_entry.py` / `jsonl_server.py` / `test_jsonl_backend.py`）；`from ai_pr_review.backend.jsonl_server import JsonlBackend` → `import ok` |
| 6 | 独立复跑（只读 subagent，不看我的中间结论） | 上面 1/3/4 三条 + 收集数 + 归位用例的存在性与位置 | 465/10/1143 与我当时的数字逐项一致；5 条归位用例"各出现一次、位置正确、判据与 `git show HEAD:` 的旧版逐字相同" |
| 7 | 预算三来源（手工探针） | `python -c` 逐值调用 `_chat_context_budget_plan()` | 默认 `(8000,'fallback')`；`1200` → `(1200,'config')`；`0`/`"abc"` → `(8000,'fallback')`；文件里 0/-5/"abc"/null/[1200]/300_000 → `(8000,'fallback')`；文件 1200 → `(1200,'config')`；文件 8000 → `(8000,'fallback')`；缺文件 → `(8000,'fallback')`；`context_window=1` → `(1,'model_spec')` |
| 8 | 封顶与例外（手工探针 + 回归用例） | `python -c` | 中转站 200_000/3_000 → 3_000；`max_output=6_000`+预留 12_000 → 6_000；`max_output=64_000` → 16_096；`deepseek-chat`（兜底条目）→ 16_096 不变；本地 ollama → 12_096 不变（R3 预留保住）；**预设模型 + 兜底条目** → 8_192（改用预设值）；**落盘 `null`** → 不抛、退回现状 |
| 9 | 预算随规格（手工探针） | `python -c` | 用户条目 200_000 → `(100000,'model_spec')`；1_048_576 → `(200000,'model_spec')`（上限截断）；8_192 → `(4096,'model_spec')`；只有预设（无用户条目、无目录）→ `(8000,'fallback')` |
| 10 | F1 的端到端复现（评审发现） | `CliRunner` 跑 `config import`（payload 不带 `models`）后再问后端 | 落盘 32_768/4_096，但预算 `(8000,'fallback')`、封顶 8_192——**不是** 16_384/4_096 |

新增/移动用例明细（`grep -c "^def test_"` 函数个数；括号内为 pytest 收集到的 case 数，
含参数化展开）：

```text
tests/test_config.py        44 → 47 个函数（149 collected）  +2 归位 C、+1 新增过滤共用
tests/test_cli.py           87 → 91 个函数（ 93 collected）  +3 归位 D、+1 新增向前兼容导入
tests/test_jsonl_backend.py 195 → 198 个函数（224 collected） -5 归位、+8 新增
                                          （§2 三条 + §4 四条 + 评审回归一条）
```

> 三文件 case 数 456 → 466（+10 = 3 + 4 + 3），与上表逐项一致。

### 5.1 独立评审发现并已修的 6 处

交付前跑了一轮**只读对抗评审**（独立 subagent，目标是把实现和本文档证伪）。它找到 6 处真问题，
全部修完并补了回归用例；下表是"问题 → 触发路径 → 修法"：

| # | 问题 | 触发路径（评审给出的可复现输入） | 修法 |
|---|---|---|---|
| R1 | 自动写入的兜底条目被当成"用户规格" | `config import` 的 payload 不带 `models` → `ensure_default_model_present()` 补 `32_768/4_096`；旧判据是"与预设不同 = 用户写的" → 预算翻到 16_384、封顶砍到 4_096（思考预留全被吃掉） | `_user_written_spec` 先把**兜底那一对**判死（与有没有预设无关）；封顶遇到兜底条目改用预设值。回归用例 `test_chat_spec_never_trusts_auto_written_or_malformed_entries` |
| R2 | 落盘 `null` 让零网络出口抛 `TypeError` | 手改配置写 `max_output: null` → `int(None)`；`config.snapshot` / `model.status` 是 TUI 一启动就调的 | 取值全部经 `_positive_int` 收口，读不出来就当"不可信"（同一条回归用例） |
| R3 | 目录命中时用的还是预设数字 | 目录说 8_192、预设写 1M 的模型 → 预算按 1M 算（24 倍） | 窗口数字改成"谁背书用谁的数字"（§4.3）：目录命中就用目录值 |
| R4 | 越界字面量没被当成"配坏了" | 文件里写 `chat_context_budget: 300000`（加载期已归一化成 8_000）→ 仍按模型规格放大 | `_budget_literal` 用 `config.CHAT_CONTEXT_BUDGET_RANGE` 判区间（`jsonl_server.py:265`） |
| R5 | `context_window = 1` 算出预算 0 | `int(1 × 0.5) = 0` → `used_percent` 除零，整轮 chat 崩 | `max(1, ...)`（`jsonl_server.py:2050`） |
| R6 | 文档两处与代码不符 | §2.4 的"`resolve_model_spec` 永远给得出数字"（落盘非法值不成立）、§4.3 的"目录值不参与"（实际参与判定） | 两处已按代码改写；另补了默认安装的 `/think` 影响（§2.4）与 `declared is None` 防御分支的说明（§4.4） |

评审同时确认（未被证伪）：归位用例与 `git show HEAD:` 的旧版逐字相同、`assistant.finished.context`
之外没有别的精确键集消费者、TUI 无 `budget_source`/`chat_context_budget` 的消费方、
`_chat_max_tokens` 只降不升且绝不改 `ai_client`。

**环境噪声（不是本次改动引起）**：`tests/test_cli.py::test_cli_chat_clear_removes_persisted_session`
在本机会花 21~28s。`faulthandler` 抓到的栈是
`openai.py:409 _chat_sync → urllib.request.urlopen → socket.readinto`，即 CLI chat 启动路径
里的一次**真实 HTTP 请求**被沙箱网络黑洞拖到超时；首跑慢、二跑 0.01s。该文件与 chat 的 CLI
路径（`cli.py` 不经 `jsonl_server`）都不在本次改动范围内，仅记录以免下次误判成回归。

**并发工作树**：收尾时 `git status` 显示 `chat_commands.py`、`tests/test_chat_commands.py`、
`frontend/tui/src/*` 也在改动中（其他 agent 的任务），`jsonl_server.py` 里另有一处与本任务
无关的 `/help` 文案改写。本文只描述本任务动过的部分；行号以交付时的文件为准。

---

## 6. 未决项

1. **契约 v1 的 `context` 少了一个字段**：`budget_source` 只能挂在 `/context` 与
   `config.snapshot` 上（§4.5）。若产品希望它进 `assistant.finished.context`，需要先改
   `docs/chat-contract-verification.md` 与 `tests/test_chat_contract_events.py`（都不在本任务
   写集内），属于契约版本变更而不是后端改动。
2. **预算的会话内依赖性**（§4.3）：没同步过目录的进程按 8_000。彻底确定化需要"把目录值采用
   进规格条目"或"持久化上次采用的窗口"，两者都超出本任务写集（`config.py` 的字段设计 +
   TUI 助手屏）。
3. **`ProviderConfig.from_dict` 仍不过滤未知模型键**（设计 §5 风险 1）：见 §3.3，与
   `config_entry` 的偏好过滤是两条独立的兼容路径。
4. **`config test` 仍不显示规格**（`docs/claude-b2b3-impl.md` §5 第 6 条）：`ModelProviderConfig`
   没有规格字段，属新增功能，本轮未动。
5. **TUI 侧**：`chat_context_budget_source` 目前没有前端消费方（状态栏角标属 TUI 任务）。
6. **封顶只看 `max_output`，没有"思考档位降级"**：`max_output < 思考预留` 时总额度就取
   `max_output`（§2.4），思考可能吃满额度、答案为空。更体贴的做法是自动把档位降到放得下的
   那一档（或干脆不传 `reasoning_effort`），但那会**改写用户显式选择的档位**，需要产品决策
   （以及 `/think` 的反馈文案），本轮不做。
7. **目录与生效值不一致时的取舍只在"预算侧"保守**（§4.3）：封顶侧同样优先目录值，但
   `config.snapshot.model_spec` 展示的仍是生效值（§2.8 的规则），所以用户可能看到
   "规格 1M / 预算按 8k 算"的组合——`needs_verification` 已经在提示这条不一致，暂不加新文案。
