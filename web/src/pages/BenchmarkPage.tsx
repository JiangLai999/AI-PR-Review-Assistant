import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BenchmarkReport } from '../api/types'
import { Card, CardHead, Chip, Empty, Metric, Notice, Section, cx } from '../components/ui'
import { tn, useT } from '../i18n'
import { formatPercent } from '../lib/format'

/** 策略名/说明只存 key，渲染时用 t() 取词；后端若返回未知策略，回落显示原始 name。 */
const STRATEGY_KEYS: Record<string, { name: string; desc: string }> = {
  static: { name: 'benchmark.strategy.static.name', desc: 'benchmark.strategy.static.desc' },
  ast: { name: 'benchmark.strategy.ast.name', desc: 'benchmark.strategy.ast.desc' },
  combined: {
    name: 'benchmark.strategy.combined.name',
    desc: 'benchmark.strategy.combined.desc',
  },
}

function isReport(value: unknown): value is BenchmarkReport {
  return !!value && typeof value === 'object' && 'precision' in value
}

/**
 * 零缺陷对照组没有任何预测，精确率/召回率在数学上无定义。
 * 显示为「—」而不是「0%」，避免看起来像这条样例失败了。
 */
function metricCell(value: number, tp: number, fp: number, fn: number): string {
  if (tp + fp + fn === 0) return '—'
  return formatPercent(value, 0)
}

