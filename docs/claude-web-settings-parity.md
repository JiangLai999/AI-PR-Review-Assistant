# Web 设置页对齐 CLI 配置助手 6 阶段（Phase 2 前端）

**一句话结论**：Web 设置页从"只有模型服务"补成 4 个配置分组（模型服务与凭证 / 成本与并发 /
界面与输出 / 审查偏好）+ 凭证健康面板 + 保存区，6 个偏好下拉（`ui_language` / `output_format` /
`chat_layout` / `workbench_mode` / `repo_context` / `review_reasoning_effort`）的**选项来自后端
`config.options.*`、初值来自 `config.preferences.*`**，保存时与既有平铺键一起提交；
后端还没合入读侧（`ConfigView` 无这三个键）时整组降级为禁用 + 「当前后端不支持这一项」，不崩、不提交。
离线自证 **71 断言全绿**（Playwright，`/api/**` 全部打桩），`npm run typecheck` 退出码 0。

## 1. CLI 助手 6 阶段 ↔ Web 分组/控件

阶段号取自 CLI 配置助手的**渲染源**：`frontend/tui/src/app.tsx:1761-1790`（`screenStages`）、
`:1792-1808`（`stageNames`）、`:2761-2763`（渲染成 `N/6 · 阶段名`）；
实测帧 `.pytest_claude/ai-pr-review-repo-context-check/frame-repo-context-zh.txt:9` 显示
`5/6 · 界面与输出`。

| CLI 阶段 | CLI 阶段名 | Web 分组（`SettingsPage.tsx`） | Web 控件 |
| --- | --- | --- | --- |
| 1/6 | 运行模式 | 模型服务与凭证 · 卡片头 | `runtime_profile` **只读** Chip（`:527`）——槽位路由 Web 仍无入口 |
| 2/6 | 模型服务 | 模型服务与凭证 `:515-518` | 供应商预设 / Base URL / 模型名 / API 格式（原样保留） |
| 3/6 | 凭据与模型 | 同上 | 模型 API Key |
| 4/6 | GitHub Token | 同上 | GitHub Token |
| 5/6 | 界面与输出 | 界面与输出 `:740-745` + 审查偏好 `:750-755` | 6 个 `<select>`：`ui_language` / `output_format` / `chat_layout` / `workbench_mode` / `repo_context` / `review_reasoning_effort` |
| 6/6 | 确认保存 | 保存 `:760-764` | 「校验后保存 / 直接保存 / 放弃改动」（原样保留） |
| — | （无此阶段） | 成本与并发 `:660-663` | Web 独有 8 项：6 个数值 + 2 个开关 |

**为什么是 4 组**：任务书写的是"把现有『模型服务/凭证/成本与并发』与新增的两组分成 4 组"，
落点为 `模型服务与凭证`（阶段 2-4 合并，因为 api_key 与 GitHub Token 本来就在同一张卡里）、
`成本与并发`、`界面与输出`、`审查偏好`；原有的「凭证健康」是探测面板不是配置组，保留在第 3 个 Section。

**阶段号与任务书示例不一致（以 CLI 为准）**：任务书示例写「界面与输出 · CLI 助手 **4/6**」，
但 CLI 助手的真实渲染是 **5/6**（4/6 是 GitHub Token）：`app.tsx:1800` 把 `ui_language` /
`output_format` / `auto_publish` / `chat_layout` / `workbench` / `repo_context` / `review_effort`
全部标在 stage 5，`app.tsx:1795` 的 `github: 4`。本页取 **5/6**，
`docs/web-workbench-proposal-opencode.md:98` 的建议同样是 `STAGE 5 · UI & OUTPUT`。
`repo_context` 与 `review_reasoning_effort` 在 CLI 里也在同一阶段，Web 拆成两组只为便于查找，
两组的阶段标注都写 5/6（`:750-755` 的说明里写明了这一点）。

## 2. 改动点（file:line）

`web/src/api/types.ts`

- `:204-208` `OptionItem = { value; label }`
- `:210-215` `NumericRange = { min?; max?; step? }`
- `:217-226` `PreferenceView`（6 个可选字符串）
- `:230-238` `ConfigOptions`（6 个清单 + `numeric_ranges: Record<string, NumericRange>`）
- `:253-257` `ConfigView` 新增 `preferences?` / `options?` / `runtime_profile?`

