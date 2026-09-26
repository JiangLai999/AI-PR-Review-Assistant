# B2/B3 接线设计：models.dev 接进配置助手 + 规格可配 + 中转站逐项自定义

- 任务：`claude-b2b3-design`（**只出设计，不改源码**）
- 日期：2026-09-26 · 写作基线：`85d5552`（模型目录服务来自 `3a0a694`）
- 上游：[docs/chat-experience-plan.md](chat-experience-plan.md) §B1/B2/B3（第 75-113 行）、[docs/codex-model-catalog.md](codex-model-catalog.md)（服务层已落地）、[docs/model-metadata-sources.md](model-metadata-sources.md)（数据源评估）
- 注意：`chat-experience-plan.md` §5 第 4 条（第 207 行）还写着旧的"手动刷新 + 1 小时 TTL"建议，该条已被同一文件 §B2（第 92-99 行）的修订（commit `8f19247`）**作废**；本设计以 §B2 的修订版为准（不做 TTL）。
- 阅读约定：**【事实】**= 本次只读核查过、带 `文件:行号` 支撑；**【推断】**= 设计判断，实施时需自证。
- **行号会漂**：Python 侧行号对应当前工作树；`frontend/tui/src/app.tsx` 正在被 mimo 并发修改（group C），因此本文对该文件**只用符号锚点**（类型名/函数名/可 `grep` 的代码片段），不给行号 —— 核对期间该文件的行号仍在移动。

---

## 0. 一屏结论

| # | 决定 | 依据 |
|---|---|---|
| 1 | **取数时机**：TUI 配置助手打开时（`config.options`）同步一次 models.dev，进程内一次；失败静默回退，绝不抛错 | 方案 §B2（第 92-99 行）；服务层 `fetch()` 已是进程级缓存 |
| 2 | **取数不许阻塞事件循环**：在 `asyncio.to_thread` 里跑（仓库已有先例），否则 chat 流会被 10s 超时卡住 | 【事实】`jsonl_server.py:1644` 有 `to_thread` 先例；`serve()` 每个请求一个 task，事件循环共享（`3118-3152`） |
| 3 | **读出口三处同键同形**：`config.options.model`（活跃槽 + `slots.remote/local`）、`config.snapshot.model_spec`、`model.status.model_spec` + 顶层 `source`/`needs_verification` | 沿用 `repo_context`/`symbol_locate` 的"三出口同源"惯例（`jsonl_server.py:771-799`、`1273-1276`） |
| 4 | **快照与状态里不能叫 `model`**：TUI 把 `model.status` 的结果整体并进 `runtime`，而 `runtime.model` 是**字符串** —— 用 `model_spec` | 【事实】`frontend/tui/src/app.tsx` 的 `type RuntimeSnapshot` 里 `model?: string`；两处 `setRuntime((current) => ({ ...current, ...(status.result as RuntimeSnapshot) }))` 会把 `model.status` 的所有键铺进 runtime（`grep -nF "setRuntime((current) => ({ ...current, ...(status.result" frontend/tui/src/app.tsx` 可定位） |
| 5 | **写入口**：`config.setup` 新增 4 个可选参数（规格是**槽位属性**，与运行模式分支无关），沿用"缺失/`null`=不动、非法=整单失败" | 与 `_setup_slot`/`repo_context` 同语义（`jsonl_server.py:941-964`、`1112-1121`） |
| 6 | **不猜测**：生效值与目录值不一致 → `needs_verification: true` 并**同时暴露两个数字**，绝不静默覆盖用户值 | 方案 §B2（第 100-103 行） |
| 7 | **custom 中转站不套用官方预设**：目录未命中就是 `source:"unknown"`，规格全由用户逐项填 | 方案 §B3（第 109-113 行） |
| 8 | **`source` 四值口径**（models.dev / cache / builtin / unknown）由 §2.8 的判定算法唯一决定，UI 不自行推导 | 本设计；取值表由任务 prompt 钉死 |

---

## 1. 现状核查（接线点清单）

