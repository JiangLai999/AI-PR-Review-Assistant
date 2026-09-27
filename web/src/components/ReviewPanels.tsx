import { useState } from 'react'
import type { InterfaceImpact, ReviewPlan } from '../api/types'
import { MarkdownLite } from './MarkdownLite.jsx'
import { Card, CardHead, Chip, Empty, cx } from './ui'
import { dictKeys, getLang, t, useT } from '../i18n'
import type { Lang } from '../i18n'

/** 空值统一显示的长破折号（与导出的 Markdown / CLI 表格保持同一种"没有"）。 */
const EMPTY_VALUE = '—'

/**
 * 词典里真有这条词条才用译文。`dictKeys` 会遍历整本词典，按语言缓存成 Set，
 * 免得每个 chip 都重扫一遍（一屏几十个 chip）。
 */
let dictKeyCache: { lang: Lang; keys: Set<string> } | null = null

function hasDictKey(key: string): boolean {
  const lang = getLang()
  if (!dictKeyCache || dictKeyCache.lang !== lang) {
    dictKeyCache = { lang, keys: new Set(dictKeys(lang)) }
  }
  return dictKeyCache.keys.has(key)
}

/**
 * 规范 id → 词典文案：`security` → `安全` / `Security`，`valid` → `证据有效` / `Valid`。
 *
 * 审查计划是后端**确定性**生成的，id 是规范值（见 services/agent/planner.py 与
 * models/review_plan.py）。词典里没有这条（老 run 里的新 id、后端将来加的类别）
 * **一律原样回退 id**：绝不显示空白或裸 key。
 */
export function idText(prefix: string, id: string): string {
  const key = `${prefix}${id}`
  return hasDictKey(key) ? t(key) : id
}

/** 折叠阈值：行数或字符数任一超限即默认折叠。 */
const COLLAPSE_LINES = 12
const COLLAPSE_CHARS = 600

/**
 * 折叠预览：先取前 N 行，再按字符截断（超长单行也能折）。截断处补省略号，
 * 免得半句话看着像被吞了。返回 `text` 本身表示没截断。
 */
function collapsePreview(text: string): string {
  const preview = text.split('\n').slice(0, COLLAPSE_LINES).join('\n')
  const cut = preview.length > COLLAPSE_CHARS ? preview.slice(0, COLLAPSE_CHARS) : preview
  return cut === text ? text : `${cut}…`
}

/**
 * 可折叠的 Markdown 正文（追问回答 / 审查意图共用）。
 *
 * 用户明确要求「无论文本大小均可折叠」：**任何**长度都渲染折叠控件，长文本
 * （>12 行 或 >600 字符）默认折起并显示「展开全部（N 行）」，短文本默认展开但
 * 仍可手动收起。折叠是**按源码截断**而不是 CSS 裁剪 —— 这样被折起来的代码块里
 * 的复制按钮不会留在 DOM 里被 Tab 键够到。
 */
export function CollapsibleText({ text, className }: { text: string; className?: string }) {
  const t = useT()
  const lines = text ? text.split('\n').length : 0
  const long = lines > COLLAPSE_LINES || text.length > COLLAPSE_CHARS
  const [expanded, setExpanded] = useState(!long)
  // 换文本（历史回填 / 换一条 run）就回到默认态：不能沿用上一条回答的展开状态。
  const [rendered, setRendered] = useState(text)
  if (rendered !== text) {
    setRendered(text)
    setExpanded(!long)
  }
  if (!text.trim()) return null

  return (
    <div
      className={cx('collapsible-text', className)}
      data-collapsed={expanded ? 'false' : 'true'}
    >
      <MarkdownLite text={expanded ? text : collapsePreview(text)} />
      <button
        type="button"
        className="btn btn-ghost btn-sm collapsible-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded
          ? t('text.collapse')
          : long
            ? t('text.expandAll', { count: lines })
            : t('text.expand')}
      </button>
    </div>
  )
}

