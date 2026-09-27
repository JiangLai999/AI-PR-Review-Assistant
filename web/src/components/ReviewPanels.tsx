import type { InterfaceImpact, ReviewPlan } from '../api/types'
import { Card, CardHead, Chip, Empty, cx } from './ui'
import { useT } from '../i18n'

/** 空值统一显示的长破折号（与导出的 Markdown / CLI 表格保持同一种"没有"）。 */
const EMPTY_VALUE = '—'

export function PlanCard({ plan }: { plan: ReviewPlan }) {
  const t = useT()
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: t('panels.plan.intent'), value: plan.intent || EMPTY_VALUE },
    {
      label: t('panels.plan.riskLevel'),
      value: <Chip accent>{plan.risk_level}</Chip>,
    },
    {
      label: t('panels.plan.riskCategories'),
      value: plan.risk_categories.length ? (
        <span className="row row-wrap" style={{ gap: 6 }}>
          {plan.risk_categories.map((c) => (
            <Chip key={c}>{c}</Chip>
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
            <Chip key={s}>{s}</Chip>
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
            {t('panels.plan.stats.risk', { level: plan.risk_level })}
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
            <span className="plan-value">{row.value}</span>
          </div>
        ))}

        <hr className="divider" style={{ margin: 'var(--ds-space-2) 0' }} />
        <div>
          <span className="finding-field-label">{t('panels.plan.rationale')}</span>
          {plan.rationale.length > 0 ? (
            <ol className="plan-rationale">
              {plan.rationale.map((item) => (
                <li key={item}>{item}</li>
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
            <div className="metric-key">{key}</div>
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