| # | 关注点 | 位置（文件:行） | 现状【事实】 | 本设计要做的 |
|---|---|---|---|---|
| 1 | 目录服务 | `services/model_catalog.py:110-245` | `fetch/refresh/lookup/reasoning_summary` 齐备；类级进程缓存；失败返回 `None`。**没有**"这次数据是网络拉的还是缓存里的"这一信息 | 增一个只读 `last_load_origin()`（§3.1） |
| 2 | 目录开关 | `config.py:641-643`、`787-791`、`838`、`856` | `preferences.model_catalog_fetch` 默认 `True`，加载时归一化；**服务层不读它**（服务本文档 76-78 行写明） | 由 `jsonl_server` 在取数时读（§3.3.3） |
| 3 | 配置助手选项 | `backend/jsonl_server.py:823-939` | `providers`（`830-843`，**显式排除 `custom`**，`831`）、`local`（`856-899`）、`current`（`900-930`）、`routing`/`repo_context`/`symbol_locate`（`931-938`） | 新增同级 `model` 与 `custom_endpoint` 两块 |
| 4 | 配置助手写 | `jsonl_server.py:966-1138` | cloud 分支 `974-1029`（`provider_name="custom"` 已可用，`991` 允许无 Key）、local 分支 `1030-1054`、custom **路由**档 `1056-1068`、偏好逐项 `1083-1130`、`save`+重载 `1132-1138` | 保存前插一个与 profile 无关的规格写入步（§3.3.8） |
| 5 | 协议出口 | `jsonl_server.py:2586-2600` | `config.snapshot`/`config.options`/`config.setup` 三个分支 | `config.options` 分支加一次 `await self._ensure_model_catalog()` |
| 6 | 快照 | `jsonl_server.py:719-760` | 活跃槽 + `routing`（`759`） | 加 `model_spec` |
| 7 | 模型状态 | `jsonl_server.py:1255-1293` | `provider/model/base_url/available/models/routing/repo_context/symbol_locate` | 加 `model_spec` + 顶层 `source`/`needs_verification`；**禁止**在此触发网络 |
| 8 | 状态文案 | `jsonl_server.py:1295-1320` | 读 `status.get("model")` 当**模型名**打印（`1305`） | 不改；正因为这两处，规格块不能占用 `model` 键（§0 第 4 条） |
| 9 | 预设规格 | `config.py:355-429`（表；`344-352` 是构造它的 `_build_models`） | `PROVIDER_MODEL_PRESETS` 只有 `("name", context, output)`；`custom` 只有 `custom-model` 一条（`428`） | 规格的"内置"来源就是它 |
| 10 | 规格条目 | `config.py:489-495`、`551-557` | `ProviderModelConfig(name, context_window=32768, max_output=4096)`；`ensure_default_model_present` 会**凭空造**默认条目 | 写入目标；未知模型因此永远"有数字"，需要 `source:"unknown"` 兜底 |
| 11 | 未知模型的假规格 | `config.py:515-535`（`522-525`） | `from_model_provider` 对新模型写死 `32_768/4_096` | B3 的痛点：中转站模型名必被写死；改为可覆盖（§3.2/§3.3.8） |
| 12 | 加载兼容 | `config.py:1262-1274`、`1285-1289`、`1306-1312` | `PreferencesConfig`/`AIClientConfig` 走 `_filter_dataclass_payload`；**`ProviderConfig.from_dict`（`537-549`）不过滤 `models[].*`** | 本设计不新增 `ProviderModelConfig` 字段（否则新→旧降级会崩，§5） |
| 13 | CLI 向导 | `cli.py:859-921` | `_prompt_provider_model` **已经在问**上下文/最大输出（`909-918`）；`config_wizard.py:51` 把 `models` 整体替换为 `{selected_model.name: selected_model}`（只留一个模型） | CLI 本轮不加网络请求；只把"目录默认值"列为后续（§6.4） |
| 14 | CLI 只读出口 | `config_commands.py:31-45`、`provider_diagnostics.py:18-41` | `config health` 的 payload（`build_provider_health_payload`）不含规格；**`config test` 不是 JSON 出口**：`run_config_test`（`config_commands.py:17-28`）返回 `{"provider": ModelProviderConfig, "output_format", "risk_warning"}`，cli 只打印一行文本（`cli.py:3262-3268`），而 `ModelProviderConfig`（`config.py:432-443`）根本没有规格字段 | 只给 `config health` 增 `context_window`/`max_output`/`spec_source`/`needs_verification`（§3.4）；`config test` 明确**不在**本轮范围 |
| 15 | CLI 导入导出 | `config_entry.py:27-37`、`86-132`；`cli.py:1319-1335` | `provider.to_dict()`（`config.py:575-580`）**已经**带 `models[].context_window/max_output`；`config_entry.py:119` 的 `PreferencesConfig(**payload)` **不过滤** | 只加回归测试（§4.1-D）；`119` 的过滤缺失记为风险（§5） |
| 16 | TUI 助手取数点 | `app.tsx` 两处 `onMount` 里的 `props.backend.request("config.options", …)`（`grep -c` 得 2 处） | 两个助手屏各调一次 `config.options`；超时预算 `const PROBE_TIMEOUT_MS = 30_000` | 后端一次 fetch（10s）落在 30s 预算内，安全（§5） |

---

## 2. 契约

### 2.1 取数（唯一时机 + 缓存）

```text
TUI 打开配置助手 → config.options
   ├─ preferences.model_catalog_fetch == False → 不请求；catalog.source="builtin"、reason="disabled"
   ├─ await asyncio.to_thread(ModelCatalog.fetch)        # 不带 refresh
   │     ├─ 冷进程：真发一次 HTTPS（超时 10s，model_catalog.py:18）→ origin="network"
   │     ├─ 进程内已有目录：不发请求 → origin="cache"
   │     └─ 失败/超时/形状错误 → None；catalog.source="builtin"、reason="fetch_failed"；不抛错
   └─ 结果记进 backend 实例的 self._catalog_state（一个进程只定档一次）
```

- **进程内只拉一次**：`ModelCatalog` 的类级缓存已经保证（`model_catalog.py:110-145`），backend 再 memo 一次 `_catalog_state`，保证同一个助手里两次 `config.options` **不会**把 `source` 从 `models.dev` 翻成 `cache`。
- **不拉的路径**：`config.snapshot`、`model.status`、chat、review、`/model` 切换。它们只读 `self._catalog_state`（可能为 `None` → 按 `builtin` 渲染）。方案 §B2 验收"三次 chat 调用不触发任何拉取"由这条保证。
- **手动重试（可选）**：新协议方法 `config.catalog.refresh` → `await asyncio.to_thread(catalog.refresh)` 后重建 `_catalog_state`，返回新的 `config.options.model`；对应方案里的"重新获取"按钮（第 99 行）。本轮可只落地方法，不做按钮。

### 2.2 `config.options.model`（新键，与 `routing`/`repo_context` 同级）

顶层四键就是契约要求的 `source`/`context_window`/`max_output`/`reasoning`（描述**活跃槽**，与 `current` 的约定一致，`jsonl_server.py:900-930`）；每槽明细在 `slots`（"模型规格"屏每槽一次，方案 §B1 第 78 行）。

```jsonc
"model": {
  "provider": "deepseek",
  "model": "deepseek-flash",
  "source": "models.dev",              // models.dev | cache | builtin | unknown
  "context_window": 1000000,           // 生效值（= 落盘值；落盘缺失时是预设/默认）
  "max_output": 393216,
  "reasoning": "档位 low/high/max · 开关",   // 摘要串；目录无该模型时为 null
  "reasoning_controls": [{"kind": "effort", "values": ["low","high","max"], "min": null}],
  "needs_verification": false,
  "endpoint_matches_preset": true,     // 见 §2.8：false 时必然 needs_verification
  "catalog": {                          // 目录命中才有；未命中/离线为 null
    "context_window": 1000000,
    "max_output": 393216,
    "source": "models.dev",             // models.dev | cache
    "fetched_at": "2026-09-26T09:12:33+00:00"
  },
  "preset": {"context_window": 1048576, "max_output": 384000},   // 内置预设；无预设为 null
  "bounds": {"context_window": [1024, 10000000], "max_output": [1, 10000000]},
  "catalog_state": {"enabled": true, "source": "models.dev", "reason": "", "fetched_at": "..."},
  "slots": {
    "remote": { /* 与上面同形，去掉 slots */ },
    "local":  { /* 与上面同形，去掉 slots */ }
  }
}
```

### 2.3 `model.status`（加法式）

新增：

```jsonc
"model_spec": { /* = config.options.model（活跃槽那一份，含 catalog/preset/bounds） */ },
"source": "models.dev",        // = model_spec.source，供状态栏一行读取
"needs_verification": false
```

