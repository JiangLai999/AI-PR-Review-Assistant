import { useEffect, useMemo, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { api, ApiError } from '../api/client'
import type { EvidenceStatus, JobEvent, JobSnapshot, ReviewResponse, Severity } from '../api/types'
import { FindingCard } from '../components/FindingCard'
import {
  FilterCard,
  InterfaceImpactCard,
  NoFindings,
  PlanCard,
  ValidationCard,
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
import { formatCost, formatDuration, parsePrUrl } from '../lib/format'

type Mode = 'plan' | 'review'
type Status =
  | { kind: 'idle' }
  | { kind: 'running'; mode: Mode; label: string }
  | { kind: 'ok'; mode: Mode; message: string }
  | { kind: 'error'; message: string }
  | { kind: 'cancelled' }

const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'info']
const EVIDENCE: EvidenceStatus[] = ['valid', 'needs_review', 'invalid', 'unverified']

const SEVERITY_TEXT: Record<Severity, string> = {
  critical: 'CRITICAL',
  high: 'HIGH',
  medium: 'MEDIUM',
  low: 'LOW',
  info: 'INFO',
}

const EVIDENCE_TEXT: Record<EvidenceStatus, string> = {
  valid: '证据有效',
  needs_review: '待人工确认',
  invalid: '证据不成立',
  unverified: '未校验',
}

const RUN_STEPS = ['获取 PR 数据', '过滤变更文件', '构建代码上下文', '静态 / AST 分析', 'AI 结构化审查', '证据校验', '跨文件影响', '写入审查记录']

const STEPS = [
  ['1', '填写 PR 链接', '支持任意公开或你有权限访问的 GitHub 仓库。'],
  ['2', '生成审查计划', '解析 PR、过滤文件、按规则计算风险，不调用模型。'],
  ['3', '执行完整审查', '构建上下文、逐文件调用模型、校验证据并落库。'],
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
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [selectedMode, setSelectedMode] = useState<Mode>('plan')
  const [result, setResult] = useState<ReviewResponse | null>(initialResult)
  const [job, setJob] = useState<JobSnapshot | null>(null)
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
      setStatus({ kind: 'error', message: validation.hint ?? '请输入有效的 PR 链接。' })
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
    setStatus({ kind: 'running', mode: 'plan', label: '正在抓取 PR 并生成审查计划' })
    setResult(null)
    onResult(null, null)
    try {
      const payload = await api.plan(url.trim(), controller.signal)
      setResult(payload)
      onResult(payload, payload.run?.id ?? null)
      setStatus({ kind: 'ok', mode: 'plan', message: '审查计划已生成，未消耗模型调用。' })
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
    setStatus({ kind: 'running', mode: 'review', label: '正在提交审查任务' })
    setResult(null)
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
          ? `正在审查 ${started.total_files} 个文件`
          : '正在准备审查上下文',
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
                  ? `正在审查 ${snapshot.current_file}`
                  : `已完成 ${snapshot.completed_files} / ${snapshot.total_files} 个文件`,
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
          label: `正在审查 ${event.filename}`,
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
        setStatus({ kind: 'error', message: event.message || event.error || '审查失败' })
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
        onResult(snapshot.result, snapshot.run_id ?? snapshot.result.run?.id ?? null)
        setStatus({
          kind: 'ok',
          mode: 'review',
          // 任务口径（含抓取/过滤/落库）；下方指标条是模型审查口径，两者不冲突。
          message: `审查完成，总耗时 ${formatDuration(snapshot.elapsed_seconds)}。`,
        })
        return
      }
      if (snapshot.status === 'cancelled') {
        setStatus({ kind: 'cancelled' })
        return
      }
      if (snapshot.status === 'failed') {
        setStatus({ kind: 'error', message: snapshot.error || '审查失败' })
        return
      }
      if (!fallbackOnError) {
        setStatus({ kind: 'error', message: '任务状态异常，请刷新查看历史记录。' })
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
    setStatus({ kind: 'error', message })
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
    setStatus({ kind: 'running', mode: 'review', label: '正在请求停止…' })
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
        <h1>审查工作台</h1>
        <p className="lead">
          输入 GitHub Pull Request 链接。先「生成审查计划」可以在零模型成本下确认审查范围；
          确认无误后再执行完整审查。
        </p>
      </div>

      <Card className="review-launch-card" data-reveal>
        <div className="stack">
          <div className="field">
            <label className="label" htmlFor="pr-url">
              Pull Request 链接
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

          <div className="review-mode-grid" aria-label="选择审查模式">
            <button
              type="button"
              className={cx('review-mode-card', activeMode === 'plan' && 'is-selected')}
              disabled={busy}
              onClick={() => setSelectedMode('plan')}
            >
              <span className="review-mode-kicker mono">01 · SAFE START</span>
              <strong>先生成审查计划</strong>
              <span>只抓取、过滤和评估风险，不调用模型，不产生模型费用。</span>
            </button>
            <button
              type="button"
              className={cx('review-mode-card', activeMode === 'review' && 'is-selected')}
              disabled={busy}
              onClick={() => setSelectedMode('review')}
            >
              <span className="review-mode-kicker mono">02 · FULL REVIEW</span>
              <strong>直接开始完整审查</strong>
              <span>执行规则、AI、证据和跨文件分析，并写入本地历史。</span>
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
              生成审查计划
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !url.trim()}
              onClick={() => void run('review')}
            >
              {busy && status.kind === 'running' && status.mode === 'review' && <Spinner />}
              开始完整审查
            </button>
            {url.trim() && !validation.ok && status.kind !== 'error' && (
              <span className="dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
                {validation.hint}
              </span>
            )}
            {busy ? (
              <button type="button" className="btn btn-ghost" onClick={cancel}>
                取消
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
                完整审查会真实调用模型并产生费用
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
                已完成 {job.completed_files} / {job.total_files} 个文件
                {job.current_file ? ` · 正在处理 ${job.current_file}` : ''}
              </p>
            )}
            <div className="run-pipeline">
              {RUN_STEPS.map((step, index) => (
                <div key={step} className={cx('run-step', index < activeStep ? 'is-done' : index === activeStep ? 'is-active' : '')}>
                  <span className="run-step-mark">{index < activeStep ? '✓' : index === activeStep ? '●' : '○'}</span><span>{step}</span>
                </div>
              ))}
            </div>
            <p
              className="dim"
              style={{ marginTop: 'var(--ds-space-3)', fontSize: 'var(--ds-text-sm)' }}
            >
              {status.mode === 'plan'
                ? '正在解析 PR、抓取 diff 与文件内容，并按规则计算风险。'
                : '正在构建上下文、逐文件调用模型、校验证据并写入本地历史库。'}
            </p>
          </Card>
        </div>
      )}

      {status.kind === 'error' && (
        <div className="review-error-stack" style={{ marginTop: 'var(--ds-space-4)' }}>
          <Notice kind="error">{status.message}</Notice>
          <div className="review-error-actions">
            <span className="dim mono">服务端：127.0.0.1:8787 · 数据只保存在本机</span>
            {lastModeRef.current && validation.ok && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void run(lastModeRef.current as Mode)}
              >
                重试上一次操作
              </button>
            )}
          </div>
          {status.message.includes('无法连接') && (
            <p className="review-recovery-hint">
              本地服务可能未启动。请在项目目录运行 <code>pr-review serve</code>，然后重试。
            </p>
          )}
        </div>
      )}
      {status.kind === 'cancelled' && (
        <div style={{ marginTop: 'var(--ds-space-4)' }}>
          <Notice kind="warn">
            已取消。界面已停止等待；若服务端仍在处理最后一个文件，它可能会继续跑完并写入历史。
          </Notice>
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
            title="风险总览"
            extra={
              riskLevel ? (
                <span className={`chip chip-risk-${riskLevel}`}>风险等级 {riskLevel}</span>
              ) : undefined
            }
          >
            <div className="metrics">
              <Metric label="变更文件" value={result.pr.files_changed ?? '—'} zero={!result.pr.files_changed} />
              <Metric label="纳入审查" value={result.filter?.included_count ?? '—'} zero={!result.filter?.included_count} />
              <Metric label="已跳过" value={result.filter?.excluded_count ?? '—'} zero={!result.filter?.excluded_count} />
              <Metric
                label="Findings"
                value={findings.length}
                zero={findings.length === 0}
                hint={
                  counts.critical
                    ? `${counts.critical} 个 critical`
                    : counts.high
                      ? `${counts.high} 个 high`
                      : undefined
                }
              />
              <Metric label="模型审查耗时" value={formatDuration(result.run?.duration_seconds)} small />
              <Metric
                label="本次成本"
                value={formatCost(result.run?.total_cost)}
                small
                zero={!result.run?.total_cost}
                hint={result.run?.total_cost ? undefined : '计划模式不产生费用'}
              />
            </div>
            <div className="evidence-summary" aria-label="证据校验摘要">
              <div className="evidence-summary-lead">
                <span className="eyebrow">EVIDENCE STATUS</span>
                <strong>每条结论都要落回真实变更</strong>
              </div>
              <div className="evidence-summary-items">
                <span className="evidence-summary-item is-valid"><b>{evidenceCounts.valid}</b> 证据有效</span>
                <span className="evidence-summary-item is-review"><b>{evidenceCounts.needs_review}</b> 待人工确认</span>
                <span className="evidence-summary-item is-invalid"><b>{evidenceCounts.invalid}</b> 不成立</span>
                <span className="evidence-summary-item is-muted"><b>{evidenceCounts.unverified}</b> 未校验</span>
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
                        作者 {result.pr.author}
                      </span>
                    )}
                    {result.pr.url && (
                      <a
                        href={result.pr.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        style={{ fontSize: 'var(--ds-text-sm)' }}
                      >
                        在 GitHub 打开 ↗
                      </a>
                    )}
                  </div>
                </div>
              </Card>
            )}
          </Section>

          <Section eyebrow="PLAN" title="审查计划">
            <div className="stack">
              {result.plan ? (
                <PlanCard plan={result.plan} />
              ) : (
                <Card>
                  <Empty mark="[ i ]" title="本次未生成计划">
                    计划模式会生成完整的 ReviewPlan；完整审查同样会先规划再执行。
                  </Empty>
                </Card>
              )}
              <ValidationCard validation={result.validation ?? {}} />
              <FilterCard filter={result.filter} />
              <InterfaceImpactCard impacts={result.interface_impacts ?? []} />
            </div>
          </Section>

          {result.review && (
            <Section
              eyebrow="FINDINGS"
              title="审查发现"
              description={
                findings.length
                  ? `共 ${findings.length} 条，按严重度与证据状态可筛选。`
                  : undefined
              }
            >
              {findings.length === 0 ? (
                <NoFindings />
              ) : (
                <>
                  <Card >
                    <div className="toolbar">
                      <div className="toolbar-group">
                        <span className="label">严重度</span>
                        <select
                          className="select"
                          value={severity}
                          onChange={(e) => setSeverity(e.target.value as Severity | '')}
                        >
                          <option value="">全部（{findings.length}）</option>
                          {SEVERITIES.filter((s) => counts[s]).map((s) => (
                            <option key={s} value={s}>
                              {SEVERITY_TEXT[s]}（{counts[s]}）
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="toolbar-group">
                        <span className="label">证据状态</span>
                        <select
                          className="select"
                          value={evidence}
                          onChange={(e) => setEvidence(e.target.value as EvidenceStatus | '')}
                        >
                          <option value="">全部</option>
                          {EVIDENCE.map((s) => (
                            <option key={s} value={s}>
                              {EVIDENCE_TEXT[s]}
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
                          清除筛选
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
                        <Empty mark="[ ? ]" title="没有符合筛选条件的发现">
                          调整筛选条件查看其它结果。
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
                          />
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}
            </Section>
          )}

          <Section eyebrow="RAW" title="原始响应">
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
                    复制
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
        <Section eyebrow="GETTING STARTED" title="还没有审查结果">
          <Card>
            <div className="stack" style={{ gap: 'var(--ds-space-4)' }}>
              <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                推荐流程：先生成计划确认范围，验证抓取是否正常，最后才执行完整审查。
              </p>
              <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
                {STEPS.map(([step, title, desc]) => (
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
                      <div style={{ fontWeight: 600, fontSize: 'var(--ds-text-md)' }}>{title}</div>
                      <div className="muted" style={{ fontSize: 'var(--ds-text-sm)' }}>
                        {desc}
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

