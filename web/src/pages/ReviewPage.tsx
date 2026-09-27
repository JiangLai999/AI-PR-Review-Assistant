import { useEffect, useMemo, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { api, ApiError } from '../api/client'
import type { EvidenceStatus, JobEvent, JobSnapshot, ReviewResponse, Severity } from '../api/types'
import { AskPanel } from '../components/AskPanel'
import { FindingCard } from '../components/FindingCard'
import { MarkdownLite } from '../components/MarkdownLite.jsx'
import { ReportActions } from '../components/ReportActions'
import {
  FilterCard,
  InterfaceImpactCard,
  NoFindings,
  PlanCard,
  ValidationCard,
  idText,
} from '../components/ReviewPanels'
import {
  Card,
  CardHead,
  Empty,
  Metric,
  Notice,
  ProgressBar,
  Section,
  Spinner,
  cx,
} from '../components/ui'
import { useT } from '../i18n'
import { formatCost, formatDuration, parsePrUrl } from '../lib/format'

type Mode = 'plan' | 'review'
type Status =
  | { kind: 'idle' }
  | { kind: 'running'; mode: Mode; label: string }
  | { kind: 'ok'; mode: Mode; message: string }
  | { kind: 'error'; message: string; offline?: boolean }
  | { kind: 'cancelled' }

const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'info']
const EVIDENCE: EvidenceStatus[] = ['valid', 'needs_review', 'invalid', 'unverified']

/** 严重度 → i18n key：chips、下拉与 title 提示共用一份，避免三处各写一遍。 */
const SEVERITY_LABEL_KEY: Record<Severity, string> = {
  critical: 'severity.critical',
  high: 'severity.high',
  medium: 'severity.medium',
  low: 'severity.low',
  info: 'severity.info',
}

const EVIDENCE_KEYS: Record<EvidenceStatus, string> = {
  valid: 'review.evidence.valid',
  needs_review: 'review.evidence.needsReview',
  invalid: 'review.evidence.invalidFull',
  unverified: 'review.evidence.unverified',
}

const RUN_STEPS = [
  'review.run.step.fetch',
  'review.run.step.filter',
  'review.run.step.context',
  'review.run.step.static',
  'review.run.step.model',
  'review.run.step.evidence',
  'review.run.step.impact',
  'review.run.step.persist',
]

const STEPS = [
  ['1', 'review.section.step1.title', 'review.section.step1.desc'],
  ['2', 'review.section.step2.title', 'review.section.step2.desc'],
  ['3', 'review.section.step3.title', 'review.section.step3.desc'],
]

function useElapsed(active: boolean) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!active) {
      setElapsed(0)
      return
    }
    const started = Date.now()
    const id = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 120)
    return () => window.clearInterval(id)
  }, [active])
  return elapsed
}

