# Phase 3b · 概览 / 准确率 / 离线演示 中英双语（claude）

任务：`p3b-overview`。范围（write_scope）内 5 个文件，全部为**字典填充 + 页面取词**，未改基建、未加依赖、未做 git 操作。

| 文件 | 动作 |
| --- | --- |
| `web/src/i18n/overview.ts` | 新填 114 个 key × 2 语言（原为空壳 `{}`） |
| `web/src/pages/OverviewPage.tsx` | 全部中文文案改走 `t()` / `tn()` |
| `web/src/pages/BenchmarkPage.tsx` | 同上 |
| `web/src/components/DemoPanel.tsx` | 同上 |
| `docs/claude-i18n-overview.md` | 本文档 |

## 1. key 命名规则

- `overview.<区域>.<名称>` / `benchmark.<区域>.<名称>`，全小写点分，**禁止中文 key**。
  区域示例：`overview.hero.*`、`overview.trust.*`、`overview.pipeline.*`、`overview.capabilities.*`、
  `overview.snapshot.*`、`overview.accuracy.*`、`overview.cli.*`、`overview.demo.*`、
  `benchmark.hero.*`、`benchmark.strategy.*`、`benchmark.metric.*`、`benchmark.matrix.*`、`benchmark.cases.*`、`benchmark.note.*`。
- 序号段用数字：`overview.pipeline.1.title` … `overview.pipeline.8.title`（卡片列表，顺序即语义）。
- **复数**用 `tn('key', count)`，词典里成对写 `key.one` / `key.other`。本批次用到 3 组：
  - `overview.hero.console.findings.{one,other}` → `{count} 条 · {duration}` / `{count} finding(s) · {duration}`
  - `overview.accuracy.cases.{one,other}` → `{count} 个样例` / `{count} sample(s)`
  - `benchmark.matrix.cases.{one,other}` → `{count} 个样例合计` / `{count} sample(s) in total`
- **插值**写 `{name}`：如 `t('overview.snapshot.runsHint', { count })`、`t('benchmark.metrics.title', { strategy })`。

### 边界与复用（需要主控知晓的一个决定）

概览页的「基准测试结果」预览块展示的就是 benchmark 报告本身，指标术语（精确率 / 召回率 / F1 / 误报率 / 行号准确率）
与准确率页完全同义。为避免同一术语出现两份文案来源，该预览块**直接复用 `benchmark.metric.*`**（`web/src/pages/OverviewPage.tsx:319-375`）。
`benchmark.*` 属于本命名空间（`overview.ts`），不跨文件、不跨 agent。

未与 `shell.ts` 冲突：`shell.ts` 只有 `app.*` / `nav.*` / `api.error.*`；本批次只用 `overview.*` / `benchmark.*`。
实跑校验（见 §4.4）：5 个命名空间合并后 **duplicate key = 0**。

## 2. 改动点（file:line）

### 2.1 `web/src/i18n/overview.ts`（332 行，114 key × zh/en）

原文件是空壳（`'zh-CN': {}, 'en-US': {}`）。现按上方命名规则填满，zh / en **逐 key 对齐**，key 集合完全一致（校验见 §4.4）。

### 2.2 `web/src/pages/OverviewPage.tsx`

| 位置（改后行号） | 改动 |
| --- | --- |
| `:8` | `import { tn, useT } from '../i18n'` |
| `:12-33` | `CAPABILITIES` / `TRUST_POINTS` / `PIPELINE` 三个模块级数组由「中文文案」改成「key 数组」（`titleKey` / `bodyKey`）；`tag`（`ReviewPlanner` 等代码标识）保持字面量 |
| `:40` | `const t = useT()`（紧随 `onNavigate` 之后、`useRef` 之前） |
| `:95-117` | 首屏 eyebrow / 两行主标题 / lead / 两个 CTA 按钮 → `t()` |
| `:125` | 控制台 `aria-label` → `overview.hero.consoleAria` |
| `:152-154` | `{n} 条 · {时长}` → `tn('overview.hero.console.findings', n, { duration })` |
| `:168` | 空态「还没有审查记录」→ `t()` |
| `:182-197` | 信任条 `aria-label` + 标题 + 4 条要点（数组取词） |
| `:202-244` | SNAPSHOT：区块标题、错误提示（插值 `{detail}`）、6 个指标 label + hint（hint 含 `{count}` / `{recall}` 插值） |
| `:246-284` | PIPELINE：区块标题 + 8 张卡片标题/正文 |
| `:285-318` | CAPABILITIES：区块标题 + 6 张卡片标题/正文 |
| `:317-374` | ACCURACY 预览：标题 / 描述 / 「查看明细 →」/ `{strategy} 策略` / `tn(样例数)` / 5 个指标（复用 `benchmark.metric.*`）/ 免责说明 |
| `:376-402` | CLI：区块标题、「命令行」「本地 HTTP 接口」、第二个 `<pre>` 的 6 行带中文注释的接口清单（整块进词典 `overview.cli.endpoints`，用 `\n` 保留换行）；第一个 `<pre>` 纯命令、无汉字，保持字面量 |

