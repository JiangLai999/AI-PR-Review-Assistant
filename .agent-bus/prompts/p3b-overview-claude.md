你是本项目的协作 agent（claude）。**Phase 3b 任务**：把「概览 / 准确率 / 离线演示」这三块做**中英双语**。
主控已经把 i18n 基建写好并提交（`web/src/i18n/`），你只需**填词典 + 改页面**。

## 已就绪的基建（**不要改**）
```ts
// web/src/i18n/index.ts —— 运行时
export function useT(): (key: string, vars?: Record<string, string|number>) => string
export function t(key: string, vars?): string      // 非组件代码用
export function tn(key: string, count: number, vars?): string   // 复数：key.one / key.other
export function setLang(value: unknown): void
```
- 组件里：`import { useT } from '../i18n'` → `const t = useT()` → `t('overview.hero.title')`。
- 语言来自后端 `preferences.ui_language`，由 App 启动时 `setLang`，设置页保存后也会 `setLang`；
  你**不需要**自己读配置或加语言开关。
- 词典按命名空间拆分：**你只填 `web/src/i18n/overview.ts`**（`{ 'zh-CN': {...}, 'en-US': {...} }`）。
  所有 agent 共用的 key 已在 `shell.ts`（导航/状态栏/页脚/通用错误），**不要重复定义**（重复 key 在 dev 下会告警）。

## 你的范围（write_scope）
1. `web/src/i18n/overview.ts`：填写你页面用到的**全部** key（zh + en 两份都要）。
2. `web/src/pages/OverviewPage.tsx`（审计：61 条汉字字面量）
3. `web/src/pages/BenchmarkPage.tsx`（21 条）
4. `web/src/components/DemoPanel.tsx`（少量）
5. `docs/DEV_RECORD.md`：key 命名规则、改动点 file:line、前后字面量数字、验证、未决项。

## 约定
- key 命名：`overview.<区域>.<名称>` / `benchmark.<区域>.<名称>`（小写点分，禁止中文 key）。
- 复数用 `tn('overview.demo.cases', count)`，并在词典里写 `overview.demo.cases.one` / `.other`。
- 插值用 `{name}`：`t('overview.snapshot.runs', { count })`。
- **验收口径**：改完后 `node web/tools/i18n-coverage.mjs` 里你负责的三个文件汉字字面量应为 **0**
  （注释不算，工具已排除注释）；中文文案一律进词典，TSX 里只留 key。
- 不引入新依赖；不改 `web/src/i18n/index.ts` / `shell.ts` / 其它命名空间文件；禁止 git；禁止 `npm run build`。
- 术语统一：audit=审查；finding=发现；workbench=工作台；evidence=证据；plan=审查计划。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
node tools/i18n-coverage.mjs | findstr /C:"OverviewPage" /C:"BenchmarkPage" /C:"DemoPanel"   # 期望：不再出现在 Top 列表
```
并从中英两份词典各抽 3 条对照，确认没有"英文 key 缺失回落中文"的情况（可在文档里贴 key→两句文案的对照）。

完成后按总线报告：
`python scripts/agent_bridge.py report p3b-overview --agent claude --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 前后字面量数字>" --blocker "<未决项，没有写无>"`
