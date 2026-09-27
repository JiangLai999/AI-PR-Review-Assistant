# 配置助手 B2/B3 屏：模型规格与中转站表单（TUI）

- **任务**：mimo 实现（`frontend/tui/src/*` 979 行未提交改动）→ claude 接管收尾（`claude-config-wizard-fix`：修 11 条 manual 回归 + 补帧断言 + 本文件）。
- **契约来源**：`docs/b2b3-wiring-design.md` §2.1/§2.2/§2.5/§2.6/§2.8、§3.6、§6.1（屏的位置属 TUI 体验决策）。
- **改动文件**：`frontend/tui/src/{app,format,protocol,setup-routing}.tsx|ts`、`protocol.test.ts`、`scripts/manual-route-wizard-check.tsx`、本文件。**未碰 Python、未做 git 操作。**

---

## 1. 两个新屏做了什么

| 屏 | `screen` 值 | 数据来源（读） | 写入（`config.setup`） |
|---|---|---|---|
| 模型规格 | `model_spec` | `config.options.model`（顶层 = 活跃槽，`slots.remote/local` 给每槽明细） | `setupModelSpecFields()` → `context_window` / `max_output` / `local_context_window` / `local_max_output` |
| 中转站 | `custom_endpoint` | `config.options.custom_endpoint` | `setupCustomEndpointFields()` → `provider_name:"custom"` + `api_format` + 非空的 `base_url` / `api_key` / `model_name` / `context_window` / `max_output` |

两屏都遵循"**缺字段就不显示、绝不编造数字**"：旧后端没有 `model` / `custom_endpoint` 时，规格屏出「暂无模型规格数据」、中转站屏出五行 `—`，载荷里一个字节都不新增（既有 [A]/[B]/[E] 三条流程仍按旧形状断言）。

### 1.1 屏在流程里的位置（`screenStages` / `*Order`）

| 顺序 | 位置 | 理由 |
|---|---|---|
| `cloudOrder` | `… api_key → model → model_spec → custom_endpoint → github …` | 设计 §3.6.2 建议"紧跟在选模型之后" |
| `localOrder` | `… local_base_url → local_model → model_spec → github …` | 同上（本地槽只有一组规格字段） |
| `customOrder` | `route_review → model_spec → github`（**没有** `provider` / `api_key` / `local_*` / `custom_endpoint`） | 后端 `_apply_setup` 的 custom 分支只写 `chat_slot`/`review_slot`，写别的一律被忽略；显示出来是"填了没保存"的误导（设计 §2.6 的写路径） |

阶段编号（`screenStages`）本轮修了一处：`custom_endpoint` 原为 `2`（"模型服务"），而它在 cloud/local 顺序里紧跟 `model_spec`（3/6），进度条会 **3/6 → 2/6 → 4/6 倒退**；现为 `3`（"凭据与模型"），与同阶段的 `api_key`/`model`/`model_spec` 一致。帧证据：`frame-custom-endpoint-zh.txt` 第 8 行 `3/6 · 凭据与模型 · 中转站配置`。

### 1.2 键盘

- 路由细化两屏：`↑↓` 改当前方框、`Tab`/`←→` 换方框、`Enter` 前进、`Esc` 返回（原有行为，未改）。
- 模型规格屏：`R` 重新获取目录、`↑↓` 换编辑字段（先提交当前框）、`Enter` 前进（由输入框 `onSubmit` 处理，全局处理器对这两屏**提前 return**）、`Esc` 返回。
- 中转站屏：`↑↓` 换字段、`Enter` 前进、`Esc` 返回。两项的 `↑↓` 都会先把焦点字段写回对应 signal，再移动焦点。
- **首屏（运行模式）的 `← 返回`**：没有上一屏时"返回"= **退出助手**（等同 `Esc 取消`）。
  2026-09-27 用户实测修复——原实现是 `if (screen() === "runtime") return`，首屏的 `←`
  成了静默死键，而页脚写着「← 返回」。助手在确认页之前不落盘，退出不丢改动。
  同一规则兜底"当前屏不在本次顺序里"（旧后端缺 `review_reasoning_effort` 等）。
  回归：`manual-route-wizard-check.tsx` §[X]（帧 `frame-root-back-key.txt`）。
- **排错记录（2026-09-27）**：用户报「3/6 选择模型 屏的返回键没反应」，键位追踪
  （临时 `AI_PR_REVIEW_TUI_KEYLOG` 日志）显示按下去的是 `backspace`（退格键），整段操作
  里**没有一次 `left`**——助手只认 `←` / `Ctrl/Alt+←` / `Esc`，退格键没有任何绑定。
  结论：不是代码缺陷；若要支持"退格=返回"，那是新的交互需求（当前**不**做，保持
  输入屏里退格只删字符）。

