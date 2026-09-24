# P4 OpenTUI 独立只读复核报告

**范围**：`frontend/tui/src/{app.tsx,command-menu.ts,format.ts,keymap.ts}` + `command-menu.test.ts` / `keymap.test.ts` / `format.test.ts`  
**读取次数**：7 / 12。未读 node_modules、tui_static、dist、其他文档、凭据；未全仓搜索；未改文件。  
**format.ts / format.test.ts**：与三问无关（仅路径/URL 截断），不展开。

---

## (1) `/model`、`/model status`、`/review` 的 Enter / Tab / 空格

### 结论：确证存在 2 处 Enter 吞参/误执行；空格安全；Tab 在带参时会误切 Mode

| 键 | 行为 | 判定 |
|----|------|------|
| 空格 | 无任何 handler，只作正文输入 | **确证安全** |
| Enter | 见下 2 个缺陷 | **确证缺陷** |
| Tab | 菜单无匹配时切 Build/Plan/Compose 且未 `preventDefault` | **确证切 Mode；是否插入 `\t` 待实测** |

### 缺陷 A：唯一前缀绕过「需参命令先补全」— **确证**

`command-menu.ts:45-57` 注释写明「需参命令第一次 Enter 只补全」，但 `matchCount === 1` 分支无视 `needsArgument`：

```50:56:frontend/tui/src/command-menu.ts
  const exact = draft.trim().toLowerCase() === option.name.toLowerCase()
  const needsArgument = Boolean(option.argument)
  const hasTrailingSpace = draft !== draft.trimEnd()
  if (exact && (!needsArgument || hasTrailingSpace)) return { kind: "run" }
  if (exact && needsArgument) return { kind: "complete", draft: commandCompletion(option) }
  if (matchCount === 1) return { kind: "run" }
  return { kind: "complete", draft: commandCompletion(option) }
```

- 精确 `/review` → 补全 `/review `（`command-menu.ts:54`，测试覆盖）
- 唯一前缀 `/rev` → **直接 run `/review`，args 为空**（走第 55 行）

`submit()` 随后 `override = selected.name`（`app.tsx:240`），丢弃用户草稿，执行空参 `command.execute`（`app.tsx:277-281`）。

测试缺口：`command-menu.test.ts:40-44` 只测了无参 `/he`→run，**无 `/rev`→complete 用例**。

**最短复现**：
1. 输入 `/rev`（菜单唯一命中 `/review`）
2. Enter  
→ 期望：草稿变为 `/review `；实际：立即执行无 URL 的 `/review`。

**最小修复**（`command-menu.ts:55`）：
```ts
if (matchCount === 1) {
  if (needsArgument && !hasTrailingSpace) return { kind: "complete", draft: commandCompletion(option) }
  return { kind: "run" }
}
```
保留 `/he`→run（现有测试），补测 `commandEnterAction("/rev", review, 1) === { kind: "complete", draft: "/review " }`。

---

### 缺陷 B：`/model st` 被高亮项替换并执行 `/model status` — **确证**

`command-menu.ts:26-28`：draft 含空格时仍可能唯一命中多段命令名：

```26:28:frontend/tui/src/command-menu.ts
  if (query.includes(" ")) {
    return commands.filter((command) => command.name.startsWith(query) || query === `${command.name} `)
  }
```

`commandMatches("/model st")` → 仅 `["/model status"]`（`/model status`.startsWith(`/model st`)）。

随后 `commandEnterAction("/model st", …, 1)`：非 exact → 第 55 行 **run**；`app.tsx:240` `override = selected.name` 把草稿 **`/model st` 替换成 `/model status`**，执行连通性检查，而不是用户可能想要的 `/model st…` 模型切换。参数被命令名吞掉。

**最短复现**：
1. 输入 `/model st`（或 `/model stat` / `/model statu`）
2. Enter  
→ 期望：作为 `/model` + 参数发送或补全到 `/model `；实际：执行 `/model status`，草稿被覆盖。

**最小修复**（与缺陷 A 同处）：
```ts
if (matchCount === 1) {
  if (needsArgument && !hasTrailingSpace) return { kind: "complete", draft: commandCompletion(option) }
  if (!exact && option.name.includes(" ")) return { kind: "complete", draft: option.name }
  return { kind: "run" }
}
```
并建议 `app.tsx:240` 在 `kind === "run"` 时优先 `override = liveDraft`（精确匹配时二者等价，避免再吞参）。

---

### Tab 切 Mode（附带）— 部分确证

`app.tsx:337-338`：带参后 `commandMatches` 为空，`onEditorKeyDown` 直接 return。  
`app.tsx:372-376`：`matches().length === 0` 时 Tab 切换 Mode，**无 `preventDefault()`**。

**最短复现**：输入 `/review https://github.com/org/repo/pull/1` 后按 Tab → Mode 从 Build 变为 Plan。  
是否同时向 textarea 插入 tab 字符（进一步破坏 URL）— **待实测**（OpenTUI textarea 默认行为未在允许文件内）。

**最小修复**：`app.tsx:372` 分支对 `key.preventDefault()`；若 draft 以 `/` 开头则忽略 Tab 切 Mode。

---

## (2) `INITIAL_MESSAGE` 的 `onMount` + `setTimeout` 是否覆盖用户输入

### 结论：**确证会覆盖**（无条件 `setText`）