**硬约束**：不能叫 `model`。`model.status` 的结果会被 TUI 整体 spread 进 runtime 快照（`app.tsx` 里两处 `setRuntime((current) => ({ ...current, ...(status.result as RuntimeSnapshot) }))`），而后端 `model.status.model` 是模型名字符串（`jsonl_server.py:1266`），TUI 的 `RuntimeSnapshot.model?: string` 也被当字符串读（状态栏、`/model` 提示等）；占用该键会把状态栏的模型名换成对象。同理 `config.snapshot` 用 `model_spec`（TUI 读 `snapshot.model ?? "model"` 当字符串）。

### 2.4 `config.snapshot`

新增 `"model_spec": self._active_spec_block()`（活跃槽，轻量同形，不为快照做网络请求）。`config.options.model` 与 `model.status.model_spec` 用**同一个 builder**，保证三出口同键同形。

### 2.5 `config.setup` 写契约（4 个新参数，全部可选）

| 参数 | 目标 | 语义 |
|---|---|---|
| `context_window` | **远端槽**（`config.provider`）当前 `default_model` 的条目 | 整数；缺失/`null` = 保持落盘值 |
| `max_output` | 同上 | 整数；缺失/`null` = 保持落盘值 |
| `local_context_window` | **本地槽**（`_local_slot_config()`，`jsonl_server.py:1169-1177`）当前 `default_model` | 同上 |
| `local_max_output` | 同上 | 同上 |

- **槽位作用域**：与 `model_name`（远端）/`local_model`（本地）的既有划分一致（`jsonl_server.py:1003-1017`、`1037-1044`）。
- **与运行模式分支无关**：写在所有 profile 分支**之后**、`_sync_runtime_sections()`（`1132`）之前，这样 `runtime_profile="custom"`（只写槽位路由的档）也能改规格 —— 否则参数会被分支静默吞掉。
- **校验在赋值之前，非法整单失败**（`ConfigValidationError`，中文 + `（field accepts ...）`）：

  | 规则 | 文案（含 `模型规格` 四字，便于 TUI 路由回该屏） |
  |---|---|
  | 必须是整数（bool 拒绝；`"1000000"` 数字串接受；`1e6` 拒绝） | `模型规格的上下文长度需为整数。（context_window accepts an integer.）` |
  | 闭区间 `[1024, 10_000_000]` / `[1, 10_000_000]` | `模型规格的上下文长度需在 1024–10000000 之间。（context_window accepts 1024..10000000.）` |
  | `max_output <= context_window`（用"本次提交后的两个值"比较） | `模型规格的最大输出不能大于上下文长度。（max_output must not exceed context_window.）` |

- **写入位置**：`ProviderConfig.models[model_name]`（不存在则新建条目）。这样 chat/review 读到的仍是同一份数据结构（`ProviderModelConfig`），不需要新的持久化路径。
- **重新选择模型时**：`_apply_slot_model`（`1149-1163`）保持现状（新模型走 `ensure_default_model_present`，即 32768/4096）；不在 `/model` 路径上拉目录（方案：状态/高频路径不拉）。目录值只在**助手**里作为默认值/对照出现。
- **两个槽指向同一对象/同一模型**（主 Provider 就是 Ollama，`_local_slot_config` 会返回 `config.provider`）且两组参数都给了**不同**值 → 报错：`模型规格：同一个 Provider 的两个槽指向同一模型，只需填一处。（Both slots use the same provider/model; specify the spec once.）`；只给一组则照常写入。

### 2.6 `config.options.custom_endpoint`（B3 中转站的读出口）

`providers[]` 继续排除 `custom`（`jsonl_server.py:831`，理由是预设里 `base_url` 为空、没有可选项语义），中转站单独一块，供 TUI 预填它自己的那一屏：

```jsonc
"custom_endpoint": {
  "name": "custom",
  "display_name": "Custom Endpoint",
  "base_url": "https://relay.example.com/v1",
  "api_format": "openai",
  "default_model": "relay-model",
  "api_key_configured": true,
  "models": ["relay-model"],
  "context_window": 200000,
  "max_output": 16384,
  "source": "unknown",          // 目录无 custom/relay-model → 如实标注
  "needs_verification": false   // 没有可比对的官方数据，就不假称需要核对
}
```

写路径复用 §2.5 的参数 + `_apply_setup` 已有字段（`provider_name:"custom"`、`api_key`、`model_name`、`base_url`、`api_format`，`jsonl_server.py:974-1017`）：**中转站不需要新参数**，缺的只是"规格别被写死"（§3.2）与"读出口"（本块）。

### 2.7 `reasoning` 摘要串

`ModelCatalog.reasoning_summary()`（`model_catalog.py:235-245`）已把 models.dev 的三种形状收敛成 `{"supported", "controls"}`。摘要串由后端按 `preferences.ui_language` 生成（双语表，沿用 `REVIEW_ROUTING_REASONS` 的写法，`jsonl_server.py:96-112`）：

| controls | zh-CN | en-US |
|---|---|---|
| `toggle` | `开关` | `toggle` |
| `effort` + values | `档位 low/high/max` | `effort low/high/max` |
| `budget_tokens` + min | `预算 ≥1024` | `budget ≥1024` |
| 多条 | ` · ` 连接，顺序 = controls 顺序 | 同 |
| 目录无该模型 | `null`（**不是**"未声明"：离线时我们并不知道） | 同 |

### 2.8 `source` / `needs_verification` 判定算法（唯一事实来源）

```python
def resolve(slot_provider, model_name):
    stored  = slot_provider.models.get(model_name)                       # 生效值（config.py:551-557 保证存在）
    preset  = PROVIDER_MODEL_PRESETS.get(slot_provider.name.lower(), {}).get(model_name)
    spec    = catalog.lookup(slot_provider.name, model_name) if catalog_state else None
    catalog_source = "models.dev" if catalog_state.origin == "network" else "cache"

    # 生效值：落盘条目优先；没有条目时用预设；再没有就是 ProviderModelConfig 的默认值（config.py:494-495）。
    context_window = (stored.context_window if stored is not None
                      else preset["context_window"] if preset is not None else 32_768)
    max_output     = (stored.max_output if stored is not None
                      else preset["max_output"] if preset is not None else 4_096)

    if spec is None or (spec.context_window is None and spec.max_output is None):
        source = "unknown" if preset is None else "builtin"
        needs_verification = False          # 没有可比对的远端数据 → 不假称"需要核对"
    elif agree(stored, spec):               # 双方都非 None 的字段全部相等
        source = catalog_source             # models.dev | cache
        needs_verification = not endpoint_matches_preset(slot_provider)
    else:
        source = "builtin"                  # 生效值来自本地（预设或用户填），与目录不一致
        needs_verification = True

    catalog_block = None if spec is None else {…spec 的原值 + source=catalog_source + fetched_at…}
```

