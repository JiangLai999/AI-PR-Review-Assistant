import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HistoryResponse, ReportResponse } from '../api/types'
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

export function HistoryPage({ onNavigate }: { onNavigate: (page: string) => void }) {
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
        <h1>历史审查</h1>
        <p className="lead">
          每次审查都会写入本地 SQLite：计划、证据校验摘要、跨文件接口影响与人工反馈都随运行一起保存，
          方便复盘与对比。
        </p>
      </div>

      {error && (
        <div style={{ marginBottom: 'var(--ds-space-4)' }}>
          <Notice kind="error">{error}</Notice>
        </div>
      )}

      <Section eyebrow="AGGREGATE" title="聚合统计">
        <div className="metrics">
          <Metric label="总运行次数" value={formatNumber(stats.total_runs)} />
          <Metric label="覆盖 PR" value={formatNumber(stats.unique_prs)} />
          <Metric label="累计发现" value={formatNumber(stats.total_findings)} />
          <Metric label="critical" value={formatNumber(stats.critical_findings)} />
          <Metric label="high" value={formatNumber(stats.high_findings)} />
          <Metric label="累计成本" value={formatCost(Number(stats.total_cost ?? 0))} small />
        </div>
      </Section>

      <Section
        eyebrow="RUNS"
        title="运行记录"
        extra={
          <button type="button" className="btn btn-ghost" onClick={() => void load()} disabled={loading}>
            {loading ? <Spinner /> : null}
            刷新
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
            <Empty mark="[ 0 ]" title="还没有审查记录">
              <span>在工作台执行一次审查后，运行记录会出现在这里。</span>
              <button type="button" className="btn btn-primary" onClick={() => onNavigate('review')}>
                前往审查工作台
              </button>
            </Empty>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>仓库</th>
                    <th>模型</th>
                    <th className="table-num">发现</th>
                    <th className="table-num">耗时</th>
                    <th className="table-num">成本</th>
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
                          查看报告
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
          title={`运行报告 · ${report.run_id.slice(0, 8)}`}
          extra={
            <button type="button" className="btn btn-ghost" onClick={() => setReport(null)}>
              收起
            </button>
          }
        >
          <div className="stack">
            <Card flush >
              <CardHead
                title={report.run.pr_url ? repoLabel(report.run) : report.run_id}
                extra={<Chip>{report.review.findings.length} 条发现</Chip>}
              />
              <div className="card-body">
                <div className="metrics">
                  <Metric label="耗时" value={formatDuration(report.run.duration_seconds)} small />
                  <Metric label="成本" value={formatCost(report.run.total_cost)} small />
                  <Metric label="模型" value={report.run.model || '—'} small />
                  <Metric label="时间" value={formatTime(report.run.created_at)} small />
                </div>
                {report.review.summary && (
                  <div style={{ marginTop: 'var(--ds-space-4)' }}>
                    <span className="finding-field-label">审查摘要</span>
                    <p className="finding-text" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                      {report.review.summary}
                    </p>
                  </div>
                )}
              </div>
            </Card>

            {/* 与审查工作台共用同一个组件，发布/导出行为不可能分叉。 */}
            <ReportActions runId={report.run_id} />

            {report.plan && <PlanCard plan={report.plan} />}
            <ValidationCard validation={report.validation ?? {}} />

            {report.review.findings.length > 0 && (
              <div className="stack">
                {report.review.findings.map((finding, index) => (
                  <FindingCard
                    key={finding.finding_id || `h-${index}`}
                    finding={finding}
                    runId={report.run_id}
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
