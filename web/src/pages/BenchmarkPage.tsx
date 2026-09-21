import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BenchmarkReport } from '../api/types'
import { Card, CardHead, Chip, Empty, Metric, Notice, Section, cx } from '../components/ui'
import { formatPercent } from '../lib/format'

const STRATEGY_LABEL: Record<string, { name: string; desc: string }> = {
  static: { name: '逐行规则', desc: '按行匹配的安全规则：动态执行、硬编码凭证、SQL 插值、危险反序列化等。' },
  ast: { name: 'AST 规则', desc: '基于 Python 语法树：可变默认参数、裸 except、资源泄漏、弱哈希、异常链丢失等。' },
  combined: { name: '合并策略', desc: '逐行规则与 AST 规则合并去重，对应真实审查链路的默认行为。' },
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

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">BENCHMARK</div>
        <h1>准确率基准</h1>
        <p className="lead">
          内置的已知缺陷样例库。每个样例都预埋了缺陷及其准确行号，用同一套指标衡量不同分析策略，
          用于防止规则退化与误报增加。
        </p>
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
          <Empty mark="[ ! ]" title="未能载入基准报告">
            请确认本地服务正在运行。
          </Empty>
        </Card>
      ) : (
        <>
          <Section eyebrow="STRATEGY" title="策略对比">
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
                        {STRATEGY_LABEL[name]?.name ?? name}
                      </strong>
                      {active && <Chip accent>当前</Chip>}
                    </div>
                    <div
                      className="metrics"
                      style={{ marginTop: 'var(--ds-space-4)', gridTemplateColumns: '1fr 1fr' }}
                    >
                      <div>
                        <div className="metric-key">精确率</div>
                        <div className={cx('metric-value', 'metric-value-sm')}>
                          {formatPercent(item.precision, 0)}
                        </div>
                      </div>
                      <div>
                        <div className="metric-key">召回率</div>
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
                      {STRATEGY_LABEL[name]?.desc}
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
                title={`${STRATEGY_LABEL[selected]?.name ?? selected} · 指标`}
              >
                <div className="metrics">
                  <Metric
                    label="精确率"
                    value={formatPercent(report.precision)}
                    small
                    hint="报出的问题里有多少是真缺陷"
                  />
                  <Metric
                    label="召回率"
                    value={formatPercent(report.recall)}
                    small
                    hint="预埋缺陷有多少被找到"
                  />
                  <Metric label="F1" value={formatPercent(report.f1)} small />
                  <Metric label="误报率" value={formatPercent(report.false_positive_rate)} small />
                  <Metric label="行号准确率" value={formatPercent(report.line_accuracy)} small />
                  <Metric label="样例数" value={report.case_count} small />
                </div>

                <Card flush  style={{ marginTop: 'var(--ds-space-4)' }}>
                  <CardHead
                    title="混淆矩阵计数"
                    extra={<Chip>{report.case_count} 个样例合计</Chip>}
                  />
                  <div className="card-body">
                    <div className="metrics" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                      <Metric label="命中 (TP)" value={report.true_positives} small />
                      <Metric label="误报 (FP)" value={report.false_positives} small />
                      <Metric label="漏报 (FN)" value={report.false_negatives} small />
                    </div>
                  </div>
                </Card>
              </Section>

              <Section eyebrow="CASES" title="逐样例结果">
                <Card flush >
                  <div style={{ overflowX: 'auto' }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>样例</th>
                          <th className="table-num">TP</th>
                          <th className="table-num">FP</th>
                          <th className="table-num">FN</th>
                          <th className="table-num">精确率</th>
                          <th className="table-num">召回率</th>
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
                                  对照组
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
                      样例库共有 4 个文件样例：3 个预埋缺陷（共 12 处）与 1 个零缺陷对照组。
                      对照组用于衡量误报。这些数字代表规则在该精选集合上的表现，
                      <strong>不等同于在真实 PR 上的泛化准确率</strong>。
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