配套硬规则：

1. **永不覆盖**：`context_window`/`max_output` 永远是**落盘值**；目录值只出现在 `catalog.*`，UI 自己决定要不要"采用目录值"。打开助手不写盘。
2. **端点不一致要标**：`endpoint_matches_preset = bool(preset_base_url) and slot_provider.base_url == preset_base_url`，其中 `preset_base_url = MODEL_PROVIDER_PRESETS.get(provider, {}).get("base_url", "")`（`.get` 而非下标：未知 provider 没有预设）。为 `false` 时（中转/自建代理套用了官方 provider 名）即使数字与目录一致也置 `needs_verification=True` —— models.dev **不区分端点**（`docs/model-metadata-sources.md:76-77`）；预设 `base_url` 为空（`custom`，`config.py:336`）视为"无官方端点可比"，不因此置位。
3. **官方预设只对"预设里真有这一条"的模型生效**。`custom` 只有字面量 `custom-model`（`config.py:428`），所以中转站的自定义模型名必然落到 `unknown`，不会套用任何官方数字。
4. **不做跨供应商的模型名猜测**：`Lookup` 只在 `(provider, model)` 内做大小写/空格容错（`model_catalog.py:71-79`、`211-217`）。`siliconflow` 的 `deepseek-ai/DeepSeek-V3` 与 models.dev 的 `deepseek/deepseek-v3` 是两条不同记录，**不互相映射**；需要对齐时由用户显式填规格。

---

## 3. 逐文件接线点

### 3.1 `src/ai_pr_review/services/model_catalog.py`（加法，1 个类方法）

- `_load()`（`138-145`）里记来源：命中 `ModelCatalog._cache` → `'cache'`；`_fetch_from_source()` 成功 → `'network'`；失败/异常 → `None`。
- 新增类级字段 `_cache_origin: str | None = None`（与 `_cache`/`_cache_failed` 同处，`110-118`），`reset_cache()`（`120-124`）一并清零。
- 新增只读 API：

```python
@classmethod
def last_load_origin(cls) -> str | None:
    """上一次 _load() 的数据来源：'network' | 'cache' | None（没有可用目录）。"""
```

- **不改**任何既有签名与返回类型；`tests/test_model_catalog.py` 现有 13 个用例必须原样通过。

### 3.2 `src/ai_pr_review/config.py`（加法 + 1 处硬编码改为可覆盖）

1. **常量**（放 `644-647` 的 `*_RANGE` 旁边）：

```python
CONTEXT_WINDOW_RANGE: tuple[int, int] = (1_024, 10_000_000)
MAX_OUTPUT_RANGE: tuple[int, int] = (1, 10_000_000)
```

   若实施者写集不含 `config.py`：把这两个常量改放在 `jsonl_server.py`（`SYMBOL_LOCATE_TRUE_VALUES` 附近，`146-151`）并在 `tests/test_jsonl_backend.py` 加一条"与 config 层同值"的钉住用例（先例：`test_symbol_locate_vocabulary_matches_the_config_layer`，`3692`）。

2. **`ProviderConfig.set_model_spec()`（新增实例方法，放 `551-557` 附近）**：

```python
def set_model_spec(self, model_name: str, *, context_window: int | None = None,
                   max_output: int | None = None) -> bool:
    """把向导提交的规格写到该模型的条目上；两个参数都是 None 时不动任何东西。"""
```

   语义：`ensure_default_model_present()` → 取/建 `models[model_name]` → 只覆盖非 `None` 的字段 → 返回是否发生写入。**不**改 `default_model`，**不**碰其它模型条目。

3. **`from_model_provider`（`515-535`）**：保持默认行为（预设值），但**允许调用方覆盖**：新增可选参数 `spec_overrides: dict[str, dict[str, int]] | None = None`，在 `from_model_provider` 末尾按 key 覆盖（解决 `522-525` 写死 `32_768/4_096`）。这是 B3 的核心：中转站模型不再是死数字。不传参数 = 与今天逐字节一致。

4. **不加** `ProviderModelConfig` 字段（`489-495`）。理由见 §5 第 1 条：`from_dict`（`537-549`）对 `models[].*` 不做过滤，加字段会让"新版本写的配置在旧版本上加载崩溃"。

### 3.3 `src/ai_pr_review/backend/jsonl_server.py`（主体）

#### 3.3.1 新常量（与 `REPO_CONTEXT_LABELS`/`SYMBOL_LOCATE_CHOICES` 同区，`135-151`）

```python
# 模型规格的来源标注（B2）：取值由 §2.8 的判定算法唯一决定，TUI 只渲染不推导。
MODEL_SPEC_SOURCES = frozenset({"models.dev", "cache", "builtin", "unknown"})
# 目录级来源（config.options.model.catalog_state.source）只可能是这三个。
CATALOG_SOURCES = frozenset({"models.dev", "cache", "builtin"})
# reasoning 摘要串的双语表（沿用 REVIEW_ROUTING_REASONS:96-112 的写法）。
REASONING_KIND_LABELS: dict[str, dict[str, str]] = {
    "toggle": {"zh-CN": "开关", "en-US": "toggle"},
    "effort": {"zh-CN": "档位", "en-US": "effort"},
    "budget_tokens": {"zh-CN": "预算", "en-US": "budget"},
}
```

#### 3.3.2 构造与状态

- `JsonlBackend.__init__`（`586-603`）新增关键字参数 `model_catalog: ModelCatalog | None = None`（默认 `ModelCatalog()`，测试可注入假目录，避免联网），并初始化：

```python
self._model_catalog = model_catalog or ModelCatalog()
self._catalog_state: _CatalogState | None = None   # 进程内定档一次，见 §2.1
```

#### 3.3.3 取数（唯一网络点）

```python
async def _ensure_model_catalog(self) -> None:
    """配置助手打开时同步一次 models.dev（方案 §B2）；进程内一次，失败静默降级。"""
    if self._catalog_state is not None:
        return
    if not bool(getattr(self.config.preferences, "model_catalog_fetch", True)):
        self._catalog_state = _CatalogState.disabled()
        return
    index = await asyncio.to_thread(self._model_catalog.fetch)   # 不阻塞 chat 流（先例 1644）
    self._catalog_state = _CatalogState.from_fetch(
        index, origin=ModelCatalog.last_load_origin()
    )
```

