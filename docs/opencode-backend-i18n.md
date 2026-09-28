# Phase 4 · 后端生成文案的双语化（结构化键契约）

范围：Web 工作台里**由后端生成、前端直接显示**的文案。这类文案在英文界面下曾经
一律回落成中文原文——因为前端拿到的只有拼好的中文句子，没有可查词典的键。

## 1. 契约：原文 + 结构化键 + 插值参数

后端**同时**返回原文与键，是刻意的加法式设计：

- 原文（`message` / `label` / `detail` / `fix_hint`）继续供 CLI、旧前端、以及
  "词典还没跟上"时回落使用，**不得删除**；
- 键（`message_key` / `label_key` / `detail_key` / `fix_hint_key`）供新前端查词典；
- `params` 是插值参数，键里出现的每个 `{占位符}` 都**必须**在 params 里有值。

前端消费规则在 `web/src/pages/SettingsPage.tsx`：`hasDictKey(key)` 为真才走
`t(key, params)`，否则回落原文。空串键 = 没有可翻译的文案（例如探测通过时没有
修复建议），前端直接不渲染该行。

### 为什么占位符必须"给了才算"

`web/src/i18n/index.ts:interpolate()` 只在参数**存在**时替换：

```ts
return template.replace(/\{(\w+)\}/g, (match, name: string) =>
  name in vars ? String(vars[name]) : match,
)
```

所以"词典写了 `{models}`、后端没给 `models`"的后果不是缺一段文字，而是页面上
直接出现 `{models}` 字面量。`tests/test_i18n_text.py` 里有对应用例逐分支卡这条。

## 2. key 清单

### `POST /api/config` → `SaveResult`

| key | params | 触发条件 |
| --- | --- | --- |
| `config.save.saved` | `count`, `path` | 落盘成功 |
| `config.save.noop` | — | 提交值与原值相同 |
| `config.save.unsupported_key` | `keys` | 提交了白名单外的键 |
| `config.save.unsupported_provider` | `provider` | 供应商预设不存在 |
| `config.save.invalid_value` | `name` | 数值/布尔非法 |
| `config.save.invalid_value_options` | `name`, `options` | 偏好项不在词表内 |
| `config.save.verify_failed` | `fields` | 落盘回读与提交值不一致 |

### `GET /api/credentials` → `CredentialStatus`

GitHub：`credentials.github`（label）、`.missing` / `.unprobed` / `.ok`(`login`) /
`.invalid` / `.forbidden` / `.other`(`status`, `body`)，
修复建议 `.fix_token` / `.fix_reissue` / `.fix_retry` / `.fix_network`。

模型供应商：`credentials.provider`（label）、
`.missing` / `.unprobed` / `.unprobed_model`(`model`)、
`.ok` / `.ok_named`(`endpoint`) / `.ok_models`(`count`) /
`.ok_named_models`(`endpoint`, `count`)、
`.model_missing`(`model`, `models`) / `.invalid` / `.invalid_mismatch` /
`.not_found`(`url`) / `.unreachable`(`reason`) / `.error`(`status`)，
修复建议 `.fix_key` / `.fix_model` / `.fix_mismatch` / `.fix_endpoint` / `.fix_network`。

200 分支拆成 4 条（端点归属 × 是否有可用模型），是因为两个维度都可能为空：
合成一条会在英文界面拼出 `Connected to .` 这类半截句子。

## 3. 词典位置与守卫

词条都在 `web/src/i18n/settings.ts`（zh / en 各一份，key 集合必须一致）。

两层守卫，缺一不可：

1. `tests/test_i18n_text.py::test_every_backend_key_exists_in_the_frontend_dictionary`
   —— 扫后端源码里所有 `credentials.*` / `config.save.*` 字面量，逐个查词典（两种语言）。
2. `tests/test_i18n_text.py::test_provider_placeholder_values_match_the_branches`
   —— monkeypatch `_http_json` 走遍每个分支，断言"词典占位符 ⊆ 后端 params"，
   且中英词条的占位符集合相同。

这两个用例的存在理由是一次真机验收：当时后端 12 条键（含 `credentials.provider.ok`）
根本没进词典，单测全绿但英文界面 100% 回落中文。补齐后又按"空值维度"把
`.ok` / `.unprobed` / `.invalid` 各拆成 2–4 条（合成一条会拼出半截句子），
所以本页列出的键比"补漏"时多。

真机验收脚本：`node web/tools/backend-i18n-acceptance.mjs`（需 `pr-review serve` 在跑，
可用 `BASE=` 换地址；脚本临时切到 `en-US` 并在 `finally` 还原）。

## 4. 刻意保留的中文

6 组偏好下拉的 `label`（如「紧凑 / Compact」）由后端
`web_config.py:PREFERENCE_OPTION_LABELS` 给出，与 TUI `_setup_options()` 文案逐字对齐，
由 `tests/test_web_config_writes.py` 的漂移用例锁死（且 `options` 项形状被冻结为
`{value, label}` 两个键）。所以英文界面里这几行**会**出现中文，属契约不属漏翻；
验收脚本按"接口原样发出的 label"做白名单，而不是放过所有中文。

要改成单语只能同时改 TUI 文案与那条漂移用例，属独立改动。

## 5. 未覆盖

- 已落库的历史 run 不会回溯翻译：文案在**生成时**按当时的界面语言冻结。
- `filter_pipeline.py` / `hybrid_orchestrator.py` 的说明文字走
  `services/i18n_text.py` 的生成时本地化，不经过前端词典。
