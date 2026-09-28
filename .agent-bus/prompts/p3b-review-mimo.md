你是本项目的协作 agent（mimo）。**Phase 3b 任务**：把「审查工作台 / 历史审查」两个页面做**中英双语**。
范围刻意收窄（只 2 个页面 + 1 个词典文件），请**先写文件、后跑命令**，不要通读全仓（你前几轮卡死都是因为先读一堆）。

## 已就绪的基建（**不要改**）
```ts
import { useT } from '../i18n'    // 组件内
const t = useT()                   // t('review.plan.title')
// 复数：词典里写 review.findings.one / review.findings.other，调用 tn('review.findings', count)
```
语言由 App 统一管理（来自后端 `preferences.ui_language`），**你不需要**加语言开关或读配置。
公共词（导航/状态栏/页脚/接口错误）已在 `web/src/i18n/shell.ts`，不要重复定义。

## 你的范围（write_scope）
1. `web/src/i18n/review.ts`：写全你两个页面用到的 key（**zh + en 两份都要有**）
2. `web/src/pages/ReviewPage.tsx`（56 条汉字字面量：标题、两种模式卡、进度控制台、证据摘要、
   筛选器、结果区分组、按钮与提示）
3. `web/src/pages/HistoryPage.tsx`（12 条：表头、统计、按钮、空态）
4. `docs/mimo-i18n-review-pages.md`：key 清单（按页面分组）、改动点 file:line、前后字面量数字、验证、未决项

## 纪律（避免卡死）
- 顺序：**先写 `review.ts`（可以边看页面边补 key）→ 再改两个页面 → 再跑命令 → 最后写文档与报告**。
- 每个文件写完立刻保存；不要做"先通读全仓"的动作；最多 grep 3 次。
- 目标 25 分钟内完成；typecheck 失败最多修 3 轮，仍失败就如实报告阻塞。

## 约定
- key 命名：`review.<区域>.<名称>` / `history.<区域>.<名称>`；复数用 `.one/.other`；插值 `{name}`。
- **验收口径**：`node web/tools/i18n-coverage.mjs` 里 `ReviewPage.tsx` 与 `HistoryPage.tsx` 汉字字面量应为 **0**。
- 不改 `web/src/i18n/index.ts` / `shell.ts` / 其它命名空间；禁止 git；禁止 `npm run build`；不引依赖。
- 术语：finding=发现；severity=严重度；evidence=证据；plan=审查计划；workbench=工作台。

## 验证（必须真跑，报数字）
```bash
cd web && npm run typecheck
node tools/i18n-coverage.mjs
```

完成后按总线报告：
`python scripts/agent_bridge.py report p3b-review --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + typecheck 结果 + 前后字面量数字>" --blocker "<未决项，没有写无>"`