`_CatalogState` 是一个小 frozen dataclass（放 `jsonl_server.py` 模块级，`_routing_snapshot` 上方）：`index`、`source`（`models.dev|cache|builtin`）、`reason`（`""|"disabled"|"fetch_failed"`）、`fetched_at`、`lookup(provider, model)`。

#### 3.3.4 三个 builder（唯一真源）

```python
def _slot_spec_block(self, slot: str) -> dict[str, Any]:   # §2.8 的算法
def _active_slot_name(self) -> str:                        # 用 _active_provider_config() 的 is 比较，config.py:1157-1174
def _model_spec_options(self) -> dict[str, Any]:           # §2.2 的 model 块（活跃槽 + slots）
def _custom_endpoint_options(self) -> dict[str, Any]:      # §2.6
def _reasoning_text(self, controls: list[dict]) -> str | None
```

插入位置：紧跟 `_symbol_locate_options`（`786-799`）之后、`_coerce_symbol_locate`（`801-821`）之前，与其它 `*_options()` 同区。

#### 3.3.5 `_setup_options()` 插入点（`931-938` 之后）

```python
            # 模型规格（B1/B2/B3）：与 routing/repo_context 同级；三出口同一个 builder，
            # 保证 config.options / config.snapshot / model.status 三份同键同形。
            "model": self._model_spec_options(),
            # 中转站（B3）：custom 不在 providers 列表里（831 行），单独一块给 TUI 预填。
            "custom_endpoint": self._custom_endpoint_options(),
```

#### 3.3.6 `_config_snapshot()` 插入点（`759` 的 `routing` 之后）

```python
            # 模型规格来源（B2）。只读 self._catalog_state，绝不触发网络。
            # 键名必须是 model_spec 而不是 model：TUI 的 runtime.model 是字符串（app.tsx 的 RuntimeSnapshot.model）。
            "model_spec": self._active_spec_block(),
```

#### 3.3.7 `_model_status()` 插入点（`1276` 的 `symbol_locate` 之后）

```python
            "model_spec": spec,
            "source": spec["source"],                    # 任务契约要求的两个顶层字段
            "needs_verification": spec["needs_verification"],
```

（`spec = self._active_spec_block()` 在 `status` 字典**之前**算好，只算一次。）
`_model_status_text`（`1295-1320`）**不改**：它继续用 `status["model"]`（字符串模型名）。

#### 3.3.8 `_apply_setup()` 写路径（`1132` 之前插入）

```python
        # B1/B3：模型规格是**槽位属性**，与运行模式分支无关（custom 路由档也要能改），
        # 因此放在所有分支之后、保存之前统一应用；校验失败整单报错、一个字段都不写。
        self._apply_model_spec_params(params)
```

新增三个私有方法（放 `_setup_slot`（`941-964`）附近）：

```python
def _coerce_spec_int(self, params, key, *, label, bounds) -> int | None   # 缺失/None→None；非法→ConfigValidationError
def _apply_slot_spec(self, target, params, context_key, output_key) -> None
def _apply_model_spec_params(self, params) -> None
    # remote: self.config.provider        keys ("context_window", "max_output")
    # local:  self._local_slot_config()   keys ("local_context_window", "local_max_output")
    # 先 remote 后 local；两目标同对象且同 default_model 且两组值不同 → 报错（§2.5）
```

写入用 `config.py` 的 `ProviderConfig.set_model_spec()`（§3.2）；**顺序**：解析模型名（`1003-1007`/`1037-1039`）→ 写规格（本步）→ `_sync_runtime_sections()`（`1132`）→ `save`（`1133`）→ `AppConfig.load` 重载（`1136`）。重载会重建 provider 对象，所以规格**必须**在 save 之前写（既有坑：`config.save` 重建 provider）。

#### 3.3.9 协议分发（`2592-2593`）

```python
            elif method == "config.options":
                # 打开配置助手 = 同步一次模型目录（方案 §B2）。失败静默，绝不挡配置流程。
                await self._ensure_model_catalog()
                result(self._setup_options())
```

（可选）`config.catalog.refresh` 分支紧随其后，返回 `{"model": self._model_spec_options()}`。

### 3.4 `provider_diagnostics.py` / `config_diagnostics.py`

`build_provider_health_payload`（`provider_diagnostics.py:18-41`）在 `payload` 里补 4 个键（加法）：

```python
    payload["context_window"] = spec["context_window"]
    payload["max_output"] = spec["max_output"]
    payload["spec_source"] = spec["source"]                     # models.dev|cache|builtin|unknown
    payload["needs_verification"] = spec["needs_verification"]
```

- 数据来源：函数内用 `config._active_provider_config()` + `PROVIDER_MODEL_PRESETS` 现算（**不联网**，目录不可用时 `spec_source="builtin"`；`custom` 未知模型 `"unknown"`）。为免两处实现漂移，建议把 §2.8 的纯函数版判定抽到 `config.py`（`resolve_model_spec(provider_config, model_name, catalog=None)`）供 `jsonl_server` 与 `provider_diagnostics` 共用；若 `config.py` 不在写集，则在本文件实现并在 `tests/test_jsonl_backend.py` 加一条"两处同值"的钉住用例。
- `config_diagnostics.build_health_check_output`（`36-68`）透传即可，`--discover-models`/`--probe` 语义不变。
- **`config test` 不在此列**：它的 payload 是 `{"provider": ModelProviderConfig, "output_format", "risk_warning"}`（`config_commands.py:17-28`），而 `ModelProviderConfig`（`config.py:432-443`）不带规格字段；要让它显示规格，属于**新增功能**（改 `run_config_test` + `cli.py:3262-3268` 的输出行），不是本轮"接线"。

### 3.5 `config_entry.py` / `config_commands.py` / `config_wizard.py`（只加测试，原则上不改代码）

【事实】三者已经覆盖规格的持久化与展示：`config_entry.run_config_import:114` 走 `ProviderConfig.from_dict`（含 models）、`_export_config_payload`（`cli.py:1319-1335`）走 `provider.to_dict()`（含 `models[].context_window/max_output`）、`config_wizard.apply_wizard_configuration:51` 落 `models={selected_model.name: selected_model}`。因此：

