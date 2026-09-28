# Phase 3b · 设置页 / 接口页 中英双语（agent: opencode）

任务 `p3b-settings`。范围：`write_scope` 内 4 个文件，未改 `web/src/i18n/index.ts` / `shell.ts`
及其它命名空间，未做任何 git 操作。

## 1. key 命名

词典全部落在 `web/src/i18n/settings.ts`（zh + en 各 165 条，两侧 key 集合完全一致，无重复）。

| 前缀 | 归属 | 例子 |
| --- | --- | --- |
| `settings.<区域>.<名称>` | SettingsPage.tsx | `settings.numeric.costRun.label` |
| `api.<区域>.<名称>` | ApiPage.tsx | `api.endpoint.plan.desc` / `api.cli.run` |
| `api.error.*` | **shell.ts（已有，本任务直接复用，未重复定义）** | `api.error.offline` / `api.error.nonJson` |

约定：

- 控件常量只存 key（`STAGE_*_KEY` / `NUMERIC_FIELDS.labelKey` / `Group.titleKey` / `Endpoint.descKey`），
  渲染时 `t(key)` 取词，语言切换即时重渲染；模块级常量不调 `t()`。
- 插值用 `{name}`：`t('settings.cost.range', { min, max })`。
- 本任务没有复数场景，未使用 `tn(...)`。
- 术语统一：provider=供应商；credential=凭证；token=令牌；cost cap=成本上限。
- 界面语言下拉的 option 文案来自后端 `options.ui_languages`，按要求**未翻译**。

## 2. 改动点

### `web/src/i18n/settings.ts`（原为空壳，新增 165×2 条）

分区块：页面骨架/阶段徽标、数值项×6、布尔项×2、6 个偏好项 label+hint、两个偏好分组、
读写提示、凭证健康面板、模型服务与凭证、成本与并发、保存；接口页的分组、字段标签、入参、
19 条端点 `desc` + 12 条 `errors` + 含中文的 `response/body/curl`、静态资源、CLI 对照、运行边界。

### `web/src/pages/SettingsPage.tsx`（805 → 832 行）

- `import { setLang, t, useT } from '../i18n'`；组件内 `useT()`，模块级 `postConfig()` 用 `t()`。
- `STAGE_*` / `UNSUPPORTED_TEXT` / `NUMERIC_FIELDS` / `BOOL_FIELDS` / `INTERFACE_FIELDS` /
  `REVIEW_FIELDS` 全部由「汉字字面量」改为「key 字段」。
- `StatusPill` / `PreferenceSelect` / `PreferenceGroup` / `SettingsPage` 各自 `useT()`。
- 错误文案 `读取配置失败 / 探测失败 / 保存失败（HTTP n）/ 保存失败：服务端拒绝…` 进词典；
  连接与非 JSON 两条直接复用 shell.ts 的 `api.error.offline` / `api.error.nonJson`（文案本就相同）。
- **验收画面**：`save()` 成功分支在 `hydrate(result.config)` 之后新增
  `setLang(result.config.preferences?.ui_language)`（SettingsPage.tsx:445），
  于是「在设置页把界面语言改成 English」保存后立刻全站生效。

### `web/src/pages/ApiPage.tsx`（409 → 337 行）

- 类型改为「文案字段存 key」：`descKey` / `inputKey` / `errorsKey` / `responseKey` / `bodyKey` / `curlKey`；
  纯英文技术示例 `path` / `body` / `response` / `curl` 按要求保持原样。
- 5 条原本混入中文的示例（`/api/review` response、`/api/jobs/{id}/cancel` response、
  `/api/report/export` response、`/api/config` response、`/api/chat` body + curl）
  进词典：中文保持原文，英文给等义译文。
- `CLI` 表与新增 `BOUNDARIES` 常量改为 `[key, key]`；静态资源段落按 4 段 key 拆分以保留
  `<span className="mono">` 内联样式。

### `docs/opencode-i18n-settings.md`

即本文档。

## 3. 前后汉字字面量

口径：`node web/tools/i18n-coverage.mjs`（只统计**非注释**字符串字面量，注释与 JSX 纯文本子节点不计）。

| 文件 | 改动前 | 改动后 |
| --- | --- | --- |
| `web/src/pages/SettingsPage.tsx` | **57** | **0** |
| `web/src/pages/ApiPage.tsx` | **55** | **0** |

补充口径（JSX 纯文本子节点如 `<h1>设置</h1>`、`<th>命令</th>` 不进上面的计数，
但同样已翻译）：用 `rg -n '[一-鿿]'` 复核两个文件，剩余 CJK **只出现在注释里**，正文 0 条。

## 4. 验证（真跑结果）

```bash
cd web && npm run typecheck        # tsc --noEmit → 通过，0 error
node tools/i18n-coverage.mjs
# files scanned: 20 / files with CJK literals: 0 / CJK string literals: 0
# I18N_AUDIT {"files":20,"filesWithCjk":0,"literals":0,"top":[]}
```

词典自检（`.pytest_opencode/check_dict.mjs`，gitignored 临时脚本）：

```
zh keys: 165  en keys: 165
dup in zh: []   dup in en: []
missing in en: []   missing in zh: []
cross-namespace duplicate keys: []
```

## 5. 未决项

1. **保存成功提示 `result.message`** 与 **凭证面板 `item.label` / `item.detail` / `item.fix_hint`**
   都是后端 `/api/config`、`/api/credentials` 返回的中文文案，未翻译 —— 后端不在 `write_scope`。
   英文界面下这三处仍会显示中文，需后续后端 i18n（按 `ui_language` 下发）。
2. **工具口径**：执行期间 `web/tools/i18n-coverage.mjs` 被并行任务改动（新增排除 `web/src/i18n/`），
   且其词法扫描把 `/static/*` 里的 `/*` 当作块注释，会吞掉该行之后的全部内容
   （旧版 ApiPage 从第 344 行起不再计数）。因此「改动前 57/55」是该工具当次的真实输出，
   「改动后 0/0」另用逐字面量清单 + `rg` 全量 CJK 复核交叉确认，不只依赖单一工具。
3. 原 JSX 跨行中文（设置页 lead、保存说明）折行处会渲染出一个多余空格，词典里合并成整句后该空格消失
   （中文排版更正确，英文按语义补空格），属刻意微调。
4. 未运行 `npm run build`（任务禁止），也未做 UI 截图回归；改动仅 `tsc --noEmit` + 覆盖率脚本验证。
