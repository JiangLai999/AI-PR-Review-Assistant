# Phase 3b — 审查工作台 / 历史审查 中英双语

Agent: mimo · Task: `p3b-review` · 范围仅限 write_scope 四个文件。

## 1. 改动点（file:line）

### `web/src/i18n/review.ts`（新建填充）
- 112 个 key × zh/en 两份（`review.*` 79 + `history.*` 33）
- 命名：`review.<区域>.<名称>` / `history.<区域>.<名称>`；复数 `history.findings.one/.other`；插值 `{count}` `{file}` `{done}` `{total}` `{duration}` `{level}` `{name}` `{id}`

### `web/src/pages/ReviewPage.tsx`
| 位置 | 改动 |
|---|---|
| `ReviewPage.tsx:28` | 引入 `useT` |
| `ReviewPage.tsx:40-70` | `EVIDENCE_TEXT` → `EVIDENCE_KEYS`；`RUN_STEPS` / `STEPS` 改为 key 引用 |
| `ReviewPage.tsx:94` | 组件内 `const t = useT()` |
| `ReviewPage.tsx:160-374` | 运行状态文案（计划/完整审查/进度/失败/取消/停止）全部走 `t()` |
| `ReviewPage.tsx:361` | 离线判定改为 `ApiError.status === 0` 标记（原 `message.includes('无法连接')` 依赖中文） |
| `ReviewPage.tsx:410-498` | 页头、表单、模式卡、按钮、费用提示 |
| `ReviewPage.tsx:525-572` | 进度控制台步骤条、计划/审查提示、错误恢复 |
| `ReviewPage.tsx:592-662` | 风险总览指标、证据摘要、作者/外链 |
| `ReviewPage.tsx:671-810` | 区块标题、空态、筛选器、复制 |
| `ReviewPage.tsx:825-829` | 新手引导三步 |

### `web/src/pages/HistoryPage.tsx`
| 位置 | 改动 |
|---|---|
| `HistoryPage.tsx:21` | 引入 `useT, tn` |
| `HistoryPage.tsx:22` | 组件内 `const t = useT()` |
| `HistoryPage.tsx:65-66` | 页头标题与导语 |
| `HistoryPage.tsx:75-82` | 聚合统计 4 个 label（critical/high 为严重度英文名，保留） |
| `HistoryPage.tsx:88-120` | 运行记录标题、刷新、表头 6 列 |
| `HistoryPage.tsx:104-107` | 空态 |
| `HistoryPage.tsx:162` | 查看报告按钮 |
| `HistoryPage.tsx:177-199` | 报告标题（插值 `{id}`）、收起、4 个指标、审查摘要 |
| `HistoryPage.tsx:189` | `{n} 条发现` → `tn('history.findings', n)` |

## 2. 前后字面量数字

| 文件 | 前 | 后 |
|---|---|---|
| `web/src/pages/ReviewPage.tsx` | **56** | **0** |
| `web/src/pages/HistoryPage.tsx` | **12** | **0** |
| `web/src/i18n/review.ts` | 0 key（空壳） | 112 key × 2 语言 |

全仓 CJK 字面量：573 → 112（其余在 SettingsPage/ApiPage 等他方范围）。

## 3. 验证（真实运行）

```bash
cd web
node tools/i18n-coverage.mjs   # ReviewPage.tsx=0, HistoryPage.tsx=0  ✅ 验收达成
npm run typecheck              # 本范围 0 错误；ReviewPanels.tsx(274/290/291) 报 Cannot find name 't'
```

`typecheck` 的 3 条错误全部位于 `web/src/components/ReviewPanels.tsx`（**不在 write_scope**，并行 agent 正在改该文件且尚未导入 `t`）。`ReviewPage.tsx` / `HistoryPage.tsx` / `review.ts` 零错误。

## 4. 未决项

1. `parsePrUrl` 的 `hint`（`web/src/lib/format.ts:54-61`）仍是硬编码中文，且该文件不在 write_scope；英文模式下 URL 校验提示会保持中文。
2. `ReviewPanels.tsx` / `FindingCard` / `ReportActions` / `AskPanel` 等共享组件的中文不在本任务范围，由其它命名空间任务处理。
3. 历史页指标 `label="critical"` / `label="high"` 为严重度英文专名，与 `SEVERITY_TEXT` 口径一致，未做成词典 key。