- **不改代码**，只补回归测试（§4.1-D），证明中转站规格能导入/导出/回显。
- 已知不一致（**记录，不在本设计修**）：CLI 向导只保留选中模型（`config_wizard.py:51`），TUI/协议路径保留整份预设表（`config.py:517-535`）。
- 新发现模型会落 `32_768/4_096`，但来源不是 `ensure_default_model_present`：`run_config_models`（`config_commands.py:61-79`）只是转调 `resolve_model_discovery`（`config_diagnostics.py:71-100`），真正造条目的是回调 `_set_active_model`（`cli.py:1834-1862`，`slot.models[model_name] = ProviderModelConfig(name=model_name)` 走 dataclass 默认值 `config.py:494-495`），落盘时还会经 `from_model_provider` 的写死分支（`config.py:521-525`）。"用目录补默认值"列为后续（§6.4）。

### 3.6 前端（mimo 的活，本设计只定契约）

1. `SetupOptions`（`app.tsx` 的 `type SetupOptions`）加可选 `model?: ModelSpecOptions`、`custom_endpoint?: CustomEndpointOptions`；`RuntimeSnapshot`（`type RuntimeSnapshot`）加 `model_spec?: ModelSpecBlock` + `source?: string`。
2. 新屏「模型规格」（每个被使用的槽一次）：两个整数字段，默认值 = `model.slots.<slot>.context_window/max_output`；当 `catalog` 非空且与生效值不同，显示 `目录值 …` + 「采用目录值」按钮；`needs_verification` 时显示 `⚠ 与 models.dev 不一致，未自动采用` 与实测入口提示（`python scripts/probe_model_reasoning.py --provider X --model Y`）。
3. 提交时把这些字段并进 `config.setup` 载荷（`apply()` 里的 `const payload: Record<string, unknown> = {…}`）。
4. 错误路由（`apply()` 的 `catch` 链）：后端规格错误文案统一含「模型规格」，前端加一条 `message.includes("模型规格") → goTo("model_spec")`，且必须排在泛化的 `else if (!isCustom() && message.includes("模型"))` **之前**（否则永远不可达——"模型规格"也含"模型"）。
5. 状态栏：`source != "models.dev"` 时在模型名后加来源角标（`内置`/`缓存`），`needs_verification` 时加 `⚠`。

---

## 4. 测试与验证

### 4.1 测试清单（文件 :: 用例名 → 判据）

**A. `tests/test_model_catalog.py`（追加 2 条；13 条旧的必须原样绿）**

| 用例 | 判据 |
|---|---|
| `test_last_load_origin_reports_network_then_cache` | 首次 `fetch()` 后 `last_load_origin()=="network"`；再次 `fetch()`（不 refresh）后 `"cache"`；`refresh()` 后回 `"network"` |
| `test_failed_fetch_keeps_origin_none` | `install_failure` 后 `fetch() is None` 且 `last_load_origin() is None`（不谎报来源） |

**B. `tests/test_jsonl_backend.py`（追加 15 条，全部离线）**

前置设施（必须先落，否则会真联网）：
- autouse fixture `_offline_model_catalog(monkeypatch)`：把 `ModelCatalog._fetch_from_source` 打桩为 `None` + `reset_cache()`。**不是可选项**：取数点落在 `config.options` 的协议分支后，现有 3 个协议级用例会经过它 —— `test_config_and_model_snapshots_carry_routing`（`tests/test_jsonl_backend.py:3349`）、`test_protocol_config_options_and_setup_carry_symbol_locate`（`3641`）、`test_protocol_config_options_and_setup_carry_repo_context`（`3849`）；另外 9 个直接调 `_setup_options()` 的用例不受影响（也正因此取数点**必须**放协议分支，不能塞进 `_setup_options()`）。
- helper `_stub_catalog(monkeypatch, payload)`：复用 `tests/test_model_catalog.py:16-49` 的 payload 形状（deepseek `deepseek-flash` = 1_000_000/393_216 + effort low/high/max + toggle），或直接 `JsonlBackend(..., model_catalog=FakeCatalog(...))` 注入。

| 用例 | 判据 |
|---|---|
| `test_config_options_fetches_the_catalog_once_per_process` | 计数打桩：连续两次 `handle(config.options)` → fetch 调用数 == 1；两次 `model.catalog_state.source` 都是 `"models.dev"`（不在助手里翻转） |
| `test_config_options_falls_back_to_builtin_when_the_catalog_fails` | 失败时 `ok is True`、`model.catalog_state.source=="builtin"`、`reason=="fetch_failed"`、`model.remote.source=="builtin"` |
| `test_config_options_respects_model_catalog_fetch_off` | `preferences.model_catalog_fetch=False` → fetch 计数 0、`reason=="disabled"` |
| `test_model_spec_block_marks_a_user_override_without_overwriting_it` | 目录 1_000_000/393_216，落盘改 128_000/8_192 → `context_window==128_000`、`catalog.context_window==1_000_000`、`needs_verification is True` |
| `test_model_spec_block_matches_the_catalog_when_values_agree` | 落盘 == 目录 → `source=="models.dev"`、`needs_verification is False`、`reasoning=="档位 low/high/max · 开关"` |
| `test_custom_endpoint_specs_never_take_official_presets` | `provider_name="custom"` + `model_name="relay-model"` + 规格 200_000/16_384 → `config.provider.models["relay-model"]` 是这两个数（**不是** 32_768/4_096）；`model.remote.source=="unknown"`、`preset is None` |
| `test_config_setup_persists_specs_and_all_exits_read_them_back` | 提交 `context_window`/`max_output` → `config.options.model`、`config.snapshot.model_spec`、`model.status.model_spec` 三处同值（同键同形） |
| `test_config_setup_spec_params_are_partial_updates` | 只给 `local_max_output` → 本地该模型变、远端不动；给 `context_window=null` → 保持落盘值 |
| `test_config_setup_rejects_an_invalid_spec_and_writes_nothing` | 越界 / `True` / `max_output > context_window` → `ok is False`、文案含「模型规格」；落盘文件字节不变、内存值不变 |
| `test_config_setup_applies_specs_in_the_custom_routing_profile` | `runtime_profile="custom"`（只写槽位路由的档）时规格参数仍落盘（不被 profile 分支吞掉） |
| `test_model_status_spec_key_does_not_shadow_the_model_name` | `status["model"] == provider.model_name`（字符串）、`status["model_spec"]` 是对象、`status["source"]`/`["needs_verification"]` 与块内一致 |
| `test_model_status_and_config_snapshot_never_fetch_the_catalog` | 只调 `model.status` / `config.snapshot` → fetch 计数 0 |
| `test_reasoning_summary_text_follows_the_ui_language` | zh-CN 与 en-US 各一条断言；目录缺该模型 → `reasoning is None` |
| `test_catalog_fetch_does_not_block_the_event_loop` | 打桩 fetch 睡 0.3s；同时跑一个每 10ms 自增的后台 task → config.options 返回时计数 ≥ 3（to_thread 生效；余量放宽，不卡 CI） |
| `test_protocol_config_options_and_setup_carry_model_specs` | 协议层 round trip：`config.options.model` 存在、`custom_endpoint` 存在，且既有键（`repo_context`/`symbol_locate`/`routing`/`current`）一个都没少 |