**汉字字面量：61 → 0。** 文件内仅剩 3 处中文**注释**（`:11`、`:46-47`），工具口径明确排除注释。

### 2.3 `web/src/pages/BenchmarkPage.tsx`

| 位置（改后行号） | 改动 |
| --- | --- |
| `:5` | `import { tn, useT } from '../i18n'` |
| `:9-17` | `STRATEGY_LABEL`（中文直写）→ `STRATEGY_KEYS`（策略名/说明存 key）；后端若返回未知策略，回落显示原始 `name` |
| `:32` | `const t = useT()` |
| `:62-63` | `selectedLabel`：把「当前选中的策略」先取词，供区块标题插值 |
| `:69-70` | 页头 `<h1>` / lead |
| `:89-91` | `Empty` 标题 + 正文（未连接服务） |
| `:95`、`:106`、`:118`、`:152` | STRATEGY 区块标题、策略卡片名/「当前」Chip/说明、卡内精确率·召回率小标 |
| `:166-206` | METRICS 区块标题（`{strategy} · 指标`）+ 6 个指标 label/hint + 混淆矩阵卡片标题 + `tn(样例合计)` + TP/FP/FN |
| `:228-231`、`:250`、`:274-295` | CASES 区块标题、表头（样例 / 精确率 / 召回率；`TP`/`FP`/`FN`/`F1` 为纯 ASCII，保持字面量）、「对照组」Chip |
| `:313-315` | 结尾说明段落拆 3 段 key（`body` + `<strong>emphasis</strong>` + `tail` 标点），保住原来的加粗强调 |

**汉字字面量：21 → 0。** 仅剩 3 处中文注释（`:8`、`:23-24`）。

### 2.4 `web/src/components/DemoPanel.tsx`

| 位置（改后行号） | 改动 |
| --- | --- |
| `:4`、`:7` | 引入并使用 `useT` |
| `:31` | `aria-label="离线演示"` → `t('overview.demo.aria')` |
| `:34-35` | `<h2>` 标题、`<p>` 说明 |
| `:41` | 「运行中…」/「运行离线演示」 |
| `:48` | 空态「选择案例并运行」「结果会在这里展示」 |

**汉字字面量：3 → 0**（工具只统计字符串字面量）。另有 **4 处 JSX 文本子节点**（`<h2>`、`<p>`、空态 `<b>`/`<small>`）同样含汉字，
审计工具不统计 JSX 文本（见 `docs/mimo-i18n-audit.md` §6 已声明的局限），本次一并迁进词典；改后该文件**全文已无任何汉字**（除 0 条注释）。

## 3. 翻译口径

- 术语统一按约定：audit=审查、finding=发现、workbench=工作台、evidence=证据、plan=审查计划。
  落地用词：`Review runs`（历史审查）、`Findings`（发现问题）、`Evidence chain validation`（证据链校验）、
  `review pipeline`（审查流水线）、`Deterministic rules`（确定性规则）。
- 已是英文的产品词（`ReviewPlan`、`tree-sitter`、`SQLite`、`F1`、`TP/FP/FN`、`last.run`、`DEMO RESULT`）中英都保留原样。
- 中文里的全角标点在英文版改用半角；中英标点分属不同 key 的只有 `benchmark.note.tail`（`。` / `.`）。

## 4. 验证（实跑记录）

### 4.1 类型检查

```console
$ cd web && npm run typecheck
> ai-pr-review-web@0.1.0 typecheck
> tsc --noEmit
```

退出码 0，无任何诊断输出（`strict` + `noUnusedLocals` + `noUnusedParameters` 全开）。

### 4.2 i18n 覆盖度审计（官方工具）

**改前**（`node web/tools/i18n-coverage.mjs`，2026-09-27T10:50:26Z）：

```console
files scanned: 25 / files with CJK literals: 15 / CJK string literals: 361
   1. web/src/pages/OverviewPage.tsx  61
   7. web/src/pages/BenchmarkPage.tsx  21
   (DemoPanel 未进 Top 10，工具口径为 3 条)
```

**改后（终验）**，2026-09-27T10:54:10Z：

```console
$ node web/tools/i18n-coverage.mjs
files scanned: 20 / files with CJK literals: 9 / CJK string literals: 211
Top 10: SettingsPage 57 | ReviewPage 56 | ApiPage 55 | ReviewPanels 15 | HistoryPage 12
        | FindingCard 6 | ui.tsx 4 | ErrorBoundary 3 | lib/format.ts 3
```

