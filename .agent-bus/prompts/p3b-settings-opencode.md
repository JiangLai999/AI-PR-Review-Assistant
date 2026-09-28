你是本项目的协作 agent（opencode）。**Phase 3b 任务**：把「设置页 / 接口文档页」做**中英双语**。
主控已经写好 i18n 基建（`web/src/i18n/`），你只填词典 + 改页面。

## 已就绪的基建（**不要改**）
```ts
import { useT } from '../i18n'          // 组件内
const t = useT()                         // t('settings.provider.label')
import { t, tn } from '../i18n'          // 非组件代码
// tn(key, count) → key.one / key.other（复数）
```
- 语言来自后端 `preferences.ui_language`（App 启动时 setLang）；
  **另外请你在设置页保存成功后调用 `setLang(result.config.preferences?.ui_language)`**——
  这样"在设置页把界面语言改成 English"能立刻全站生效（这是 Phase 3b 的验收画面之一）。
- 词典按命名空间拆分：**你只填 `web/src/i18n/settings.ts`**；公共词（导航/错误）已在 `shell.ts`。

## 你的范围（write_scope）
1. `web/src/i18n/settings.ts`（zh + en 两份都要写全）
2. `web/src/pages/SettingsPage.tsx`（57 条汉字字面量；含 4 个分组标题、6 个偏好项的 label/hint、
   数值项 label/hint、按钮（校验后保存 / 直接保存 / 重新探测）、保存成功/失败提示、凭证面板）
3. `web/src/pages/ApiPage.tsx`（55 条；端点描述的**中文说明**也要翻：`desc`/`errors` 是展示文案，
   `method`/`path`/`curl`/`body`/`response` 保持英文原样）
4. `docs/DEV_RECORD.md`：key 命名、改动点、前后字面量数字、验证、未决项。

## 约定
- key 命名：`settings.<区域>.<名称>` / `api.<区域>.<名称>`；复数用 `tn(...)` + `.one/.other`；
  插值用 `{name}`。
- 界面语言下拉本身就是 `preferences.ui_language` 的选项（`options.ui_languages`），
  它的 label 由后端提供（"中文 / Chinese"），**不要翻译后端给的 label**。
- **验收口径**：`node web/tools/i18n-coverage.mjs` 里你负责的两个文件汉字字面量应为 **0**。
- 不改 `web/src/i18n/index.ts` / `shell.ts` / 其它命名空间；禁止 git；禁止 `npm run build`；不引依赖。
- 术语统一：provider=供应商；credential=凭证；token=令牌；cost cap=成本上限。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
node tools/i18n-coverage.mjs
```

完成后按总线报告：
`python scripts/agent_bridge.py report p3b-settings --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 前后字面量数字>" --blocker "<未决项，没有写无>"`