export function BenchmarkPage() {
  const t = useT()
  const [reports, setReports] = useState<Record<string, BenchmarkReport> | null>(null)
  const [selected, setSelected] = useState('combined')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const payload = await api.benchmark('all')
        if (!alive) return
        if (isReport(payload)) {
          setReports({ [payload.strategy]: payload })
        } else {
          setReports(payload)
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const report = reports?.[selected]
  const names = reports ? Object.keys(reports) : []
  const selectedKey = STRATEGY_KEYS[selected]
  const selectedLabel = selectedKey ? t(selectedKey.name) : selected

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">BENCHMARK</div>
        <h1>{t('benchmark.hero.title')}</h1>
        <p className="lead">{t('benchmark.hero.lead')}</p>
      </div>

      {error && (
        <div style={{ marginBottom: 'var(--ds-space-4)' }}>
          <Notice kind="error">{error}</Notice>
        </div>
      )}

      {loading ? (
        <Card>
          <div className="card-body stack">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton" style={{ height: 56 }} />
            ))}
          </div>
        </Card>
      ) : !reports ? (
        <Card>
          <Empty mark="[ ! ]" title={t('benchmark.empty.title')}>
            {t('benchmark.empty.body')}
          </Empty>
        </Card>
      ) : (
        <>
          <Section eyebrow="STRATEGY" title={t('benchmark.strategy.title')}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: 'var(--ds-space-4)',
              }}
            >
              {names.map((name) => {
                const item = reports[name]
                const active = name === selected
                const label = STRATEGY_KEYS[name]
                return (
                  <button
                    key={name}
                    type="button"
                    onClick={() => setSelected(name)}
                    style={{
                      textAlign: 'left',
                      border: `1px solid ${active ? 'var(--ds-color-brand)' : 'var(--ds-color-border-subtle)'}`,
                      boxShadow: active
                        ? '0 0 0 3px var(--ds-color-brand-soft)'
                        : 'var(--ds-shadow-card)',
                      background: 'var(--ds-color-bg-overlay)',
                      borderRadius: 'var(--ds-radius-card)',
                      padding: 'var(--ds-space-5)',
                      cursor: 'pointer',
                      transition: 'border-color .2s ease, box-shadow .2s ease',
                    }}
                  >
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <strong style={{ fontSize: 'var(--ds-text-base)' }}>
                        {label ? t(label.name) : name}
                      </strong>
                      {active && <Chip accent>{t('benchmark.strategy.current')}</Chip>}
                    </div>
                    <div
                      className="metrics"
                      style={{ marginTop: 'var(--ds-space-4)', gridTemplateColumns: '1fr 1fr' }}
                    >
                      <div>
                        <div className="metric-key">{t('benchmark.metric.precision')}</div>
                        <div className={cx('metric-value', 'metric-value-sm')}>
                          {formatPercent(item.precision, 0)}
                        </div>
                      </div>
                      <div>
                        <div className="metric-key">{t('benchmark.metric.recall')}</div>
                        <div className={cx('metric-value', 'metric-value-sm')}>
                          {formatPercent(item.recall, 0)}
                        </div>
                      </div>
                    </div>
                    <p
                      className="dim"
                      style={{
                        marginTop: 'var(--ds-space-3)',
                        fontSize: 'var(--ds-text-sm)',
                        lineHeight: 1.55,
                      }}
                    >
                      {label ? t(label.desc) : undefined}
                    </p>
                  </button>
                )
              })}
            </div>
          </Section>

          {report && (
            <>
              <Section
                eyebrow="METRICS"
                title={t('benchmark.metrics.title', { strategy: selectedLabel })}
              >
                <div className="metrics">
                  <Metric
                    label={t('benchmark.metric.precision')}
                    value={formatPercent(report.precision)}
                    small
                    hint={t('benchmark.metric.precisionHint')}
                  />
                  <Metric
                    label={t('benchmark.metric.recall')}
                    value={formatPercent(report.recall)}
                    small
                    hint={t('benchmark.metric.recallHint')}
                  />
                  <Metric label={t('benchmark.metric.f1')} value={formatPercent(report.f1)} small />
                  <Metric
                    label={t('benchmark.metric.fpr')}
                    value={formatPercent(report.false_positive_rate)}
                    small
                  />
                  <Metric
                    label={t('benchmark.metric.lineAccuracy')}
                    value={formatPercent(report.line_accuracy)}
                    small
                  />
                  <Metric
                    label={t('benchmark.metric.cases')}
                    value={report.case_count}
                    small
                  />
                </div>

                <Card flush  style={{ marginTop: 'var(--ds-space-4)' }}>
                  <CardHead
                    title={t('benchmark.matrix.title')}
                    extra={<Chip>{tn('benchmark.matrix.cases', report.case_count)}</Chip>}
                  />
                  <div className="card-body">
                    <div className="metrics" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                      <Metric
                        label={t('benchmark.matrix.tp')}
                        value={report.true_positives}
                        small
                      />
                      <Metric
                        label={t('benchmark.matrix.fp')}
                        value={report.false_positives}
                        small
                      />
                      <Metric
                        label={t('benchmark.matrix.fn')}
                        value={report.false_negatives}
                        small
                      />
                    </div>
                  </div>
                </Card>
              </Section>

              <Section eyebrow="CASES" title={t('benchmark.cases.title')}>
                <Card flush >
                  <div style={{ overflowX: 'auto' }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>{t('benchmark.cases.caseId')}</th>
                          <th className="table-num">TP</th>
                          <th className="table-num">FP</th>
                          <th className="table-num">FN</th>
                          <th className="table-num">{t('benchmark.metric.precision')}</th>
                          <th className="table-num">{t('benchmark.metric.recall')}</th>
                          <th className="table-num">F1</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.cases.map((item) => (
                          <tr key={item.case_id}>
                            <td className="mono" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                              {item.case_id}
                              {item.true_positives + item.false_positives + item.false_negatives === 0 && (
                                <span className="chip" style={{ marginLeft: 8 }}>
                                  {t('benchmark.cases.control')}
                                </span>
                              )}
                            </td>
                            <td className="table-num">{item.true_positives}</td>
                            <td
                              className="table-num"
                              style={{
                                color: item.false_positives
                                  ? 'var(--ds-sev-critical)'
                                  : undefined,
                              }}
                            >
                              {item.false_positives}
                            </td>
                            <td
                              className="table-num"
                              style={{
                                color: item.false_negatives ? 'var(--ds-sev-medium)' : undefined,
                              }}
                            >
                              {item.false_negatives}
                            </td>
                            <td className="table-num mono">
                              {metricCell(
                                item.precision,
                                item.true_positives,
                                item.false_positives,
                                item.false_negatives,
                              )}
                            </td>
                            <td className="table-num mono">
                              {metricCell(
                                item.recall,
                                item.true_positives,
                                item.false_positives,
                                item.false_negatives,
                              )}
                            </td>
                            <td className="table-num mono">
                              {metricCell(
                                item.f1,
                                item.true_positives,
                                item.false_positives,
                                item.false_negatives,
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>

                <Card  style={{ marginTop: 'var(--ds-space-4)' }}>
                  <div
                    className="row"
                    style={{ gap: 'var(--ds-space-3)', alignItems: 'flex-start' }}
                  >
                    <span className="notice-icon" style={{ color: 'var(--ds-sev-medium)' }}>
                      !
                    </span>
                    <p className="muted" style={{ fontSize: 'var(--ds-text-md)', lineHeight: 1.65 }}>
                      {t('benchmark.note.body')}
                      <strong>{t('benchmark.note.emphasis')}</strong>
                      {t('benchmark.note.tail')}
                    </p>
                  </div>
                </Card>
              </Section>
            </>
          )}
        </>
      )}
    </>
  )
}
