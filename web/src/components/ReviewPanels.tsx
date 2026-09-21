import type { InterfaceImpact, ReviewPlan } from '../api/types'
import { Card, CardHead, Chip, Empty } from './ui'

export function PlanCard({ plan }: { plan: ReviewPlan }) {
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: '审查意图', value: plan.intent },
    {
      label: '风险等级',
      value: <Chip accent>{plan.risk_level}</Chip>,
    },
    {
      label: '风险类别',
      value: plan.risk_categories.length ? (
        <span className="row row-wrap" style={{ gap: 6 }}>
          {plan.risk_categories.map((c) => (
            <Chip key={c}>{c}</Chip>
          ))}
        </span>
      ) : (
        '—'
      ),
    },
    {
      label: '审查策略',
      value: plan.strategies.length ? (
        <span className="row row-wrap" style={{ gap: 6 }}>
          {plan.strategies.map((s) => (
            <Chip key={s}>{s}</Chip>
          ))}
        </span>
      ) : (
        '—'
      ),
    },
    {
      label: '跨文件分析',
      value: plan.requires_cross_file_analysis ? '需要' : '不需要',
    },
    { label: '预计逐文件审查', value: `${plan.estimated_file_reviews} 个文件` },
  ]

  return (
    <Card flush>
      <CardHead title="审查计划" extra={<span className="dim mono">ReviewPlan</span>} />
      <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
        {rows.map((row) => (
          <div
            key={row.label}
            style={{
              display: 'grid',
              gridTemplateColumns: '132px 1fr',
              gap: 'var(--ds-space-4)',
              alignItems: 'start',
            }}
          >
            <span className="finding-field-label" style={{ paddingTop: 3 }}>
              {row.label}
            </span>
            <span style={{ fontSize: 'var(--ds-text-md)', color: 'var(--ds-color-text-secondary)' }}>
              {row.value}
            </span>
          </div>
        ))}

        {plan.rationale.length > 0 && (
          <>
            <hr className="divider" style={{ margin: 'var(--ds-space-2) 0' }} />
            <div>
              <span className="finding-field-label">规划依据</span>
              <ul
                style={{
                  margin: '6px 0 0',
                  paddingLeft: '1.15em',
                  display: 'grid',
                  gap: 3,
                  fontSize: 'var(--ds-text-md)',
                  color: 'var(--ds-color-text-secondary)',
                }}
              >
                {plan.rationale.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}

export function InterfaceImpactCard({ impacts }: { impacts: InterfaceImpact[] }) {
  if (!impacts.length) return null
  const breaking = impacts.filter((i) => i.is_breaking).length

  return (
    <Card flush >
      <CardHead
        title="跨文件接口影响"
        extra={
          <span className="row" style={{ gap: 6 }}>
            <Chip>{impacts.length} 处变更</Chip>
            {breaking > 0 && <Chip accent>{breaking} 处破坏性</Chip>}
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
                <span className="finding-field-label">外部调用方</span>
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
                未发现外部调用方，此变更不会破坏其它文件。
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
  const reasons = Object.entries(filter.excluded_reason_counts ?? {})
  if (!filter.total_files && !reasons.length) return null

  return (
    <Card flush >
      <CardHead
        title="文件过滤"
        extra={
          <span className="row" style={{ gap: 6 }}>
            <Chip>共 {filter.total_files}</Chip>
            <Chip accent>纳入 {filter.included_count}</Chip>
            {filter.excluded_count > 0 && <Chip>跳过 {filter.excluded_count}</Chip>}
          </span>
        }
      />
      <div className="card-body">
        {reasons.length > 0 ? (
          <div className="row row-wrap" style={{ gap: 'var(--ds-space-4)' }}>
            {reasons.map(([code, count]) => (
              <div key={code}>
                <div className="metric-key">{code}</div>
                <div style={{ fontWeight: 600 }}>{count} 个文件</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
            没有文件被过滤掉。
          </p>
        )}

        {filter.results.length > 0 && (
          <details style={{ marginTop: 'var(--ds-space-4)' }}>
            <summary style={{ cursor: 'pointer', fontSize: 'var(--ds-text-md)' }}>
              查看逐文件结果（{filter.results.length}）
            </summary>
            <div style={{ marginTop: 'var(--ds-space-3)', maxHeight: 280, overflow: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>文件</th>
                    <th>结果</th>
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
                          {entry.included ? '纳入' : '跳过'}
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
  const entries = Object.entries(validation ?? {})
  if (!entries.length) return null
  return (
    <Card >
      <h3 style={{ marginBottom: 'var(--ds-space-3)' }}>证据校验</h3>
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
  return (
    <Card>
      <Empty mark="[ ✓ ]" title="没有发现问题">
        所有纳入审查的文件都通过了当前策略的检查。可以尝试降低置信度阈值，
        或切换到更严格的模型继续审查。
      </Empty>
    </Card>
  )
}
