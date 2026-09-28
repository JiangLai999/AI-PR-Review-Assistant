你是本项目的协作 agent（mimo）。**Phase 2 的 UX 收尾任务**，范围刻意做小（上两轮你两次卡死，
这次请严格遵守"先写文件、后跑命令"的节奏，不要通读全仓）。

## 只做两件事（都是你提案 §3.1 的 U1/U3）
### U1 · 键盘焦点可见
- 现状：`web/src/styles/components.css` 里表单控件/按钮的 `:focus-visible` 样式不完整
  （Tab 走到下拉/按钮时看不出焦点在哪）。
- 要做：给 `button` / `select` / `input` / `[role="button"]` / 链接补**统一**的 `:focus-visible`
  样式（2px 描边 + 2px offset，颜色用现有 design token `--ds-color-*`，不要写死 hex），
  并保证 `:focus:not(:focus-visible)` 不显示描边（鼠标点击不脏）。

### U3 · 窄屏（390px）导航不截断
- 现状：`web/src/App.tsx:161` 附近的侧栏/状态栏在 390px 下会挤掉标签或溢出。
- 要做：**只改 CSS**（不要改 App.tsx）——在 `components.css` 的媒体查询里让
  `.workspace-sidebar` 在 `max-width: 720px` 变成顶部横向条（品牌 + 图标 + 可横向滚动），
  `.workspace-statusbar` 允许换行且不截断文字；保证 390px 下不出现横向滚动条。

## 交付
1. `web/src/styles/components.css`：上述样式（**只加，不重排既有规则**，放在文件末尾的新区块并注明 U1/U3）。
2. `web/tools/focus-mobile-check.mjs`（新，Playwright）：对 `http://127.0.0.1:8787/` 跑两条断言
   - 390×844 视口：`document.documentElement.scrollWidth <= 390 + 1`（无横向溢出）；
   - 1440×900 视口：Tab 遍历 `/api` 页或 `/settings` 页的前 6 个可聚焦元素，每个都命中
     `:focus-visible`（用 `element.matches(':focus-visible')`）且 `outline-width >= 2px`。
   脚本要以 `process.exitCode = 1` 报失败，并打印每条断言的 PASS/FAIL。
3. `docs/mimo-web-ux-focus-mobile.md`：改动点、两条断言的实测数字、未决项。

## 纪律（避免再卡死）
- 不要读 `src/ai_pr_review/**`，不要读 `web/src/pages/**`；只看 `web/src/styles/components.css` 与 `web/src/App.tsx` 的**局部**（最多各读一次）。
- 先写 `components.css` → 再写 `web/tools/focus-mobile-check.mjs` → 再跑脚本 → 最后写文档与报告。
- 目标 15 分钟内完成；如果某条断言在你的环境里跑不了（例如浏览器没装），就**如实写未确认**并照常交付文件，
  不要反复重试超过 2 次。

## 约束
- 只写：`web/src/styles/components.css`、`web/tools/focus-mobile-check.mjs`、`docs/mimo-web-ux-focus-mobile.md`；
- 禁止改 TSX/TS、禁止改 `src/ai_pr_review/**`、禁止 git；禁止 `npm run build`；禁止读取/输出凭据。

完成后按总线报告：
`python scripts/agent_bridge.py report p2-ux --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + 断言数字>" --blocker "<未决项，没有写无>"`
