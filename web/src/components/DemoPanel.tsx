import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DemoCaseSummary, DemoResult } from '../api/types'
import { useT } from '../i18n'

export function DemoPanel() {
  const t = useT()
  const [cases, setCases] = useState<DemoCaseSummary[]>([])
  const [selected, setSelected] = useState('sql-injection')
  const [result, setResult] = useState<DemoResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.demoCases().then((response) => setCases(response.cases)).catch(() => setCases([]))
  }, [])

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await api.demoRun(selected))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="demo-panel" aria-label={t('overview.demo.aria')}>
      <div className="demo-panel-copy">
        <div className="eyebrow">JUDGE MODE · OFFLINE DEMO</div>
        <h2>{t('overview.demo.title')}</h2>
        <p>{t('overview.demo.body')}</p>
        <div className="demo-controls">
          <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={loading}>
            {cases.length === 0 ? <option value="sql-injection">SQL injection</option> : cases.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}
          </select>
          <button type="button" className="btn btn-primary" onClick={() => void run()} disabled={loading}>
            {loading ? t('overview.demo.running') : t('overview.demo.run')}
          </button>
        </div>
        {error && <p className="demo-error">{error}</p>}
      </div>
      <div className="demo-result">
        {!result ? (
          <div className="demo-empty"><span>01</span><b>{t('overview.demo.emptyTitle')}</b><small>{t('overview.demo.emptyBody')}</small></div>
        ) : (
          <>
            <div className="demo-result-head"><span>DEMO RESULT</span><strong>{result.case.key}</strong></div>
            <div className="demo-summary-grid">
              <div><small>RISK</small><b className={`risk-${result.summary.risk_level}`}>{result.summary.risk_level.toUpperCase()}</b></div>
              <div><small>FINDINGS</small><b>{result.summary.finding_count}</b></div>
              <div><small>EVIDENCE</small><b>{result.summary.evidence_validated}/{result.summary.finding_count}</b></div>
            </div>
            <div className="demo-findings">
              {result.findings.map((finding) => <div className="demo-finding" key={finding.finding_id ?? `${finding.file}:${finding.line_start}`}><span>{finding.severity.toUpperCase()}</span><b>{finding.title}</b><small>{finding.file}:{finding.line_start} · evidence {finding.evidence_status}</small></div>)}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