export function PlanCard({ plan }: { plan: ReviewPlan }) {
  const t = useT()
  const rows: { label: string; value: React.ReactNode }[] = [
    {
      label: t('panels.plan.intent'),
      // PR 标题 + 描述原文（可能中可能英、可能是长段落），走 Markdown + 折叠。
      value: plan.intent ? <CollapsibleText text={plan.intent} /> : EMPTY_VALUE,
    },
    {
      label: t('panels.plan.riskLevel'),
      value: <Chip accent>{idText('panels.risk.level.', plan.risk_level)}</Chip>,
    },
    {
      label: t('panels.plan.riskCategories'),
      value: plan.risk_categories.length ? (
        <span className="row row-wrap" style={{ gap: 6 }}>
          {plan.risk_categories.map((c) => (
            <Chip key={c}>{idText('panels.risk.category.', c)}</Chip>
          ))}
        </span>
      ) : (
        EMPTY_VALUE
      ),
    },
    {
      label: t('panels.plan.strategies'),
      value: plan.strategies.length ? (
        <span className="row row-wrap" style={{ gap: 6 }}>
          {plan.strategies.map((s) => (
            <Chip key={s}>{idText('panels.plan.strategy.', s)}</Chip>
          ))}
        </span>
      ) : (
        EMPTY_VALUE
      ),
    },
    {
      label: t('panels.plan.crossFile'),
      value: plan.requires_cross_file_analysis
        ? t('panels.plan.crossFile.yes')
        : t('panels.plan.crossFile.no'),
    },
    {
      label: t('panels.plan.estimated'),
      value: t('panels.plan.estimated.value', { count: plan.estimated_file_reviews }),
    },
  ]

  return (
    <Card flush>
      <CardHead title={t('panels.plan.title')} extra={<span className="dim mono">ReviewPlan</span>} />
      <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
        {/* 统计条：三个数字（类别 / 策略 / 待审文件）+ 风险等级，窄屏自动换行。 */}
        <div className="plan-stats" role="group" aria-label={t('panels.plan.stats.aria')}>
          <span className={cx('chip', `chip-risk-${plan.risk_level}`)}>
            {t('panels.plan.stats.risk', { level: idText('panels.risk.level.', plan.risk_level) })}
          </span>
          <Chip>{t('panels.plan.stats.categories', { count: plan.risk_categories.length })}</Chip>
          <Chip>{t('panels.plan.stats.strategies', { count: plan.strategies.length })}</Chip>
          <Chip>{t('panels.plan.stats.files', { count: plan.estimated_file_reviews })}</Chip>
        </div>

        {rows.map((row) => (
          <div key={row.label} className="plan-grid-row">
            <span className="finding-field-label" style={{ paddingTop: 3 }}>
              {row.label}
            </span>
            {/* div 而不是 span：审查意图走 CollapsibleText（块级元素），span 里嵌 div 是非法嵌套。 */}
            <div className="plan-value">{row.value}</div>
          </div>
        ))}

        <hr className="divider" style={{ margin: 'var(--ds-space-2) 0' }} />
        <div>
          <span className="finding-field-label">{t('panels.plan.rationale')}</span>
          {plan.rationale.length > 0 ? (
            /* 规划依据是**句子**（后端按 UI 语言生成中英两版，老 run 里是英文），
               所以不翻译，只交给 MarkdownLite 渲染行内格式（列表外观仍是 ol/li）。 */
            <ol className="plan-rationale">
              {plan.rationale.map((item) => (
                <li key={item}>
                  <MarkdownLite text={item} />
                </li>
              ))}
            </ol>
          ) : (
            <p className="plan-value" style={{ margin: '6px 0 0' }}>
              {EMPTY_VALUE}
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}

export function InterfaceImpactCard({ impacts }: { impacts: InterfaceImpact[] }) {
  const t = useT()
  if (!impacts.length) return null
  const breaking = impacts.filter((i) => i.is_breaking).length

  return (
    <Card flush >
      <CardHead
        title={t('panels.impacts.title')}
        extra={
          <span className="row" style={{ gap: 6 }}>
            <Chip>{t('panels.impacts.changes', { count: impacts.length })}</Chip>
            {breaking > 0 && (
              <Chip accent>{t('panels.impacts.breaking', { count: breaking })}</Chip>
            )}
          </span>
        }
      />
      <div className="card-body stack">
        {impacts.map((impact) => (
          <div
            key={`${impact.file}:${impact.line}:${impact.symbol}`}
            style={{
              border: '1px solid var(--ds-color-border-subtle)',
              borderRadius: 'var(--ds-radius-panel)',
              padding: 'var(--ds-space-4)',
              background: impact.is_breaking
                ? 'var(--ds-sev-critical-bg)'
                : 'var(--ds-color-bg-surface-4)',
            }}
          >
            <div className="row row-wrap" style={{ gap: 'var(--ds-space-2)' }}>
              <span
                className="badge"
                style={{
                  background: impact.is_breaking
                    ? 'var(--ds-sev-critical)'
                    : 'var(--ds-state-unverified)',
                  color: '#fff',
                }}
              >
                {impact.label}
              </span>
              <strong className="mono" style={{ fontSize: 'var(--ds-text-base)' }}>
                {impact.symbol}
              </strong>
              <span className="finding-meta" style={{ marginTop: 0 }}>
                {impact.file}:{impact.line}
              </span>
            </div>

            <div className="row row-wrap" style={{ gap: 6, marginTop: 'var(--ds-space-3)' }}>
              <code className="code-inline">{impact.before || '<none>'}</code>
              <span className="dim">→</span>
              <code className="code-inline">{impact.after || '<none>'}</code>
            </div>

            {impact.references.length > 0 ? (
              <div style={{ marginTop: 'var(--ds-space-3)' }}>
                <span className="finding-field-label">{t('panels.impacts.callers')}</span>
                <ul
                  style={{
                    margin: '5px 0 0',
                    paddingLeft: '1.15em',
                    fontSize: 'var(--ds-text-sm)',
                    color: 'var(--ds-color-text-secondary)',
                  }}
                >
                  {impact.references.map((ref) => (
                    <li key={`${ref.file}:${ref.line}`} className="mono">
                      {ref.file}:{ref.line}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="muted" style={{ marginTop: 'var(--ds-space-3)', fontSize: 'var(--ds-text-sm)' }}>
                {t('panels.impacts.noCallers')}
              </p>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

export function FilterCard({
  filter,
}: {
  filter: {
    total_files: number
    included_count: number
    excluded_count: number
    excluded_reason_counts: Record<string, number>
    results: { filename: string; included: boolean }[]
  }
}) {
  const t = useT()
  const reasons = Object.entries(filter.excluded_reason_counts ?? {})
  if (!filter.total_files && !reasons.length) return null

  return (
    <Card flush >
      <CardHead
        title={t('panels.filter.title')}
        extra={
          <span className="row" style={{ gap: 6 }}>
            <Chip>{t('panels.filter.total', { count: filter.total_files })}</Chip>
            <Chip accent>{t('panels.filter.included', { count: filter.included_count })}</Chip>
            {filter.excluded_count > 0 && (
              <Chip>{t('panels.filter.skipped', { count: filter.excluded_count })}</Chip>
            )}
          </span>
        }
      />
      <div className="card-body">
        {reasons.length > 0 ? (
          <div className="row row-wrap" style={{ gap: 'var(--ds-space-4)' }}>
            {reasons.map(([code, count]) => (
              <div key={code}>
                <div className="metric-key">{code}</div>
                <div style={{ fontWeight: 600 }}>{t('panels.filter.files', { count })}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
             {t('panels.filter.none')}
          </p>
        )}

        {filter.results.length > 0 && (
          <details style={{ marginTop: 'var(--ds-space-4)' }}>
            <summary style={{ cursor: 'pointer', fontSize: 'var(--ds-text-md)' }}>
               {t('panels.filter.viewAll', { count: filter.results.length })}
            </summary>
            <div style={{ marginTop: 'var(--ds-space-3)', maxHeight: 280, overflow: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                     <th>{t('panels.filter.col.file')}</th>
                     <th>{t('panels.filter.col.result')}</th>
                  </tr>
                </thead>
                <tbody>
                  {filter.results.map((entry) => (
                    <tr key={entry.filename}>
                      <td className="mono" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {entry.filename}
                      </td>
                      <td>
                        <span className={`badge ${entry.included ? 'st-valid' : 'st-unverified'}`}>
                           {entry.included
                             ? t('panels.filter.included.short')
                             : t('panels.filter.skipped.short')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </Card>
  )
}

export function ValidationCard({ validation }: { validation: Record<string, number> }) {
  const t = useT()
  const entries = Object.entries(validation ?? {})
  if (!entries.length) return null
  return (
    <Card >
      <h3 style={{ marginBottom: 'var(--ds-space-3)' }}>{t('panels.validation.title')}</h3>
      <div className="metrics">
        {entries.map(([key, value]) => (
          <div className="metric" key={key}>
            {/* 键是固定集合 valid|needs_review|invalid|unverified，一律走词典（未知键原样回退）。 */}
            <div className="metric-key">{idText('panels.validation.', key)}</div>
            <div className="metric-value metric-value-sm">{value}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function NoFindings() {
  const t = useT()
  return (
    <Card>
      <Empty mark="[ ✓ ]" title={t('panels.empty.title')}>
        {t('panels.empty.body')}
      </Empty>
    </Card>
  )
}