**C. `tests/test_config.py`（追加 2 条）**

| 用例 | 判据 |
|---|---|
| `test_set_model_spec_touches_only_the_target_model` | 只改目标条目；其它模型与 `default_model` 不变；两个参数都 `None` 时返回 False 且无写入 |
| `test_model_spec_bounds_are_sane` | `CONTEXT_WINDOW_RANGE == (1024, 10_000_000)`、`MAX_OUTPUT_RANGE == (1, 10_000_000)`（若常量落地在 `config.py`；落地在 `jsonl_server` 时改断言两处同值） |

**D. `tests/test_cli.py`（追加 3 条：前 2 条是回归性质，不改产品代码；第 3 条依赖 §3.4 的 health payload 改动）**

| 用例 | 判据 |
|---|---|
| `test_config_show_and_export_keep_model_specs` | `config show`（脱敏）与 `config export` 的 `provider.models[name]` 带 `context_window`/`max_output` |
| `test_config_import_round_trips_a_relay_spec` | 导入含 `relay-model` 200_000/16_384 的 payload → 落盘同值 |
| `test_config_health_reports_the_effective_spec_and_source` | `config health` 的 JSON 输出（`build_provider_health_payload`，§3.4）含 `context_window`/`max_output`/`spec_source`/`needs_verification`；不联网时：模型在预设表里（如 `deepseek-flash`）→ `spec_source=="builtin"`，不在预设表里（既有 `test_cli.py:946` 用的 `deepseek-chat`）→ `"unknown"`。**注意**：`config test` 不是 JSON 出口（`config_commands.py:17-28`），本轮不改它 |

### 4.2 每个接线点的验证方法（命令 + 期望输出）

> PowerShell；先建临时目录并把 `TEMP/TMP` 指过去（本仓库既有做法）。

```powershell
New-Item -ItemType Directory -Force -Path .pytest_claude
$env:TEMP = "C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_claude"
$env:TMP  = $env:TEMP
```

| # | 验证对象 | 命令 | 期望 |
|---|---|---|---|
| 1 | 服务层来源标注（§3.1） | `python -m pytest tests/test_model_catalog.py -q --no-cov -k origin` | `2 passed`；整文件 `15 passed`（13 旧 + 2 新） |
| 2 | 规格块与判定（§3.3.4-3.3.7） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k "model_spec or catalog"` | 新增用例全 passed；无 `Skipped`；运行时间 < 5s（全部离线） |
| 3 | 写路径（§3.3.8） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k "config_setup and spec"` | `4 passed`（持久化 / 部分更新 / 非法不写 / custom 路由档） |
| 4 | CLI 出口（§3.4） | `python -m pytest tests/test_cli.py -q --no-cov -k "spec or health or export"` | 新旧用例全 passed |
| 5 | 全量回归 | `python -m pytest -q --no-cov` | `>= 1049 passed / 1 skipped`（**实测基线**：2026-09-26 本设计任务在 `.pytest_claude` 下运行 = `1049 passed, 1 skipped in 91.88s`；实施后总数只增不减） |
| 6 | 断网手工验证（§2.1 降级） | `$env:AI_PR_REVIEW_CONFIG="$PWD\.pytest_claude\cfg.json"; '{"id":"1","method":"config.options","params":{}}' \| python -m ai_pr_review.backend.jsonl_server` | 单行 JSON：`"ok":true`；`model.catalog_state.source=="builtin"`、`reason=="fetch_failed"`；进程在 ~10s 内退出，**无 traceback** |
| 7 | 联网手工验证（§2.2 命中） | 同上，但网络可用 | `model.remote.source=="models.dev"`；provider 换成 `deepseek` 时 `context_window==1000000`、`max_output==393216`、`reasoning` 非空 |
| 8 | 状态/快照出口不拉取（方案 §B2 验收"三次 chat 调用不触发任何拉取"） | `python -m pytest tests/test_jsonl_backend.py -q --no-cov -k never_fetch` | `1 passed`：该用例在同一进程里先调 `model.status`/`config.snapshot`、再跑 3 次 chat 请求，断言目录 fetch 计数 == 0 |

---

## 5. 风险与兼容性