export function ReviewPage({
  initialResult,
  onResult,
}: {
  initialResult: ReviewResponse | null
  onResult: (result: ReviewResponse | null, runId: string | null) => void
}) {
  const t = useT()
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [selectedMode, setSelectedMode] = useState<Mode>('plan')
  const [result, setResult] = useState<ReviewResponse | null>(initialResult)
  const [job, setJob] = useState<JobSnapshot | null>(null)
  // 发布/导出只认「当前这份结果」的 run：不能用 job.run_id 兜底，否则先跑完整审查、
  // 再跑一次计划模式时，旧 run 的发布按钮会挂在新结果下面。
  // 初值取持久化的 initialResult：切换页面再回来时不能因为本组件重挂载就丢掉 run。
  const [resultRunId, setResultRunId] = useState<string | null>(initialResult?.run?.id ?? null)
  const [severity, setSeverity] = useState<Severity | ''>('')
  const [evidence, setEvidence] = useState<EvidenceStatus | ''>('')
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const jobRef = useRef<EventSource | null>(null)
  const pollRef = useRef<number | null>(null)
  const pageRef = useRef<HTMLDivElement>(null)
  const consoleRef = useRef<HTMLDivElement | null>(null)
  const lastModeRef = useRef<Mode | null>(null)

  const elapsed = useElapsed(status.kind === 'running')

  useGSAP(
    () => {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      if (reduceMotion) return
      // 只做位移入场。这里曾用 autoAlpha:0，导致标题、说明与 PR 表单卡
      // 永久停在 visibility:hidden（整屏空白、无法操作）。
      const q = gsap.utils.selector(pageRef)
      gsap.from(q('[data-reveal]'), {
        y: 18,
        duration: 0.55,
        stagger: 0.06,
        ease: 'power2.out',
      })
    },
    { scope: pageRef },
  )
  useEffect(
    () => () => {
      abortRef.current?.abort()
      jobRef.current?.close()
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    },
    [],
  )

  // 进度控制台渲染在表单卡下方，通常在首屏之外。不主动滚动的话，
  // 用户点击「开始完整审查」后界面看起来毫无反应。
  useEffect(() => {
    if (status.kind !== 'running' || !consoleRef.current) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    consoleRef.current.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'start',
    })
  }, [status.kind])

  const validation = parsePrUrl(url)
  const busy = status.kind === 'running'
  const activeMode: Mode = status.kind === 'running' ? status.mode : selectedMode
  const activeStep = status.kind === 'running' ? Math.min(RUN_STEPS.length - 1, Math.floor(elapsed / 1.3)) : -1

  async function run(mode: Mode) {
    lastModeRef.current = mode
    if (!validation.ok) {
      setStatus({ kind: 'error', message: validation.hint ?? t('review.form.invalidUrl') })
      inputRef.current?.focus()
      return
    }
    setSelectedMode(mode)
    if (mode === 'plan') {
      await runPlan()
    } else {
      await runReviewJob()
    }
  }

  /** 计划模式：同步请求即可，没有模型调用、通常几秒返回。 */
  async function runPlan() {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setStatus({ kind: 'running', mode: 'plan', label: t('review.run.planStart') })
    setResult(null)
    setResultRunId(null)
    onResult(null, null)
    try {
      const payload = await api.plan(url.trim(), controller.signal)
      setResult(payload)
      // 计划模式不落库，run.id 通常是 null —— 发布组件据此渲染禁用态。
      setResultRunId(payload.run?.id ?? null)
      onResult(payload, payload.run?.id ?? null)
      setStatus({ kind: 'ok', mode: 'plan', message: t('review.run.planDone') })
    } catch (error) {
      handleRunError(error)
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }

  /**
   * 完整审查：提交为后台任务，用 SSE 接收逐文件进度。
   * 取消会请求服务端真正停止（在文件边界生效），而不是只断开浏览器连接。
   */
  async function runReviewJob() {
    setStatus({ kind: 'running', mode: 'review', label: t('review.run.reviewStart') })
    setResult(null)
    setResultRunId(null)
    onResult(null, null)
    setJob(null)
    jobRef.current?.close()
    jobRef.current = null

    let jobId = ''
    try {
      const started = await api.startReviewJob(url.trim())
      jobId = started.job_id
      setJob(started)
      setStatus({
        kind: 'running',
        mode: 'review',
        label: started.total_files
          ? t('review.run.reviewFiles', { count: started.total_files })
          : t('review.run.reviewPrepare'),
      })
    } catch (error) {
      handleRunError(error)
      return
    }

    const stream = new EventSource(`/api/jobs/${jobId}/events`)
    jobRef.current = stream

    /** 轮询兜底：SSE 在缓冲代理后可能不推送，轮询保证进度最终一定更新。 */
    const startPolling = () => {
      if (pollRef.current !== null) return
      pollRef.current = window.setInterval(() => {
        void api
          .job(jobId)
          .then((snapshot) => {
            setJob(snapshot)
            if (snapshot.status === 'done' || snapshot.status === 'failed' || snapshot.status === 'cancelled') {
              stopPolling()
              void finishJob(jobId)
            } else if (snapshot.total_files > 0) {
              setStatus({
                kind: 'running',
                mode: 'review',
                label: snapshot.current_file
                  ? t('review.run.reviewCurrentFile', { file: snapshot.current_file })
                  : t('review.run.reviewProgress', {
                      done: snapshot.completed_files,
                      total: snapshot.total_files,
                    }),
              })
            }
          })
          .catch(() => {
            /* 轮询失败不改变界面状态，等下一次 */
          })
      }, 2000)
    }
    const stopPolling = () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
    pollRef.current = null
    startPolling()

    stream.onmessage = (raw) => {
      let event: JobEvent
      try {
        event = JSON.parse(raw.data)
      } catch {
        return
      }
      setJob(event)

      if (event.event === 'stage' && event.message) {
        setStatus({ kind: 'running', mode: 'review', label: event.message })
      }
      if (event.event === 'file_started' && event.filename) {
        setStatus({
          kind: 'running',
          mode: 'review',
          label: t('review.run.reviewCurrentFile', { file: event.filename }),
        })
      }

      const terminal = ['done', 'failed', 'cancelled']
      if (!terminal.includes(event.event)) return

      stopPolling()
      stream.close()
      jobRef.current = null
      if (event.event === 'done') {
        void finishJob(jobId)
      } else if (event.event === 'cancelled') {
        setStatus({ kind: 'cancelled' })
      } else {
        setStatus({ kind: 'error', message: event.message || event.error || t('review.run.reviewFailed') })
      }
    }

    stream.onerror = () => {
      // SSE 断开：轮询仍在跑，先让它继续把进度补上，不立刻收尾
      stream.close()
      jobRef.current = null
    }
  }

  async function finishJob(jobId: string, fallbackOnError = false) {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    try {
      const snapshot = await api.job(jobId)
      setJob(snapshot)
      if (snapshot.status === 'done' && snapshot.result) {
        setResult(snapshot.result)
        setResultRunId(snapshot.run_id ?? snapshot.result.run?.id ?? null)
        onResult(snapshot.result, snapshot.run_id ?? snapshot.result.run?.id ?? null)
        setStatus({
          kind: 'ok',
          mode: 'review',
          // 任务口径（含抓取/过滤/落库）；下方指标条是模型审查口径，两者不冲突。
          message: t('review.run.reviewDone', {
            duration: formatDuration(snapshot.elapsed_seconds),
          }),
        })
        return
      }
      if (snapshot.status === 'cancelled') {
        setStatus({ kind: 'cancelled' })
        return
      }
      if (snapshot.status === 'failed') {
        setStatus({ kind: 'error', message: snapshot.error || t('review.run.reviewFailed') })
        return
      }
      if (!fallbackOnError) {
        setStatus({ kind: 'error', message: t('review.run.badJobState') })
      }
    } catch (error) {
      handleRunError(error)
    }
  }

  function handleRunError(error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      setStatus({ kind: 'cancelled' })
      return
    }
    const message =
      error instanceof ApiError
        ? error.message
        : error instanceof Error
          ? error.message
          : String(error)
    setStatus({
      kind: 'error',
      message,
      // status 0 = fetch 失败（本地服务未连接），按标记渲染恢复提示而不是比对文案语言。
      offline: error instanceof ApiError && error.status === 0,
    })
  }

  /** 取消：请求服务端停止任务；SSE 会回推 cancelled 事件收尾。 */
  function cancel() {
    const id = job?.job_id
    abortRef.current?.abort()
    abortRef.current = null
    if (!id) {
      setStatus({ kind: 'cancelled' })
      return
    }
    setStatus({ kind: 'running', mode: 'review', label: t('review.run.requestStop') })
    void api.cancelJob(id).catch(() => {
      setStatus({ kind: 'cancelled' })
    })
  }

  const findings = result?.review?.findings ?? []

  const counts = useMemo(() => {
    const map: Record<string, number> = {}
    for (const f of findings) map[f.severity] = (map[f.severity] ?? 0) + 1
    return map
  }, [findings])

  const visible = useMemo(
    () =>
      findings.filter(
        (f) =>
          (!severity || f.severity === severity) &&
          (!evidence || (f.evidence_status ?? 'unverified') === evidence),
      ),
    [findings, severity, evidence],
  )

  const evidenceCounts = useMemo(() => {
    const values = { valid: 0, needs_review: 0, invalid: 0, unverified: 0 }
    for (const finding of findings) values[finding.evidence_status ?? 'unverified'] += 1
    return values
  }, [findings])

  const riskLevel = result?.plan?.risk_level

  return (
    <div ref={pageRef} className="review-page">
      <div className="page-head" data-reveal>
        <div className="eyebrow">REVIEW WORKBENCH</div>
        <h1>{t('review.head.title')}</h1>
        <p className="lead">{t('review.head.lead')}</p>
      </div>

      <Card className="review-launch-card" data-reveal>
        <div className="stack">
          <div className="field">
            <label className="label" htmlFor="pr-url">
              {t('review.form.prUrl')}
            </label>
            <input
              id="pr-url"
              ref={inputRef}
              className="input"
              placeholder="https://github.com/owner/repo/pull/123"
              value={url}
              spellCheck={false}
              disabled={busy}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !busy) void run('plan')
              }}
            />
          </div>

          <div className="review-mode-grid" aria-label={t('review.form.modeAria')}>
            <button
              type="button"
              className={cx('review-mode-card', activeMode === 'plan' && 'is-selected')}
              disabled={busy}
              onClick={() => setSelectedMode('plan')}
            >
              <span className="review-mode-kicker mono">01 · SAFE START</span>
              <strong>{t('review.form.plan.title')}</strong>
              <span>{t('review.form.plan.desc')}</span>
            </button>
            <button
              type="button"
              className={cx('review-mode-card', activeMode === 'review' && 'is-selected')}
              disabled={busy}
              onClick={() => setSelectedMode('review')}
            >
              <span className="review-mode-kicker mono">02 · FULL REVIEW</span>
              <strong>{t('review.form.review.title')}</strong>
              <span>{t('review.form.review.desc')}</span>
            </button>
          </div>

          <div className="row row-wrap">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy || !url.trim()}
              onClick={() => void run('plan')}
            >
              {busy && status.kind === 'running' && status.mode === 'plan' && <Spinner />}
              {t('review.form.planAction')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !url.trim()}
              onClick={() => void run('review')}
            >
              {busy && status.kind === 'running' && status.mode === 'review' && <Spinner />}
              {t('review.form.reviewAction')}
            </button>
            {url.trim() && !validation.ok && status.kind !== 'error' && (
              <span className="dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                {validation.hint}
              </span>
            )}
            {busy ? (
              <button type="button" className="btn btn-ghost" onClick={cancel}>
                {t('review.form.cancel')}
              </button>
            ) : (
              <span
                className="row-end"
                style={{
                  fontSize: 'var(--ds-text-2xs)',
                  color: 'var(--ds-state-needs)',
                  background: 'var(--ds-sev-medium-bg)',
                  border: '1px solid rgba(255, 209, 102, 0.24)',
                  borderRadius: 'var(--ds-radius-pill)',
                  padding: '3px 10px',
                }}
              >
                {t('review.form.costWarning')}
              </span>
            )}
          </div>
        </div>
      </Card>

      {status.kind === 'running' && (
        <div ref={consoleRef} style={{ marginTop: 'var(--ds-space-4)' }} data-reveal>
          <Card className="run-console-card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="row" style={{ gap: 'var(--ds-space-2)' }}>
                <Spinner />
                <strong style={{ fontSize: 'var(--ds-text-md)' }}>{status.label}</strong>
              </span>
              <span className="mono dim">{elapsed.toFixed(1)}s</span>
            </div>
            <div style={{ marginTop: 'var(--ds-space-3)' }}>
              {job && job.total_files > 0 ? (
                <ProgressBar value={Math.round(job.progress * 100)} />
              ) : (
                <ProgressBar indeterminate />
              )}
            </div>
            {job && job.total_files > 0 && (
              <p className="mono dim" style={{ marginTop: 'var(--ds-space-2)', fontSize: 'var(--ds-text-2xs)' }}>
                {job.current_file
                  ? t('review.run.reviewProgressFile', {
                      done: job.completed_files,
                      total: job.total_files,
                      file: job.current_file,
                    })
                  : t('review.run.reviewProgress', {
                      done: job.completed_files,
                      total: job.total_files,
                    })}
              </p>
            )}
            <div className="run-pipeline">
              {RUN_STEPS.map((step, index) => (
                <div key={step} className={cx('run-step', index < activeStep ? 'is-done' : index === activeStep ? 'is-active' : '')}>
                  <span className="run-step-mark">{index < activeStep ? '✓' : index === activeStep ? '●' : '○'}</span><span>{t(step)}</span>
                </div>
              ))}
            </div>
            <p
              className="dim"
              style={{ marginTop: 'var(--ds-space-3)', fontSize: 'var(--ds-text-sm)' }}
            >
              {status.mode === 'plan' ? t('review.run.planHint') : t('review.run.reviewHint')}
            </p>
          </Card>
        </div>
      )}

      {status.kind === 'error' && (
        <div className="review-error-stack" style={{ marginTop: 'var(--ds-space-4)' }}>
          <Notice kind="error">{status.message}</Notice>
          <div className="review-error-actions">
            <span className="dim mono">{t('review.error.serverLocal')}</span>
            {lastModeRef.current && validation.ok && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void run(lastModeRef.current as Mode)}
              >
                {t('review.error.retry')}
              </button>
            )}
          </div>
          {status.offline && (
            <p className="review-recovery-hint">
              {t('review.error.recoverPre')}
              <code>pr-review serve</code>
              {t('review.error.recoverPost')}
            </p>
          )}
        </div>
      )}
      {status.kind === 'cancelled' && (
        <div style={{ marginTop: 'var(--ds-space-4)' }}>
          <Notice kind="warn">{t('review.cancelled.notice')}</Notice>
        </div>
      )}
      {status.kind === 'ok' && (
        <div style={{ marginTop: 'var(--ds-space-4)' }}>
          <Notice kind="success">{status.message}</Notice>
        </div>
      )}

      {result && (
        <>
          <Section
            eyebrow="OVERVIEW"
            title={t('review.overview.title')}
            extra={
              riskLevel ? (
                <span className={`chip chip-risk-${riskLevel}`}>
                  {/* 风险等级是规范 id（low|medium|high|critical），走词典：`高` / `High`。 */}
                  {t('review.overview.riskLevel', {
                    level: idText('panels.risk.level.', riskLevel),
                  })}
                </span>
              ) : undefined
            }
          >
            <div className="metrics">
              <Metric label={t('review.overview.filesChanged')} value={result.pr.files_changed ?? '—'} zero={!result.pr.files_changed} />
              <Metric label={t('review.overview.included')} value={result.filter?.included_count ?? '—'} zero={!result.filter?.included_count} />
              <Metric label={t('review.overview.excluded')} value={result.filter?.excluded_count ?? '—'} zero={!result.filter?.excluded_count} />
              <Metric
                label={t('review.overview.findings')}
                value={findings.length}
                zero={findings.length === 0}
                hint={
                  counts.critical
                    ? t('review.overview.criticalHint', { count: counts.critical })
                    : counts.high
                      ? t('review.overview.highHint', { count: counts.high })
                      : undefined
                }
              />
              <Metric label={t('review.overview.modelDuration')} value={formatDuration(result.run?.duration_seconds)} small />
              <Metric
                label={t('review.overview.cost')}
                value={formatCost(result.run?.total_cost)}
                small
                zero={!result.run?.total_cost}
                hint={result.run?.total_cost ? undefined : t('review.overview.costHint')}
              />
            </div>
            <div className="evidence-summary" aria-label={t('review.evidence.summaryAria')}>
              <div className="evidence-summary-lead">
                <span className="eyebrow">EVIDENCE STATUS</span>
                <strong>{t('review.evidence.lead')}</strong>
              </div>
              <div className="evidence-summary-items">
                <span className="evidence-summary-item is-valid"><b>{evidenceCounts.valid}</b> {t('review.evidence.valid')}</span>
                <span className="evidence-summary-item is-review"><b>{evidenceCounts.needs_review}</b> {t('review.evidence.needsReview')}</span>
                <span className="evidence-summary-item is-invalid"><b>{evidenceCounts.invalid}</b> {t('review.evidence.invalid')}</span>
                <span className="evidence-summary-item is-muted"><b>{evidenceCounts.unverified}</b> {t('review.evidence.unverified')}</span>
              </div>
            </div>

            {result.pr.title && (
              <Card  style={{ marginTop: 'var(--ds-space-4)' }}>
                <div className="stack" style={{ gap: 6 }}>
                  <h3>{result.pr.title}</h3>
                  <div className="row row-wrap" style={{ gap: 'var(--ds-space-3)' }}>
                    {result.pr.repository && (
                      <span className="mono dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {result.pr.repository}
                        {result.pr.pr_number ? `#${result.pr.pr_number}` : ''}
                      </span>
                    )}
                    {result.pr.author && (
                      <span className="dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {t('review.overview.author', { name: result.pr.author })}
                      </span>
                    )}
                    {result.pr.url && (
                      <a
                        href={result.pr.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        style={{ fontSize: 'var(--ds-text-sm)' }}
                      >
                        {t('review.overview.openGithub')}
                      </a>
                    )}
                  </div>
                </div>
              </Card>
            )}
          </Section>

          <Section eyebrow="DELIVER" title={t('review.section.deliver')}>
            {/* 计划模式结果没有 run（plan_only 不落库），这里传 null 让组件渲染禁用态并说明原因，
                而不是整块消失：用户至少能看到「为什么没有发布按钮」，而不是以为功能缺失。 */}
            <ReportActions runId={resultRunId} />
          </Section>

          <Section eyebrow="FOLLOW-UP" title={t('review.section.followUp')}>
            {/* 任务书写「有 result.run.id 时」挂载；这里改成只要有结果就渲染，run 缺省时
                传 undefined 让面板降级成普通对话（否则「未绑定」这条分支在真实界面里
                根本走不到，验证 1 只能靠伪造 DOM）。 */}
            <AskPanel runId={resultRunId ?? undefined} />
          </Section>

          <Section eyebrow="PLAN" title={t('review.section.plan')}>
            <div className="stack">
              {result.plan ? (
                <PlanCard plan={result.plan} />
              ) : (
                <Card>
                  <Empty mark="[ i ]" title={t('review.empty.noPlan.title')}>
                    {t('review.empty.noPlan.desc')}
                  </Empty>
                </Card>
              )}
              <ValidationCard validation={result.validation ?? {}} />
              <FilterCard filter={result.filter} />
              <InterfaceImpactCard impacts={result.interface_impacts ?? []} />
            </div>
          </Section>

          {/* 审查摘要：以前只在历史弹窗里出现，工作台里看不到「这次审查说了什么」。 */}
          {result.review?.summary && (
            <Section eyebrow="SUMMARY" title={t('panels.summary.title')}>
              <Card>
                <MarkdownLite text={result.review.summary} className="summary-text" />
              </Card>
            </Section>
          )}

          {result.review && (
            <Section
              eyebrow="FINDINGS"
              title={t('review.section.findings')}
              description={
                findings.length
                  ? t('review.section.findingsDesc', { count: findings.length })
                  : undefined
              }
            >
              {findings.length === 0 ? (
                <NoFindings />
              ) : (
                <>
                  <Card >
                    {/* 严重度分布 chips：点一下按该级别筛选，再点同一条回到全部。
                        下拉框保留（两者同步在同一份 severity 状态上）。 */}
                    <div
                      className="sev-chips"
                      role="group"
                      aria-label={t('finding.filter.severityGroup')}
                    >
                      {SEVERITIES.filter((s) => counts[s] > 0).map((s) => {
                        const active = severity === s
                        return (
                          <button
                            key={s}
                            type="button"
                            className={cx('sev-chip', `sev-${s}`)}
                            aria-pressed={active}
                            title={t(active ? 'finding.filter.clearOne' : 'finding.filter.showOnly', {
                              severity: t(SEVERITY_LABEL_KEY[s]),
                            })}
                            onClick={() => setSeverity(active ? '' : s)}
                          >
                            <i className="badge-dot" aria-hidden="true" />
                            {t(SEVERITY_LABEL_KEY[s])}
                            <b>{counts[s]}</b>
                          </button>
                        )
                      })}
                    </div>
                    <div className="toolbar" style={{ marginTop: 'var(--ds-space-4)' }}>
                      <div className="toolbar-group">
                        <span className="label">{t('review.filter.severity')}</span>
                        <select
                          className="select"
                          value={severity}
                          onChange={(e) => setSeverity(e.target.value as Severity | '')}
                        >
                          <option value="">{t('review.filter.allWithCount', { count: findings.length })}</option>
                          {SEVERITIES.filter((s) => counts[s]).map((s) => (
                            <option key={s} value={s}>
                              {`${t(SEVERITY_LABEL_KEY[s])} (${counts[s]})`}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="toolbar-group">
                        <span className="label">{t('review.filter.evidence')}</span>
                        <select
                          className="select"
                          value={evidence}
                          onChange={(e) => setEvidence(e.target.value as EvidenceStatus | '')}
                        >
                          <option value="">{t('review.filter.all')}</option>
                          {EVIDENCE.map((s) => (
                            <option key={s} value={s}>
                              {t(EVIDENCE_KEYS[s])}
                            </option>
                          ))}
                        </select>
                      </div>
                      {(severity || evidence) && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => {
                            setSeverity('')
                            setEvidence('')
                          }}
                        >
                          {t('review.filter.clear')}
                        </button>
                      )}
                      <span
                        className="row-end dim mono"
                        style={{ fontSize: 'var(--ds-text-sm)' }}
                      >
                        {visible.length} / {findings.length}
                      </span>
                    </div>
                  </Card>

                  <div className="stack" style={{ marginTop: 'var(--ds-space-4)' }}>
                    {visible.length === 0 ? (
                      <Card>
                        <Empty mark="[ ? ]" title={t('review.empty.filtered.title')}>
                          {t('review.empty.filtered.desc')}
                        </Empty>
                      </Card>
                    ) : (
                      visible.map((finding, index) => (
                        <div
                          key={
                            finding.finding_id ||
                            `${finding.file}:${finding.line_start}:${index}`
                          }
                          className={`stagger-${Math.min(index + 1, 4)}`}
                        >
                          <FindingCard
                            finding={finding}
                            runId={result.run?.id ?? null}
                            index={index}
                            prUrl={result.pr.url}
                            headSha={result.pr.head_sha}
                            prNumber={result.pr.pr_number}
                          />
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}
            </Section>
          )}

          <Section eyebrow="RAW" title={t('review.section.raw')}>
            <Card flush>
              <CardHead
                title="JSON"
                extra={
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      void navigator.clipboard?.writeText(JSON.stringify(result, null, 2))
                    }}
                  >
                    {t('review.section.copy')}
                  </button>
                }
              />
              <div style={{ padding: 'var(--ds-space-4)' }}>
                <pre className="code code" style={{ maxHeight: 380 }}>
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            </Card>
          </Section>
        </>
      )}

      {!result && status.kind === 'idle' && (
        <Section eyebrow="GETTING STARTED" title={t('review.section.startTitle')}>
          <Card>
            <div className="stack" style={{ gap: 'var(--ds-space-4)' }}>
              <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                {t('review.section.startLead')}
              </p>
              <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
                {STEPS.map(([step, titleKey, descKey]) => (
                  <div
                    key={step}
                    className="row"
                    style={{ alignItems: 'flex-start', gap: 'var(--ds-space-3)' }}
                  >
                    <span
                      className="brand-mark"
                      style={{ width: 22, height: 22, fontSize: 11, flex: 'none' }}
                    >
                      {step}
                    </span>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 'var(--ds-text-md)' }}>{t(titleKey)}</div>
                      <div className="muted" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {t(descKey)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Card>
        </Section>
      )}
    </div>
  )
}