### 1.3 数据流（读 → 编辑 → 写）

```
config.options.model ──parseModelSpecBlock()──► activeSpec()/remoteSpec()/localSpec()
        │                                              │
        │                                   primeSpecFields()（onMount、刷新后各一次）
        │                                              ▼
        │                        signals: specRemoteContext/Output、specLocalContext/Output
        │                                              │  ▲
        │                                   rows ←──────┘  └── liveInputText("model_spec")
        ▼                                                       （Enter / ↑↓ / commitInput）
config.options.custom_endpoint ──parseCustomEndpointOptions()──► customEndpoint()
        └── primeCustomFields() ──► 5 个 signal ──► 表单行 + 焦点输入框 ──► 同上
                                                                    │
config.setup ◄── setupModelSpecFields() / setupCustomEndpointFields()（只带用户改过的值）
```

- **规格值的作用域**：编辑值读的是 `slots.remote`（`primeSpecFields` 里 `spec.slots?.remote ?? spec`），顶层的 `source`/`context_window` 只喂头行与徽标。写 manual fixture 时**顶层与 `slots.remote` 要一起改**，否则会出现"徽标换了、编辑框还是旧值"——脚本的刷新 fixture 就踩过一次（见 §2.5）。
- **写回时机**：`onContentChange` 只更新 `inputValue()`；真正落进 signal 的是 `Enter`/`↑↓` 触发的 `liveInputText(owner)`。
- **提交粒度**：`setupModelSpecFields` 里 `undefined` 不发（后端 = 保持落盘值，§2.5 的 `null` 语义）；`setupCustomEndpointFields` 任一项有值才发（全空 = 不碰落盘的 `provider_name`）。
- **刷新（R）**：`config.catalog.refresh`（超时预算 `PROBE_TIMEOUT_MS = 30_000`）→ `parseCatalogRefreshResult(result)` → 成功则 `setOptions` + `primeSpecFields`，失败保留旧值并把原因显示成 `目录刷新失败，已保留旧值 · <原因>`（`formatCatalogRefreshStatus`）。

---

## 2. 本轮修复的回归：Enter 卡在上一屏（11 条断言全红）

### 2.1 现象

`scripts/manual-route-wizard-check.tsx` 的 11 条断言失败，全部落在 **[B] 云端预设**与 **[E] 本地预设**两条流程的确认页/载荷上；帧证据显示流程**停在 `3/6 · 凭据与模型 · 选择模型` / `选择本地模型`**，怎么按 Enter 都不动。

### 2.2 根因（证据判定：既不是 select 焦点，也不是 onMount 覆盖）

**真根因**：`goTo("model_spec")` 里无条件调用 `commitSpecField()`，它读 `inputRef?.value`；而 `inputRef` 可能指向**已被销毁的输入框**：

1. `next()`（Enter）→ `goTo("model_spec")` → `commitSpecField()` → `inputRef.value`；
2. `inputRef` 是上一个输入屏（cloud 流程里是 `api_key`）留下的 ref——opentui-solid 的 reconciler **只在挂载时回调 ref，没有卸载回调**：`node_modules/@opentui/solid/index.js:360` 是 `createRenderEffect(() => props.ref && props.ref(node))`，卸载时不回调 `undefined`；
3. 那个 `Input` 的 `EditBuffer` 已随屏幕切换销毁 → `Input.getText()` 抛 `EditBuffer is destroyed`；
4. 异常在 opentui 的全局 keypress handler 里被吞掉（控制台只有 `[KeyHandler] Error in global keypress handler: …`），于是**这一下 Enter 什么也没做**，屏幕停在前一屏。

栈（修复前，`TEMP/TMP=.pytest_claude`）：

```
error: EditBuffer is destroyed
  at guard (…/@opentui/src/edit-buffer.ts:67:32)
  at value (…/@opentui/src/renderables/Input.ts:122:12)
  at commitSpecField (frontend/tui/src/app.tsx)
  at goTo (frontend/tui/src/app.tsx)
  at next (frontend/tui/src/app.tsx)
  at <anonymous> (…/@opentui/src/lib/KeyHandler.ts:153:11)   ← 被吞，按键无效果
```

