# p2-ux · 键盘焦点可见 + 390px 窄屏导航（U1/U3）

> 任务：`.agent-bus/tasks/p2-ux.json`（agent: mimo）
> 日期：2026-09-27 · 写入范围：`web/src/styles/components.css`、`web/tools/focus-mobile-check.mjs`、本文件

## 1. 改动点

### U1 · 键盘焦点可见（`web/src/styles/components.css:1176-1198`）

- 给 `button` / `select` / `input` / `.input` / `.select` / `[role='button']` / `a` 补统一 `:focus-visible`：
  - `outline: 2px solid var(--ds-color-brand)`（design token，无 hex）
  - `outline-offset: 2px`
- `:focus:not(:focus-visible)` 显式 `outline: none`，鼠标点击不脏。
- 选择器带 `.input:focus-visible` / `.select:focus-visible`，以同等 class 级特异性盖过既有
  `.input:focus { outline: none }`（components.css:313）与 `.select:focus { outline: none }`（:329），
  放在文件末尾保证同特异性下后写生效。

### U3 · 窄屏（390px）导航不截断（`web/src/styles/components.css:1201-1305`）

只改 CSS（未动 `App.tsx`），`@media (max-width: 720px)` 新区块：

- `.workspace-sidebar`：变顶部横向条（`position: sticky` + `flex-direction: row`），
  品牌（`.sidebar-brand`）+ 图标（`.sidebar-icon` 保留显示）+ `.sidebar-nav` 可横向滚动
  （`overflow-x: auto`，滚动条隐藏）。
- `.workspace-statusbar`：`flex-wrap: wrap`，`.statusbar-title` / `.statusbar-model`
  `white-space: normal` + `overflow-wrap: anywhere`，不截断文字。
- 根/壳层 `overflow-x: hidden` + `max-width: 100%` + `min-width: 0`，保证 390px 无横向滚动条。

## 2. 断言与实测数字

脚本：`web/tools/focus-mobile-check.mjs`（Playwright，失败 `process.exitCode = 1`）
目标：`http://127.0.0.1:8787/`（hash 路由 `#/settings`）
环境：`TEMP`/`TMP` = `<repo>\.pytest_mimo`

### 2.1 对 8787 当前服务内容（构建产物）实跑

```powershell
$env:TEMP='...\.pytest_mimo'; $env:TMP='...\.pytest_mimo'
cd web; node tools/focus-mobile-check.mjs
```

| 断言 | 结果 | 实测数字 |
|---|---|---|
| A1 390×844 无横向溢出 | **PASS** | `document.documentElement.scrollWidth=390`（limit 391） |
| A2 1440×900 前 6 个 Tab 焦点 `:focus-visible` + `outline-width >= 2px` | **FAIL** | 6/6 均 `focus-visible=true`，但 `outline-width=1px`（浏览器默认环） |

失败原因（非 CSS 逻辑错误）：8787 由 Python 静态服务提供 **构建产物**
（`/static/assets/index-CLV_6HAs.css`，56384 字节，`focus-visible` 出现 0 次），
源码 `components.css` 的 U1 区块未进入该 bundle。约束禁止 `npm run build`，本轮无法把 U1
打进产物后在实站复测。

### 2.2 源码 U1 样式注入验证（证明规则本身有效）

用 Playwright `addStyleTag` 注入 `components.css` 的 U1 区块后复测 A2：

| 项 | 结果 |
|---|---|
| 6 个 Tab 焦点 `:focus-visible` | **6/6 true** |
| `outline-width` | **全部 2px** |
| `outline-color` | `rgb(103, 153, 254)` = `--ds-color-brand: #6799fe` |
| 汇总 | **PASS（bad=0）** |

（注：`.sidebar-nav-item` 的 `transition: .2s ease` 会把 `outline-offset` 也纳入过渡，
注入后首帧可能读到 1px 中间值；断言只要求 `outline-width >= 2px`，且 CSS 终值为 2px。）

## 3. 未决项

1. **需一次 `npm run build`（或等价重建静态资产）** 后，在 8787 实站复跑
   `node tools/focus-mobile-check.mjs`，A2 才能在构建产物上转绿。本轮按约束未执行 build。
2. A1 当前 PASS 可能部分依赖既有 `max-width: 900px` 断点 + 本次 `overflow-x: hidden`；
   若后续去掉 `overflow-x: hidden`，需用元素几何（而非仅 `scrollWidth`）复核是否有被裁切内容。
3. `.sidebar-nav-item` 全属性 `transition: .2s ease`（components.css:901）会动画 outline 族属性；
   建议后续收窄为 `transition: background-color .2s ease, color .2s ease`（本轮不改既有规则）。

## 4. 交付清单

| 文件 | 动作 |
|---|---|
| `web/src/styles/components.css` | 末尾追加 U1/U3 区块（只加，未重排既有规则） |
| `web/tools/focus-mobile-check.mjs` | 新增 Playwright 断言脚本 |
| `docs/mimo-web-ux-focus-mobile.md` | 本文件 |