**三个新键都标成可选（`?`）**：任务书要求"后端缺字段时该组禁用、不要崩"，可选类型才能在
`tsc --strict` 下强制所有读取点写降级分支；后端合入后它们会一直有值，不影响契约。

`web/src/pages/SettingsPage.tsx`

- `:21-26` 阶段号与降级文案常量（含 CLI 阶段号来源注释）
- `:47-64` `PreferenceKey` / `OptionListKey`；`:71-115` 两组控件表（label + hint）
- `:136-150` `preferencePayload()`：只提交"后端给了清单且值非空"的键
- `:156-191` `postConfig()`：见 §4 的 400 语义
- `:197-242` `PreferenceSelect`：`<select>` + 旧后端禁用 + 陈旧值回显
- `:244-298` `PreferenceGroup`：分组 Card + 阶段 Chip + 整组降级提示
- `:365-381` `probe({silent})`：保存后的探测不再清掉保存结果（见 §4）
- `:394-431` `save()`：payload 合并 6 键、`ok:false` 分支、成功后 hydrate
- `:515-518` / `:527` 模型服务与凭证分组 + `runtime_profile` 只读 Chip
- `:660-737` 成本与并发分组 + `numeric_ranges` 渲染 min/max/step（`:677`）
- `:740-745` 界面与输出 / `:750-755` 审查偏好
- `:760-802` 保存分组

## 3. 契约（本轮按此实现，字段名已冻结）

请求（`POST /api/config`，平铺键，形状不变，只多 6 个偏好键）：

```json
{ "provider_name": "...", "base_url": "...", "model": "...", "api_format": "openai",
  "persist_secrets": true, "validate": false,
  "max_tokens": 4096, "timeout_seconds": 120, "...": "…6 个数与 2 个开关…",
  "ui_language": "zh-CN", "output_format": "terminal", "chat_layout": "compact",
  "workbench_mode": "auto", "repo_context": "tests", "review_reasoning_effort": "off" }
```

**不提交** `auto_publish_comment` / `response_language`（后端刻意不给 Web，
见 `src/ai_pr_review/web_config.py:45-47`，提交即 `unsupported key` → 400）；
`runtime_profile` 只读展示，同样不提交。

响应（`GET /api/config` 的 `ConfigView.to_dict()`）新增 `preferences` / `options` / `runtime_profile`
三键、既有键不变 —— 读侧由 opencode 的 `p2-config-view` 任务落地（`src/ai_pr_review/web_config.py`）。

## 4. 降级与失败语义

1. **旧后端（读侧未合入）**：`options.<清单>` 缺失 → 该下拉 `disabled` + 占位文案
   「当前后端不支持这一项」；整组都缺时组内再显示一条 `Notice`。
   保存时**跳过**这些键（提交会被 400 拒，见 `web_config.py:84-88` 的白名单语义），
   既有 6 个数值 + 2 个开关 + 供应商三键照常提交。
2. **400 `{ok:false, message}` 必须显示 message**：`api.saveConfig` 走的
   `client.ts:56-62` 在非 2xx 时只读 body 的 `error` 键，而本端点的 400 body 是
   `{ok, changed, message, save_key_used, config}`（`web_server.py:409-419`），
   直接调用会只剩 "HTTP 400"。因此 `SettingsPage.tsx:156-191` 就地实现了一次 POST，
   读 `message`；`{error, credentials}`（校验失败，`web_server.py:392-399`）也照读 `error`。
   失败分支**不 hydrate**，用户刚填的密钥/选择不会被服务端旧值冲掉。
3. **保存结果被冲掉的既有缺陷（本轮修）**：`probe()` 开头有 `setMessage(null)`，
   而保存路径是"先 `setMessage(成功文案)` 再 `await probe()`" → 成功/失败提示会被当场清掉，
   用户看不到"到底保存成功没有"（与 TUI 那次同类缺陷同源，commit `17b49bb`）。
   现在 `save()` 一律用 `probe({ silent: true })`（`:416/:421/:426`），手动「重新探测」仍会清提示。