- 复现日志：`.pytest_claude/route-check-prefix-crash.log`（修复前，11 FAIL + 上述栈）。
- 为什么只影响 [B]/[E]：[A]（custom 顺序）走到 `model_spec` 时**还没经过任何输入屏**，`inputRef === undefined`，`?.` 短路不说，`?? inputValue()` 兜底成空串，所以侥幸不炸；[B]/[E] 都先过了 `base_url`/`api_key`（local 过 `local_base_url`），ref 已是死对象。
- 同一处的**第二个症状（未在测试里显形，代码层可判定）**：`goTo("custom_endpoint")` 也用上一屏（`model_spec`）的输入框文本去写 `customBaseUrl`。即使用户看到的中转站表单预填正确，保存时 `base_url` 会被上一屏的规格文本覆盖（例如 `"128000"`）。修掉 commit-on-enter 后 [G] 的帧里 `base_url` 仍是 relay 地址，正是这条的回归证据。

### 2.3 为什么不是官方给的两个疑似根因

| 疑似 | 判定 | 证据 |
|---|---|---|
| (a) runtime 屏 `<select>` 的聚焦/onChange 被新焦点逻辑影响 | **不成立** | 预设页的 ↓ 与 Enter 一直生效（[A] 每次都成功选到「自定义」并进入细化页）；只有"离开 `model`/`local_model` 屏"这一步卡住，而这两屏根本没有 `<select>` 的焦点参与 `goTo` |
| (b) `onMount(async …)` 的 `setRuntimeIndex` 覆盖用户按键 | **结构上不可能** | 预设 `<select>` 在 `<Show when={!loading() && screen() === "runtime"}>` 里，而 `setLoading(false)` 在 onMount 的 `finally`，即 `setRuntimeIndex` **之后**才发生；select 挂载时选中项已经是后端值，用户按键不可能先于它 |

### 2.4 修复（`frontend/tui/src/app.tsx`，精确字符串替换，未整文件重写）

1. 新增 `liveInputText(owner)`：**只认本屏的输入框**（`screen() !== owner` → `undefined`，调用方跳过回写）。`commitCustomField` / `commitSpecField` 改用它 ⇒ 任何跨屏路径都不可能再读死 `EditBuffer`，也不可能把别屏文本写进本屏 signal。
2. `goTo()` 不再在进屏时 `commitXField()`：进屏只做"复位焦点字段 + 预填初值"。那一刻的输入框属于上一屏（或已销毁），回写没有意义且会串值。
3. `screenStages.custom_endpoint: 2 → 3`（见 §1.1）。

**语义保持不变的部分**：屏幕内 `Enter`/`↑↓` 仍会提交焦点字段（`onSubmit` → `commitInput()`，`↑↓` → 先 commit 再换行）；输入屏（`base_url`/`api_key`/`local_base_url`/`github`）的 `commitInput()` 未改。

### 2.5 补帧断言时发现的第二个缺陷：`R` 刷新只重填了 signal，没重填编辑框

`refreshCatalog()` 的 docstring 写的是"成功 → 用返回的 model 块更新 options 并**重填编辑框**"，但实现只有 `setOptions` + `primeSpecFields`，没有更新输入框的 `inputValue`。实测后果（manual [F] 的探针）：

1. `R` 成功 → 行摘要 `上下文长度 1000000`（新目录值）、徽标 `models.dev ✓`，**但输入框里还是刷新前的 `128000`**；
2. 用户接着按 `↓`（会先把焦点字段写回 signal）→ `commitSpecField()` 把输入框里的旧文本写回 → **行摘要又变回 `128000`**，刚刷新到的目录值被静默丢掉；保存时发出去的也是旧值。

修复：刷新成功后按当前焦点字段重填编辑框（`setSpecFieldIndex(min(index, specFieldCount()-1))` + `setInputValue(specFieldValue(field))`）。
帧证据：`frame-spec-refresh-ok-zh.txt`（输入框 `1000000`）与 `frame-spec-refresh-then-down-zh.txt`（`↓` 之后仍是 `1000000`，焦点到最大输出、输入框装 `8192`）。

---

## 3. 既有断言：一条都没改

- 11 条失败断言**逐字未动**，修复后全绿 ⇒ 不是"改断言迁就实现"。
- `scripts/manual-route-wizard-check.tsx` 的既有 [A]/[B]/[E]/[C]/[D] 五节断言原文不变；本轮只做了**追加**：
  - fixture 侧：`setupOptions(language, extra)` 增加可选 `extra`（叠加 `model`/`custom_endpoint`/`routing`），`stubBackend`/`openWizard` 透传；默认不塞新块 ⇒ 旧流程仍走"旧后端形状"。
  - 新增 [F] 模型规格屏、[G] 中转站表单两节（§4）。
