import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HistoryResponse, ReportResponse } from '../api/types'
import { AskPanel } from '../components/AskPanel'
import { FindingCard } from '../components/FindingCard'
import { ReportActions } from '../components/ReportActions'
import { InterfaceImpactCard, PlanCard, ValidationCard } from '../components/ReviewPanels'
import {
  Card,
  CardHead,
  Chip,
  Empty,
  Metric,
  Notice,
  Section,
  Spinner,
} from '../components/ui'
import { formatCost, formatDuration, formatNumber, formatTime, repoLabel } from '../lib/format'
import { useT, tn } from '../i18n'

export function HistoryPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const t = useT()
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportLoading, setReportLoading] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setHistory(await api.history(50))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function openReport(runId: string) {
    setReportLoading(runId)
    setError(null)
    try {
      setReport(await api.report(runId))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setReportLoading(null)
    }
  }

  const stats = history?.statistics ?? {}
  const runs = history?.runs ?? []
  const feedbackMap = new Map((report?.feedback ?? []).map((f) => [f.finding_id, f.status]))

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">HISTORY</div>
        <h1>{t('history.head.title')}</h1>
        <p className="lead">{t('history.head.lead')}</p>
      </div>

      {error && (
        <div style={{ marginBottom: 'var(--ds-space-4)' }}>
          <Notice kind="error">{error}</Notice>
        </div>
      )}

      <Section eyebrow="AGGREGATE" title={t('history.stats.title')}>
        <div className="metrics">
          <Metric label={t('history.stats.totalRuns')} value={formatNumber(stats.total_runs)} />
          <Metric label={t('history.stats.uniquePrs')} value={formatNumber(stats.unique_prs)} />
          <Metric label={t('history.stats.totalFindings')} value={formatNumber(stats.total_findings)} />
          <Metric label="critical" value={formatNumber(stats.critical_findings)} />
          <Metric label="high" value={formatNumber(stats.high_findings)} />
          <Metric label={t('history.stats.totalCost')} value={formatCost(Number(stats.total_cost ?? 0))} small />
        </div>
      </Section>

      <Section
        eyebrow="RUNS"
        title={t('history.runs.title')}
        extra={
          <button type="button" className="btn btn-ghost" onClick={() => void load()} disabled={loading}>
            {loading ? <Spinner /> : null}
            {t('history.runs.refresh')}
          </button>
        }
      >
        <Card flush >
          {loading && !history ? (
            <div className="card-body stack">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton" style={{ height: 42 }} />
              ))}
            </div>
          ) : runs.length === 0 ? (
            <Empty mark="[ 0 ]" title={t('history.empty.title')}>
              <span>{t('history.empty.desc')}</span>
              <button type="button" className="btn btn-primary" onClick={() => onNavigate('review')}>
                {t('history.empty.goWorkbench')}
              </button>
            </Empty>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('history.runs.col.time')}</th>
                    <th>{t('history.runs.col.repo')}</th>
                    <th>{t('history.runs.col.model')}</th>
                    <th className="table-num">{t('history.runs.col.findings')}</th>
                    <th className="table-num">{t('history.runs.col.duration')}</th>
                    <th className="table-num">{t('history.runs.col.cost')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td className="mono nowrap" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {formatTime(run.created_at)}
                      </td>
                      <td className="mono" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {repoLabel(run)}
                      </td>
                      <td className="dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {run.model || '—'}
                      </td>
                      <td className="table-num">
                        {run.total_findings ? (
                          <span className="row" style={{ justifyContent: 'flex-end', gap: 6 }}>
                            <strong>{run.total_findings}</strong>
                            {run.critical_findings ? (
                              <span className="badge sev-critical">{run.critical_findings} crit</span>
                            ) : null}
                          </span>
                        ) : (
                          <span className="dim">0</span>
                        )}
                      </td>
                      <td className="table-num mono dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {formatDuration(run.duration_seconds)}
                      </td>
                      <td className="table-num mono dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {formatCost(run.total_cost)}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          disabled={reportLoading === run.id}
                          onClick={() => void openReport(run.id)}
                        >
                          {reportLoading === run.id ? <Spinner /> : null}
                          {t('history.runs.openReport')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </Section>

      {report && (
        <Section
          eyebrow="REPORT"
          title={t('history.report.title', { id: report.run_id.slice(0, 8) })}
          extra={
            <button type="button" className="btn btn-ghost" onClick={() => setReport(null)}>
              {t('history.report.collapse')}
            </button>
          }
        >
          <div className="stack">
            <Card flush >
              <CardHead
                title={report.run.pr_url ? repoLabel(report.run) : report.run_id}
                extra={<Chip>{tn('history.findings', report.review.findings.length)}</Chip>}
              />
              <div className="card-body">
                <div className="metrics">
                  <Metric label={t('history.report.duration')} value={formatDuration(report.run.duration_seconds)} small />
                  <Metric label={t('history.report.cost')} value={formatCost(report.run.total_cost)} small />
                  <Metric label={t('history.report.model')} value={report.run.model || '—'} small />
                  <Metric label={t('history.report.time')} value={formatTime(report.run.created_at)} small />
                </div>
                {report.review.summary && (
                  <div style={{ marginTop: 'var(--ds-space-4)' }}>
                    <span className="finding-field-label">{t('history.report.summary')}</span>
                    <p className="finding-text" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                      {report.review.summary}
                    </p>
                  </div>
                )}
              </div>
            </Card>

            {/* 与审查工作台共用同一个组件，发布/导出行为不可能分叉。 */}
            <ReportActions runId={report.run_id} />

            {/* 打开报告即可就地追问；这里的 run_id 一定存在（报告就是从它读出来的）。 */}
            <AskPanel runId={report.run_id} />

            {report.plan && <PlanCard plan={report.plan} />}
            <ValidationCard validation={report.validation ?? {}} />

            {report.review.findings.length > 0 && (
              <div className="stack">
                {report.review.findings.map((finding, index) => (
                  <FindingCard
                    key={finding.finding_id || `h-${index}`}
                    finding={finding}
                    runId={report.run_id}
                    // 历史 run 记录里本来就有这两个字段（list_runs 的 SELECT 带
                    // head_sha / pr_url），一并传下去，「文件:行」才在历史弹窗里也能点。
                    prUrl={report.run.pr_url || undefined}
                    headSha={report.run.head_sha || undefined}
                    index={index}
                    initialFeedback={
                      finding.finding_id ? feedbackMap.get(finding.finding_id) : undefined
                    }
                  />
                ))}
              </div>
            )}

            <InterfaceImpactCard impacts={report.interface_impacts ?? []} />
          </div>
        </Section>
      )}
    </>
  )
}