## 5. 验证（真跑，数字如下）

```
$ cd web && npm run typecheck
> tsc --noEmit            # 退出码 0，无输出

$ npx vite --port 5203 --strictPort         # 前置：静态服务
$ BASE=http://localhost:5203/static/ node .pytest_claude/claude/verify-settings-parity.mjs
断言：71 passed, 0 failed
```

脚本 `.pytest_claude/claude/verify-settings-parity.mjs`（离线，`/api/**` 全打桩），4 个场景：

| 场景 | 覆盖 | 结果 |
| --- | --- | --- |
| [1] 新后端 | 6 个下拉渲染 / 初值来自 `preferences`（刻意都**不是**清单第一项）/ 选项与 label 来自 `options` | 24 断言全绿 |
| [2] 保存 | `POST /api/config` 只发 1 次；偏好键集合 **== 6 个可编辑键**；不含 `auto_publish_comment` / `response_language` / `runtime_profile`；既有 6 键形状不变；改过的键发新值、没改的发原值；成功后显示后端 `message` | 15 断言全绿 |
| [3] 400 `ok:false` | 页面显示后端 `message`；无任何"已保存"成功提示；提示为 `role=alert`；失败后用户选择未被旧 config 覆盖 | 4 断言全绿 |
| [4] 旧后端 | 页面不崩；6 个下拉全禁用 + 占位「当前后端不支持这一项」；提示条存在；不提交这 6 键；原有载荷照常提交；数值输入退回本地 step | 22 断言全绿 |
| [5] 数值范围 | `#timeout_seconds` = 5/600/5、`#max_cost_per_24h` = 0/1000/0.5（来自 `options.numeric_ranges`） | 2 断言全绿 |
| [6] 分组标注 | 4 个阶段 Chip + 6 个分组标题 + `运行模式 · cloud` 只读 Chip | 11 断言全绿 |

## 6. 未决项

1. **阶段号口径冲突（未确认，建议主控裁决）**：任务书示例与 `p2-config-view-opencode.md` 把
   「界面与输出」记为 **4/6**、"审查偏好"记为 5/6；CLI 助手源码与实测帧是 **5/6**（4/6 = GitHub Token）。
   本页按 CLI 源码取 5/6。若主控确认以任务书口径为准，改 `SettingsPage.tsx:23` 一处即可。
2. **后端读侧未合入**：`ConfigView` 至今没有 `preferences` / `options` / `runtime_profile`
   （`src/ai_pr_review/web_config.py:95-127`，写侧 `EDITABLE_PREFERENCE_FIELDS` 已在 `:45-55`）。
   在 opencode 的 `p2-config-view` 落地前，真实页面上这 6 个下拉**都是禁用态**（[4] 场景即当前真实行为）。
   落地后无需再改前端，建议由 opencode 或主控用同一脚本的 [1]/[2] 场景对真实服务复跑一次。
3. **`client.ts` 的 400 语义应收口**：建议把 `web/src/api/client.ts:56-62` 的兜底改成
   依次读 `error` → `message`，或给 `request()` 加一个"保留 body"的开关；
   本次因 `client.ts` 不在 write_scope，只在设置页就地适配了一处（`SettingsPage.tsx:156-191`）。
4. **i18n 全站化留到 Phase 3**：本轮 6 个下拉的 label 已经由后端给中英双语
   （`options.*[].label`），但页面自身的文案（分组标题、hint、按钮）仍是硬编码中文，
   与 `preferences.ui_language` 尚未联动；方案见 `docs/web-workbench-proposal-opencode.md` §2.5。
5. **Web 仍无「运行模式 / 双槽位」入口**：CLI 第 1 阶段（阶段号 1/6）在 Web 只有只读 Chip
   （`SettingsPage.tsx:521-523`）。`local_only` 下 `base_url`/`model` 会被
   `_sync_runtime_sections()` 用本地槽位值覆盖，这一点本轮未改，仍是设置页的已知语义坑。
6. **未验证**：没起真实 Python 服务对 `POST /api/config` 做端到端写入（离线打桩覆盖了
   请求/响应两侧的分支）；真实后端下的落盘结果需 opencode 的 pytest 与本次脚本 [1]/[2] 复核。