- `advance()` 的 `tries = 3` 默认值**保持不变**：cloud 顺序里 `model → model_spec → custom_endpoint → github` 恰好 3 次 Enter，实测够用（这一串正是修复前卡死的地方）。[F]/[G] 里需要更多步的地方**显式传参**（`advance(view, /中转站配置/, 10)`），没有改默认值。

---

## 4. 帧断言清单（`scripts/manual-route-wizard-check.tsx`）

新增两节，帧全部落在 `TEMP/ai-pr-review-route-check/`（本任务 `TEMP/TMP=.pytest_claude`）。

### 4.1 [F] B2 模型规格屏（custom 顺序：runtime → route_chat → route_review → model_spec）

| 断言 | 帧 |
|---|---|
| 头行 `provider · model`、`source` 徽标、远端上下文长度 + `范围 1024–10000000`、远端最大输出、本地两行（`slots.local` 存在才显示）、`needs_verification` **双数字**（`当前 128000 / models.dev 1000000`）、`推理能力` 摘要行、页脚键盘说明 | `frame-spec-120x30.txt` |
| 同样四项（120×30 之外的第二个尺寸） | `frame-spec-209x51.txt` |
| `source=cache → 缓存`（并反向断言徽标位不写 `models.dev`，needs_verification 行里的数据来源说明不算） | `frame-spec-source-cache-zh-CN.txt` |
| `source=builtin → 内置` | `frame-spec-source-builtin-zh-CN.txt` |
| `source=unknown → 未知` | `frame-spec-source-unknown-zh-CN.txt` |
| `source` 缺失（旧后端）→ `未知` | `frame-spec-source-missing-zh-CN.txt` |
| en-US：标题 `Model spec` + 徽标 `builtin` | `frame-spec-source-builtin-en-US.txt` |
| `R` 成功：`目录已刷新 · models.dev ✓` + 行摘要与**输入框**都改用目录值 + 徽标更新 | `frame-spec-refresh-ok-zh.txt` |
| `R` 成功后 `↓`：焦点换到下一字段、回写的是新目录值、输入框装新字段的值（§2.5 的探针） | `frame-spec-refresh-then-down-zh.txt` |
| `R` 失败：`目录刷新失败，已保留旧值 · Error: …` + 编辑框保持旧值 | `frame-spec-refresh-error-zh.txt` |

### 4.2 [G] B3 中转站五项表单（cloud 顺序，7 次 Enter 到屏）

| 断言 | 帧 |
|---|---|
| 屏标题 + `3/6 · 凭据与模型`（进度不倒退）+ `display_name` + `Key 已配置` + 五行（`base_url` / `API Key`（掩码 `••••`）/ `模型名` / `上下文长度` / `最大输出`）+ 页脚 | `frame-custom-endpoint-zh.txt` |
| `↓` 焦点移到 `API Key` 行且不改上一行的值 | `frame-custom-endpoint-down.txt` |
| 再 `↓↓` 焦点到 `上下文长度`，并显示该槽的编辑边界 | `frame-custom-endpoint-bounds.txt` |
| `Esc` 退回模型规格屏；`Enter` 之后进入 `GitHub Token`；确认页可提交 | `frame-summary-custom-endpoint-zh.txt` |

> 关于"断言值从哪来"：[G] 用 `custom_endpoint` **满值** fixture（`relay.example.com` / `relay-model` / 200000 / 16384），[F] 用 `model` 满值 fixture（顶层 128000/8192 + `catalog` 1000000/393216 + `needs_verification` + `bounds` + 两槽）。API Key 只回显掩码，脚本里没有任何真实密钥。

---

## 5. 验证命令与真实数字（`TEMP/TMP=C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_claude`）

| 命令（工作目录 `frontend/tui`） | 修复前 | 修复后 |
|---|---|---|
| `bun run typecheck` | exit 0 | **exit 0** |
| `bun test src` | 171 pass / 0 fail（830 expect，13 文件） | **171 pass / 0 fail**（830 expect，13 文件，2.7s） |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **11 FAIL**（exit 1） | **111 PASS / 0 FAIL**（exit 0，ALL PASS） |
| `bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx` | —（未变） | **75 PASS / 0 FAIL**（exit 0，ALL PASS） |

