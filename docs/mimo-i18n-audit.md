# i18n 覆盖度审计报告（Phase 3 前期）

- 工具：`web/tools/i18n-coverage.mjs`（Node，仅依赖 `node:fs` / `node:path`，只读，不改源码）
- 扫描范围：`web/src/**/*.ts`、`web/src/**/*.tsx`
- 实跑命令：`node web/tools/i18n-coverage.mjs`
- 生成时间（脚本输出）：`2026-09-27T10:12:07.767Z`
- 退出码：0（审计工具，不作门禁）

## 1. 总量

| 指标 | 数值 |
| --- | ---: |
| 扫描文件数（.ts/.tsx） | 20 |
| 含中日韩汉字字面量的文件数 | 16 |
| 含中日韩汉字的字符串字面量总数 | 350 |
| 无汉字字面量的文件数 | 4 |

## 2. Top 10 文件（按汉字字面量数）

| # | 文件 | 字面量数 |
| ---: | --- | ---: |
| 1 | `web/src/pages/OverviewPage.tsx` | 61 |
| 2 | `web/src/pages/SettingsPage.tsx` | 57 |
| 3 | `web/src/pages/ReviewPage.tsx` | 56 |
| 4 | `web/src/pages/ApiPage.tsx` | 51 |
| 5 | `web/src/components/ReportActions.tsx` | 26 |
| 6 | `web/src/components/AskPanel.tsx` | 21 |
| 7 | `web/src/pages/BenchmarkPage.tsx` | 21 |
| 8 | `web/src/components/ReviewPanels.tsx` | 15 |
| 9 | `web/src/pages/HistoryPage.tsx` | 12 |
| 10 | `web/src/App.tsx` | 9 |

Top 3 合计 174 条，约占总量 49.7%；Top 10 合计 329 条，约占 94.0%。
翻译量高度集中在 4 个主页面（Overview / Settings / Review / Api，合计 225 条 ≈ 64%）。

机器可读行（脚本 stdout）：

```
I18N_AUDIT {"files":20,"filesWithCjk":16,"literals":350,"top":[{"file":"web/src/pages/OverviewPage.tsx","count":61},{"file":"web/src/pages/SettingsPage.tsx","count":57},{"file":"web/src/pages/ReviewPage.tsx","count":56},{"file":"web/src/pages/ApiPage.tsx","count":51},{"file":"web/src/components/ReportActions.tsx","count":26},{"file":"web/src/components/AskPanel.tsx","count":21},{"file":"web/src/pages/BenchmarkPage.tsx","count":21},{"file":"web/src/components/ReviewPanels.tsx","count":15},{"file":"web/src/pages/HistoryPage.tsx","count":12},{"file":"web/src/App.tsx","count":9}],"generatedAt":"2026-09-27T10:12:07.767Z"}
```

## 3. 噪音排除规则（脚本实现）

计数前先剔除以下内容，只有「含汉字且非噪音」的字符串字面量才计入：

1. **注释**：`// ...` 与 `/* ... */` 在词法扫描阶段直接跳过，注释里的汉字永不进入计数。
2. **`import` / `export` 行**：字面量所在物理行匹配 `^\s*(import|export)\b` 时整条跳过（模块路径、re-export 名等）。
3. **接口 / 锚点字符串**：内容 trim 后以 `/api` 或 `#` 开头的字符串（路由、hash、CSS id 选择器）跳过。
4. **纯类名 / 标识符**：内容整体匹配
   - `^[A-Za-z_][A-Za-z0-9_:-]*$`（如 `st-valid`、`data-testid` 值），或
   - `^[A-Za-z_][A-Za-z0-9_:\-.]*(\s+[A-Za-z_][A-Za-z0-9_:\-.]*)*$`（空格分隔的 class 列表，如 `btn-primary`、`btn btn-primary is-active`）  
   的字符串跳过。此类串本身不含汉字，规则用于防御性过滤，避免未来混入 CJK 时误计。
5. **测试 / 文档目录**：递归时跳过名为 `docs`、`__tests__`、`test`、`tests` 的目录，以及文件名匹配 `*.test.ts(x)` / `*.spec.ts(x)` 的文件。

## 4. 建议先翻的 3 个文件

推荐顺序按「先打通基建 → 再吃掉体量」：

1. **`web/src/App.tsx`（9 条）** —— 体量最小，用来落地词典结构 + `t()` hook + 语言切换状态，改动面可控，适合当 spike。
2. **`web/src/pages/HistoryPage.tsx`（12 条）** —— 第一个完整页面迁移，验证「页面级批量替换」的流程与回归方式。
3. **`web/src/pages/OverviewPage.tsx`（61 条）** —— 体量最大的页面，在前两步模式已验证后一次性吃掉，约占总量 17%，投入产出比最高。

备选：若主控更希望先覆盖用户感知最强的主流程，可将第 3 步换成 `web/src/pages/ReviewPage.tsx`（56 条）。

## 5. 全站 i18n 建议落地顺序

1. **词典（dictionary）**  
   先定 key 命名规范（建议 `page.section.element` / `common.*`），建 `web/src/i18n/shell.ts`（首个命名空间，源语言）。把 `App.tsx` 的 9 条抽成 key，证明结构可行。**已实现**：不再是单文件 zh-CN.ts/en-US.ts，而是按命名空间拆成 `web/src/i18n/shell.ts`、`web/src/i18n/overview.ts`、`web/src/i18n/settings.ts`、`web/src/i18n/review.ts`、`web/src/i18n/components.ts`，由 `web/src/i18n/index.ts` 汇总，每个文件内同时存 zh-CN 与 en-US 两份词典。
2. **hook（`useT` / `t()`）**  
   提供 `t(key, vars?)` 与语言上下文（React Context + `localStorage` 持久化）。要求：缺 key 时回退源语言并可在 dev 模式告警；支持插值（`{name}`）。hook 落地后立即在 `App.tsx` 回归。
3. **按页面分批迁移**  
   按 Top 10 分批，建议批次：
   - 批次 1：`App.tsx` + `HistoryPage.tsx`（基建 spike，约 21 条）
   - 批次 2：`OverviewPage.tsx` + `SettingsPage.tsx`（约 118 条）
   - 批次 3：`ReviewPage.tsx` + `ApiPage.tsx`（约 107 条）
   - 批次 4：组件层 `ReportActions` / `AskPanel` / `ReviewPanels`（约 62 条）
   - 批次 5：`BenchmarkPage.tsx` 与其余零散文件（约 42 条）
   每批跑一遍现有 UI/验收脚本后再进下一批；组件层放后面是因为它们多被页面 props/文案调用方牵制。

## 6. 已知局限（如实记录）

- **只统计字符串字面量**（`"..."` / `'...'` / `` `...` ``）。TSX 里作为 JSX 文本子节点的汉字（如 `<div>中文</div>`）**未计入**，实际待翻译量高于本报告数字。建议落地词典时补一轮 JSX text 提取，或迁移时人工扫一遍页面文案。
- 模板字符串内部 `${...}` 插值中的嵌套字符串按字面量主体处理，未单独拆分（对汉字计数影响可忽略）。
- 正则字面量中的内容未扫描（汉字出现在正则里的情况极少）。
- `docs/` 与测试目录按排除规则跳过；`web/src` 下若无此类目录则规则不生效。
- 本报告数字来自一次实跑（2026-09-27），脚本可复跑；源码变动后请以新一次 `I18N_AUDIT` 行为准。