**`OverviewPage.tsx` / `BenchmarkPage.tsx` / `DemoPanel.tsx` 三个文件均已从 Top 列表消失，Top 列表与这三个文件无关。**
（等价于任务书里的 `| findstr /C:"OverviewPage" /C:"BenchmarkPage" /C:"DemoPanel"`：无任何匹配行。）

三点说明（如实记录）：

- **审计工具在本次任务进行中被主控更新过**：新版 `web/tools/i18n-coverage.mjs:38-42` 递归时跳过 `web/src/i18n/`
  （理由写在源码注释里：词典本身含中文，不排除会导致「一边翻译、总量反而上涨」）。
  我改到一半时的中间态跑出过 `literals: 498`（`overview.ts` 117 + 其它 agent 新建的 `components.ts` 131 被计入），
  工具更新后这部分不再计入，全局数字回到真实下降通道（361 → 211，其余降幅来自同时在收尾的其它 agent）。
- 上面「改前」的 361 / 61 / 21 是在工具更新**之前**跑的，与本批次验收口径一致（三个页面文件的字面量数）。
- 本次运行与其它 agent 的文件改动并发，全局数字会随他们的进度变化；与验收相关的只有三个文件的 **0 / 0 / 0**。

为拿到三个文件的精确数字（官方工具只打印 Top 10），用了一份**镜像同规则**的临时脚本（放在仓库外 `%TEMP%`，只读仓库文件）：

```
OverviewPage.tsx  61 → 0
BenchmarkPage.tsx 21 → 0
DemoPanel.tsx      3 → 0
```

另外用 `rg '[一-鿿]'` 全文件（含 JSX 文本、含注释）复查：三个文件里的汉字只剩
`OverviewPage.tsx:11,46,47` 与 `BenchmarkPage.tsx:8,23,24` 共 6 行，**全部是 `//` / `/** */` 注释**，无任何用户可见文案。

### 4.3 中英抽样对照（3 组，验证「英文 key 缺失回落中文」）

抽取方式：`import()` 词典对象后直接读 key（Node 24 原生类型擦除），非肉眼比对：

| key | zh-CN | en-US |
| --- | --- | --- |
| `overview.hero.titleLine1` | 把 GitHub PR 审查 | Turn GitHub PR review into |
| `overview.trust.p1.title` | 先规划 | Plan first |
| `overview.demo.run` | 运行离线演示 | Run offline demo |
| `benchmark.metric.precision` | 精确率 | Precision |
| `benchmark.cases.control` | 对照组 | Control |
| `overview.accuracy.strategy` | `{strategy} 策略` | `{strategy} strategy` |

### 4.4 词典自检（额外做实的两项）

1. **zh/en 逐 key 对齐**（`overview.ts`）：`zh=114 en=114 missingEn=0 missingZh=0`。
2. **跨命名空间重复 key**：合并 `shell.ts` / `overview.ts` / `settings.ts` / `review.ts` / 其它 agent 新建的 `components.ts`，
   首次校验 `total keys=275 duplicateKeys=0`；终验重跑（其它 agent 又填了 `review.ts`）`total keys=386 duplicateKeys=0`
   —— dev 模式下不会触发 `[i18n] duplicate key` 告警。
3. **key 引用完整性**：解析三个页面里全部 `t('...')` / `tn('...')` 调用（含经数组间接取词的 key），
   `used keys: t=66 tn-forms=6 missing=0` —— 不存在「key 拼错导致渲染出原始 key 或回落中文」的情况。

## 5. 未决项与局限

- **未做浏览器渲染验证**。本批次只跑了类型检查 + 静态审计 + 词典自检，没有起 dev server 截图对比中英两版视觉
  （同时段其它 agent 正在改 `web/src`，dev server 会混入他们未完成的状态）。若主控需要视觉验收，建议在 Phase 3b 全部合流后统一跑一次。
- **`tn()` 的英文单复数只覆盖到「1 / 非 1」**：`0 findings`（"0 findings" 正确）、`1 finding` 正确；中文两条文案相同，符合预期。
- 概览页 ACCURACY 预览块复用 `benchmark.metric.*`（理由见 §1），若主控希望严格按页面前缀隔离，需要拆成 5×2 条新 key。
- `BenchmarkPage` 的 `TP` / `FP` / `FN` / `F1` 表头与卡片内的小标为纯 ASCII，未进词典（中英一致，无翻译必要）。
- 词典里的中文标点（`，`、`。`、`·`）在英文版按英文习惯改写；`benchmark.note` 因为要保住 `<strong>` 强调被拆成 3 个 key，
  若后续要调整句子结构，需同步改这两处。
