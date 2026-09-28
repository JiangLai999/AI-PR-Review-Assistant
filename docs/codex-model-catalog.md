# 模型目录服务（任务 `codex-model-catalog-b`）

日期：2026-09-26 · 对应方案：`docs/chat-experience-plan.md` §B2  
依据：`docs/model-metadata-sources.md` 的 models.dev 评估

## 范围

本任务只落地模型目录的**获取 + 归一化**层，新增
`src/ai_pr_review/services/model_catalog.py`。它不接入 `jsonl_server`、
不修改配置助手，也不持久化网络结果；因此 chat、review 和状态查询不会因为
本服务发起网络请求。

## 数据来源与字段

主源是 `https://models.dev/api.json`，请求超时固定为 10 秒。

| models.dev 字段 | `ModelSpec` 字段 | 归一化规则 |
|---|---|---|
| 顶层 provider key | `provider` | 保留 models.dev 原始 key；查询时通过映射别名命中 |
| `models.<id>` 的 key 与 `id` | `model_id` | 保留原始字符串；查询额外生成宽键索引 |
| `limit.context` | `context_window` | JSON 整数；浮点整数值兼容；布尔/负数/无法解析为 `None` |
| `limit.output` | `max_output` | 同上 |
| `reasoning_options` | `reasoning_options` | 只保留对象项，复制为普通 dict，避免缓存被调用方改动 |
| — | `source` | 成功时固定 `models.dev` |
| — | `fetched_at` | 本进程成功解析响应时的 UTC 时间 |

`reasoning_summary(spec)` 输出：

```json
{
  "supported": true,
  "controls": [
    {"kind": "toggle", "values": null, "min": null},
    {"kind": "effort", "values": ["low", "high", "max"], "min": null},
    {"kind": "budget_tokens", "values": null, "min": 1024}
  ]
}
```

未知控制类型不进入 `controls`；不猜测它是否等价于既有类型。字段与类型不匹配
时（例如 `effort.values` 不是字符串数组）按 `None` 处理。

## Provider 映射

`PROVIDER_KEY_MAP` 是应用内名称到 models.dev 顶层 key 的显式映射，覆盖本地预设
中的常见供应商。2026-09-26 只读探测 api.json 确认的关键 key 包括：

| 应用内 provider | models.dev key |
|---|---|
| `deepseek` | `deepseek` |
| `anthropic` | `anthropic` |
| `qwen` / `dashscope` | `alibaba` |
| `doubao` | `volcengine` |
| `zhipu` / `zhipuai` | `zhipuai` |
| `moonshot` / `moonshotai` | `moonshotai` |
| `mimo` / `xiaomi` | `xiaomi` |
| `xiaomi-token-plan-cn` / `mimo-token-plan-cn` | `xiaomi-token-plan-cn` |

映射表有注释说明来源；新增 provider 时应先确认 api.json 的实际 key，不猜。
同一 provider 在多个端点（例如 `xiaomi` 与 `xiaomi-token-plan-cn`）下会重复出现，
目录分别建立索引，但不做端点间能力合并。

## 缓存与失败回退

- 缓存是**类级、进程内**的：同一次运行中多个 `ModelCatalog()` 实例共享一次成功
  或失败结果。线程访问由 `threading.Lock` 串行化。
- `fetch()` / `lookup()` 的 HTTP 错误、超时、UTF-8/JSON 解析错误或响应形状错误
  都返回 `None`，不抛异常。
- 失败结果也只保留一次，避免断网时每个模型查询都重试 10 秒。
- `refresh()` 是唯一强制重拉入口；后续 UI 的“重新获取”按钮应调用它。
- 返回 `None` 的语义由调用方处理：继续使用内置预设并如实标注来源/unknown。

## 配置开关

`preferences.model_catalog_fetch` 默认为 `true`，沿用
`PreferencesConfig.__post_init__` 的布尔归一化惯例；关闭时，后续配置助手不应
自动触发目录同步。当前服务层不读取这个开关，因为“打开配置助手”的时机属于
下一个接入任务。

## 下一步边界

配置助手接入时应：

1. 只在助手打开、且 `model_catalog_fetch` 为 true 时调用一次 `fetch()`；
2. `lookup(provider, model)` 命中后把 `context_window` / `max_output` 作为默认值，
   `reasoning_summary()` 供思考强度 UI 使用；
3. 目录未命中时保持既有 `ProviderModelConfig` 预设，不套用其他模型/供应商的值；
4. UI 标注目录来源和 `fetched_at`；`None` 时标注“内置预设”；
5. 不在 chat/review 路径调用本模块。

## 测试

`tests/test_model_catalog.py` 全部 stub `urlopen`，不联网。覆盖：

- DeepSeek 真实片段的字段归一化；
- MiMo toggle-only 与 Anthropic effort+budget；
- 网络失败、无效响应、未知 provider/model；
- 类级进程内缓存与 `refresh()` 重拉；
- `model_catalog_fetch` 默认值与布尔归一化。