- 断言数变化：修复前 53 PASS + 11 FAIL = 64 条；新增 [F]（30 条）+ [G]（17 条）后 111 PASS / 0 FAIL。
- 帧目录：`.pytest_claude/ai-pr-review-route-check/`（29 张）、`.pytest_claude/ai-pr-review-chat-markdown/`（11 张）。
- 日志：`.pytest_claude/route-check-prefix-crash.log`（修复前，11 FAIL + 崩溃栈）→ `route-run-2.log`（只修 §2.4 后 ALL PASS）→ `route-final2.log`（加"刷新后 ↓"探针，1 FAIL，暴露 §2.5 的缺陷）→ `route-final3.log`（修完 §2.5，111 PASS / 0 FAIL）。
- **未跑 `bun run build`**（`dist/` 不在本任务范围，见既有约定）。

### 5.1 已知的既有失败：`manual-repo-context-wizard-check.tsx` 1 条（**不是本次改动引入**）

- 现象：该脚本 **53 PASS / 1 FAIL**，失败项是 `[E] 错误提示可见（助手没有被读取失败锁死）`。
- 判定为既有问题（三种证据）：
  1. 用 `git archive HEAD frontend/tui/src` 把 **未含 mimo 改动、也未含本次修复** 的源码复制到 `.pytest_claude/prefix-tui/`（`node_modules` 走 junction）实跑 → **53 PASS / 1 FAIL，同一条断言**（日志 `.pytest_claude/repo-context-HEAD.log`，帧同 `frame-repo-context-options-failed.txt`）。
  2. 同目录里另一 agent 12:23 的 `rc-wizard3.log` 也是 53 PASS / 1 FAIL。
  3. 机制在代码里：`goTo()` 第一行就是 `setError("")`（HEAD 已有，非本批新增），而该断言要求 `onMount` 里 `config.options` 失败写入的错误在**用户导航到「仓库上下文」屏之后**仍然可见——第一次 Enter 就把它清掉了。
- 该脚本不在本任务 `write_scope`（属仓库上下文任务），故**只报告、未改**。要修的话，方向是"错误只在重试成功后清除"或"把读取失败的提示与屏幕内容绑定"，属该任务 owner 的决定。

---

## 6. 未决项（需要实现者/用户拍板，本轮不擅自改）

1. **cloud/local 流程里的中转站表单会改 `provider_name`**（观测，未判定）：当 `custom_endpoint` 有落盘值（表单预填非空）时，即使预设选的是「云端」，`apply()` 也会 `Object.assign` 上 `provider_name:"custom"`，把远端槽切到中转站。实测载荷（[G] 的 fixture，注意与确认页上显示的 `Provider DeepSeek` / 模型 `deepseek-flash` 不一致）：
   ```json
   {"runtime_profile":"cloud","provider_name":"custom","model_name":"relay-model",
    "base_url":"https://relay.example.com/v1","context_window":200000,"max_output":16384,
    "local_context_window":32768,"local_max_output":4096}
   ```
   证据帧：`frame-summary-custom-endpoint-zh.txt`。两种可能的收口方式（都可能改到后端语义，故不在本任务做）：(a) 只有用户在表单里改动过才发送中转站字段（dirty 标记）；(b) 给这一屏一个显式"使用中转站"开关，未开启就不发。**当前 manual 的默认 fixture 没有 `custom_endpoint`，所以 [B] 的 `provider_name === "deepseek"` 断言仍然成立。**
2. **中转站的 `api_key` 只能写不能清**：清空 = 不发 = 保留落盘 Key；要清除需要另给动作（后端 `_apply_setup` 目前也没有"清空 Key"的语义）。
3. **`validateSpecInput()` 未接线**：`setup-routing.ts` 里已有越界/非整数提示函数（并有 docstring），`app.tsx` 也 import 了，但屏幕没有展示实时提示（`tsconfig` 未开 `noUnusedLocals`，所以 typecheck 不报）。当前越界值会在保存时被后端拒绝，再由 `apply()` 的错误路由回到 `model_spec`（设计 §3.6.4）。要不要做"前端先行提示"由实现者定。
4. **`needs_verification` 的一键实测**：本轮只有警示文案（设计 §6.2 明确不在本轮做跨进程执行）。
5. **`max_tokens` 是否跟随 `max_output`**：设计 §6.5 已列为独立立项，改了规格但请求体没变是已知落差（后端侧）。
6. **模型规格屏在旧后端的表现**：`model` 缺失时只显示「暂无模型规格数据」+ 空编辑框；是否值得给"该后端不支持规格编辑"的更明确文案，可再定。