| # | 风险 | 事实/推断 | 处置 |
|---|---|---|---|
| 1 | **新→旧降级崩溃**：`ProviderConfig.from_dict`（`config.py:537-549`）对 `models[].*` 不做键过滤，给 `ProviderModelConfig`（`489-495`）加任何字段，都会让旧版本加载新配置时 `TypeError` | 【事实】该处直接 `ProviderModelConfig(**model_data)` | 本设计**不加字段**；若将来要加（例如标记"用户显式填过"），必须先补 `_filter_dataclass_payload(ProviderModelConfig, model_data)` |
| 2 | **`config import` 不做偏好过滤**：`config_entry.py:119` 直接 `PreferencesConfig(**payload)`，导入"新版本导出、含未知偏好键"的文件会抛 `TypeError`（`model_catalog_fetch` 本身就是这类新键） | 【事实】`config_entry.py:118-119` | 记为既有缺陷，交配置层 owner（Codex）修（一行 `_filter_dataclass_payload`）；本设计不改 |
| 3 | **快照键名覆盖**：`config.snapshot`/`model.status` 若用 `model` 作规格块，会覆盖 TUI `runtime.model`（字符串） | 【事实】`app.tsx` 的 `RuntimeSnapshot.model?: string`、两处 `setRuntime({...current, ...status.result})`、`snapshot.model ?? "model"`；后端 `model.status.model` 是模型名（`jsonl_server.py:1266`） | 硬约束：用 `model_spec`（§2.3/§2.4）；加用例 `test_model_status_spec_key_does_not_shadow_the_model_name` |
| 4 | **离线/超时**：冷进程首次打开助手最坏等 10s（`model_catalog.py:18`） | 【事实】10s 超时；TUI 请求预算 `const PROBE_TIMEOUT_MS = 30_000`（`app.tsx`） | `await asyncio.to_thread` 不阻塞 chat 流（先例 `jsonl_server.py:1644`）；**只拉一次、不重试**；失败 → `builtin` + `reason:"fetch_failed"`；UI 标注"规格来自内置预设，可能不是最新" |
| 5 | **models.dev 限流/不可用** | 【推断】静态 CDN JSON，但无 SLA | 一次/进程，无轮询、无 TTL（方案 §B2 第 92-99 行的修订版已否掉 TTL）；失败路径已静默；"重新获取"按钮是唯一重试入口 |
| 6 | **模型名规范化差异**：`deepseek-flash` 只在 `deepseek` 键下命中；`siliconflow` 的 `deepseek-ai/DeepSeek-V3` 与 models.dev 的 `deepseek/deepseek-v3` 不会互相命中 | 【事实】`lookup` 按 `(provider_alias, normalized_model)` 精确匹配（`model_catalog.py:219-233`） | **不猜**：未命中即 `unknown`/`builtin`；需要跨键对齐时加**显式**别名表（照 `PROVIDER_KEY_MAP:25-48` 的先探测后写死）；用户可用 B3 路径手填规格 |
| 7 | **端点语义差异**：同名 provider 走了非官方 base_url | 【事实】models.dev 不区分端点（`docs/model-metadata-sources.md:76-77`） | `endpoint_matches_preset == false` → `needs_verification: true`（数字照给，但标明待核） |
| 8 | **旧配置文件缺字段** | 【事实】`PreferencesConfig.__post_init__`（`840-856`）逐项归一化缺失值；`model_catalog_fetch` 缺省 `True`（`838`） | 无需迁移；测试覆盖"缺字段=默认"即可 |
| 9 | **`_apply_setup` 非事务**：字段逐个赋值、最后保存一次（`1083-1133`） | 【事实】既有行为（同 `symbol_locate`） | 规格校验放在赋值之前；文档明说"整单失败只保证不落盘，不保证内存零残留" |
| 10 | **`save()` 会重建 provider 对象** | 【事实】`config.py:1361-1363`；`_apply_setup` 保存后还会 `AppConfig.load` 重载（`1136`） | 规格写入必须在 save 之前完成；不要在 save 后比较对象身份（既有坑） |
| 11 | 旧 TUI 遇到新键 | 【推断】`SetupOptions` 是结构化读取，未知键被忽略 | 加法安全；新 TUI + 旧后端则要求前端到处 `?.` 兜底（§3.6） |

---

## 6. 未决项（需用户/Codex 决策，本设计不擅自定）

1. **「模型规格」屏在助手里的位置**：建议紧跟在 `model`（选模型）之后、`api_key` 之前，每槽一次；custom 流程（`app.tsx` 的 `customOrder` / `order()`）里建议放在 `route_*` 之后。属 TUI 体验决策，交 mimo/用户。
2. **`needs_verification` 的一键实测**：方案 §B2 第 100-101 行写的是"（`_p5_verify/p6proto/probe_*` 脚本可直接复用）"——那些一次性脚本已产品化为 `scripts/probe_model_reasoning.py`（其 docstring 自述"产品化自 `_p5_verify/p6proto/`"），本文据此给命令提示。本轮只做**文案 + 命令提示**，不做从 TUI 跨进程执行（涉及密钥与子进程，风险高于收益）。
3. **是否给 `ProviderModelConfig` 加来源标记**（区分"用户显式填的"与"预设默认"）：本轮不加密（见 §5 第 1 条），因此 `needs_verification` 用"生效值是否与目录一致"近似判定。若将来要精确到"用户改过没有"，先补 `from_dict` 过滤再加密。
4. **CLI 向导（`cli.py:859-921`）是否也用目录默认值**：它已经在问规格（`909-918`），但同步拉 10s 会卡住交互；建议后续复用本设计的 `_CatalogState` 思路做一个"先查进程缓存、无缓存就退预设"的同步版本。本设计把 CLI 侧限定为**只读出口 + 回归测试**。
5. **`max_tokens` 是否跟随 `max_output`**（方案 §B1 验收第 80 行"`max_tokens` 随之变化"）：涉及 `AIClientConfig.max_tokens`（`config.py:987`）与 chat/review 预算链路（还有 §C6 的 reasoning 预算预留），**不在本设计范围**，需单独立项，否则会出现"规格改了但请求体没变"的落差。
6. **`config.catalog.refresh` 协议方法**：本设计给了契约但标"可选"；若要做"重新获取"按钮，需同时定 UI 反馈（拉取中/成功/仍失败）。

---

## 附录 · 本设计任务的验证记录（2026-09-26）

- **未改任何源码**：`git status --short` 中本任务只新增 `docs/b2b3-wiring-design.md`（其余 `M frontend/tui/src/*` 是 mimo 的并发改动，与本文无关）。
- **测试基线（实测，`TEMP/TMP = .pytest_claude`）**：
  - `python -m pytest tests/test_model_catalog.py -q --no-cov` → **13 passed in 0.07s**（与 §4.1-A 的"13 条旧用例"一致）
  - `python -m pytest -q --no-cov` → **1049 passed, 1 skipped in 91.88s**
- **行号来源**：全部为本次只读核查；`app.tsx` 因 mimo 并发改动**不标行号**，改用符号锚点。
- **并行核对（已完成）**：两个只读 subagent 分别核对 Python 侧与 TUI/文档/测试侧的行号与事实性断言，发现并已修订 4 处：
  1. `PROVIDER_MODEL_PRESETS` 的锚点由 `config.py:344` 改为 `355`（344-352 是 `_build_models`）；
  2. `config test` 并非 JSON 出口（`run_config_test` 返回 `ModelProviderConfig`，无规格字段）→ §1 第 14 行、§3.4、§4.1-D 收窄为 **`config health` 一个出口**；
  3. `run_config_models` 落 `32_768/4_096` 的真实来源是 `cli.py:1834-1862` 的 `_set_active_model`（dataclass 默认值），不是 `ensure_default_model_present` → §3.5 已改写；
  4. `app.tsx` 正在被并发改写（行号在两个 subagent 核对期间仍移动，md5 变了两次）→ 本文对该文件**一律改为符号锚点**，不再给行号；`scripts/probe_model_reasoning.py` 的引用改为"方案 §B2 第 100-101 行的 `_p5_verify/p6proto/probe_*` 的产品化版本"。