```183:222:frontend/tui/src/app.tsx
  const initialDraft =
    (typeof process !== "undefined" ? process.env?.AI_PR_REVIEW_INITIAL_MESSAGE ?? "" : "").trim()
  const [value, setValue] = createSignal(initialDraft)
  // ...
  onMount(() => {
    if (!initialDraft) return
    setTimeout(() => setDraft(initialDraft), 0)
  })
```

```211:215:frontend/tui/src/app.tsx
  const setDraft = (text: string) => {
    textarea?.setText(text)
    setValue(text)
    props.onDraftChange(text)
  }
```

要点：
1. `<textarea>` **未绑定 `value=`**，初始草稿只靠 timeout 里的 `setText` 写入。
2. timeout 回调 **不检查** textarea 是否已有用户输入，直接 `setText(initialDraft)`。
3. 若用户在 mount → macrotask 之间输入/粘贴/清空，`onContentChange` 已写入用户内容，随后被 `initialDraft` **整段覆盖**。
4. 无对应单元测试（仓库内无 `app.test`）。

**最短复现**：
1. `AI_PR_REVIEW_INITIAL_MESSAGE="/review"` 启动 TUI  
2. 在 timeout 触发前向 composer 输入 `hello`（测试可：mock 挂载后立刻 `setValue`/模拟按键，再 `flush microtasks + timers`）  
→ 实际：composer 变回 `/review`，`hello` 丢失。

**最小修复**：
```ts
onMount(() => {
  if (!initialDraft) return
  setTimeout(() => {
    const current = textarea?.plainText ?? value()
    if (current && current !== initialDraft) return // 用户已改写，勿覆盖
    if (!current) setDraft(initialDraft)
  }, 0)
})
```
（或仅当 `textarea.plainText === ""` 时才 `setDraft`。）

**状态**：覆盖逻辑本身 **确证**；真实交互下 0ms 竞态是否易被人类触发 **待实测**（输入事件与 timer 的相对次序依赖 OpenTUI 调度）。

---

## (3) Finding 详情 `Shift+↑/↓` 是否被 `select` 抢先处理

### 结论：**事件序待实测**；代码层已做正确分流，但 `select` 为 `focused`，存在被抢/双处理风险

意图分流（正确）：

```7:11:frontend/tui/src/keymap.ts
export function detailScrollDelta(name: string, shift: boolean): number | undefined {
  if (!shift) return undefined
  if (name === "up") return -1
  if (name === "down") return 1
  return undefined
}
```

```583:591:frontend/tui/src/app.tsx
  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    const detailDelta = detailScrollDelta(key.name, key.shift === true)
    if (detailDelta !== undefined) {
      detailScroll?.scrollBy(detailDelta)
      key.preventDefault()
      key.stopPropagation()
      return
    }
```

风险点：
1. Findings 列表是 **`focused` 的 `<select>`**（`app.tsx:606-613`），普通 ↑/↓ 依赖 select 导航（`keymap.ts:4-5` 注释明确）。
2. `useKeyboard` 里的 `preventDefault/stopPropagation` 只在 **本 handler 已拿到事件** 时有效；若 OpenTUI 先把 ↑/↓ 交给 focused select 并消耗事件，则详情滚动 **根本不会触发**（被抢）。
3. 若事件两者都到：select 未区分 `shift` 时会 **误改 selectedIndex**，同时详情也在滚（双处理）。
4. `KeyLike`（`app.tsx:24`）未声明 `shift`，依赖 OpenTUI 运行时字段；若实际报文为 `name: "shift+up"`，`detailScrollDelta` 恒为 `undefined`（**待实测**）。
5. 测试只覆盖纯函数 `detailScrollDelta`（`keymap.test.ts`），**无组件级事件序测试**。

**最短复现**：
1. 打开 Findings 详情（`Ctrl+O` 或审查完成）
2. 确保列表 `focused`，详情可滚  
3. 按 `Shift+↓`  
- 若列表光标下移 → **select 抢先（缺陷）**  
- 若仅详情滚动 → 当前实现成立  
- 若两者都动 → 双处理（缺陷）

**最小修复**（在 select 入口拦截，不依赖 useKeyboard 时序）：
- 给该 `<select>` 挂 `onKeyDown`（若 API 支持）：`shift && (up|down)` 时 `preventDefault` + `stopPropagation` + `detailScroll?.scrollBy(detailScrollDelta(...))`；或  
- 去掉 select 的 `focused`，↑/↓/Shift+↑/↓ 全部在 `FindingsDialog.useKeyboard` 内维护 `selectedIndex`。  
并补一条集成断言：`Shift+down` 后 `selectedIndex` 不变且 scrollY 增加。

---

## 总表

| # | 问题 | 状态 | 关键行号 | 误触发键 |
|---|------|------|----------|----------|
| 1a | `/rev`+Enter 空参执行 `/review` | **确证** | `command-menu.ts:55`, `app.tsx:240` | Enter |
| 1b | `/model st`+Enter 吞参执行 `/model status` | **确证** | `command-menu.ts:27,55`, `app.tsx:240` | Enter |
| 1c | 带参 Tab 切 Mode | **确证** Mode；插入 tab **待实测** | `app.tsx:372-376` | Tab |
| 1d | 空格误执行 | **确证无** | — | — |
| 2 | INITIAL_MESSAGE 覆盖用户输入 | **确证**（竞态窗口 **待实测**） | `app.tsx:183-222,211-214` | timeout |
| 3 | Shift+↑/↓ 被 select 抢先 | **待实测**（风险确证） | `app.tsx:583-591,606-613`, `keymap.ts:7-11` | Shift+↑/↓ |

复核结束。

