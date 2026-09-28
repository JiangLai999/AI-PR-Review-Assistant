import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { PublishResponse, ReportExportFormat } from '../api/types'
import { t, useT } from '../i18n'
import { Card, Notice, Spinner, cx } from './ui'

/**
 * 发布 / 导出一体组件（Phase 1）。
 *
 * 安全不变量：**只有** `confirmPublish()` 会带 `confirm:true`，而它只可能由
 * 预览面板里的「确认发布到 GitHub PR」按钮触发；入口按钮永远只发 `confirm:false`。
 * 服务端侧 preview 不构造 GitHub 客户端，所以「预览不会误发」是双重保证。
 */
type Phase = 'idle' | 'previewing' | 'previewed' | 'publishing' | 'published' | 'failed'

interface Failure {
  /** HTTP 状态码；0 表示连不上本地服务。 */
  status: number
  title: string
  detail: string
}

/** 有专属文案的状态码（key 形如 `report.failure.<status>.title/detail`）。 */
const KNOWN_FAILURE_STATUSES = new Set([0, 400, 401, 403, 404, 409, 415, 502, 503])

/** status → 可读文案。未知状态码给通用文案，并始终带上服务端原始 message。 */
export function describePublishFailure(status: number, message: string): Failure {
  const known = KNOWN_FAILURE_STATUSES.has(status)
  const title = known
    ? t(`report.failure.${status}.title`)
    : status
      ? t('report.failure.genericStatus', { status })
      : t('report.failure.generic')
  const detail = known ? t(`report.failure.${status}.detail`) : ''
  return {
    status,
    title,
    detail: [detail, message ? t('report.failure.raw', { message }) : ''].filter(Boolean).join(' '),
  }
}

function toFailure(error: unknown): Failure {
  if (error instanceof ApiError) return describePublishFailure(error.status, error.message)
  const message = error instanceof Error ? error.message : String(error)
  return describePublishFailure(0, message)
}

/**
 * 复制正文：优先 Clipboard API；在非安全上下文（`pr-review serve --host 0.0.0.0`
 * 走局域网 IP 时）它是 undefined，回退到隐藏 textarea + execCommand。
 * 两条路都失败就返回 false —— 绝不静默显示「已复制」。
 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 落到回退路径 */
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '0'
    area.style.left = '-9999px'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

export function ReportActions({
  runId,
  className,
}: {
  /** 库里已存在的 run；计划模式结果是 null（plan_only 不落库）。 */
  runId: string | null
  className?: string
}) {
  const t = useT()
  const [phase, setPhase] = useState<Phase>('idle')
  const [preview, setPreview] = useState<PublishResponse | null>(null)
  const [outcome, setOutcome] = useState<PublishResponse | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [failedStage, setFailedStage] = useState<'preview' | 'publish'>('preview')
  const [copyState, setCopyState] = useState<'idle' | 'ok' | 'fail'>('idle')
  const copyTimer = useRef<number | null>(null)

  // 换 run 就整体复位：上一条 run 的预览正文绝不能被留在屏幕上误发。
  useEffect(() => {
    setPhase('idle')
    setPreview(null)
    setOutcome(null)
    setFailure(null)
    setFailedStage('preview')
    setCopyState('idle')
  }, [runId])

  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current)
    },
    [],
  )

  const disabled = !runId
  const busy = phase === 'previewing' || phase === 'publishing'
  const body = outcome?.comment_body ?? preview?.comment_body ?? ''
  const published = phase === 'published' && outcome !== null
  const showPreview = body !== '' && phase !== 'previewing' && !published
  const exportUrl = (format: ReportExportFormat) =>
    runId ? api.exportReportUrl(runId, format) : undefined

  async function requestPreview() {
    if (!runId || busy) return
    setFailedStage('preview')
    setFailure(null)
    setPhase('previewing')
    try {
      // 预览优先：固定 confirm:false，服务端不会向 GitHub 写任何内容。
      const payload = await api.publish(runId, false)
      setPreview(payload)
      setOutcome(null)
      setCopyState('idle')
      setPhase('previewed')
    } catch (error) {
      setFailure(toFailure(error))
      setPhase('failed')
    }
  }

  async function confirmPublish() {
    if (!runId || busy) return
    setFailedStage('publish')
    setFailure(null)
    setPhase('publishing')
    try {
      const payload = await api.publish(runId, true)
      setPreview(payload)
      setOutcome(payload)
      setPhase('published')
    } catch (error) {
      // 保留 preview：正文还在屏幕上，用户可以重试而不用重新预览。
      setFailure(toFailure(error))
      setPhase('failed')
    }
  }

  function reset() {
    setPhase('idle')
    setPreview(null)
    setOutcome(null)
    setFailure(null)
    setCopyState('idle')
  }

  async function copyBody() {
    if (!body) return
    const ok = await copyText(body)
    setCopyState(ok ? 'ok' : 'fail')
    if (copyTimer.current !== null) window.clearTimeout(copyTimer.current)
    if (ok) {
      copyTimer.current = window.setTimeout(() => setCopyState('idle'), 2000)
    }
  }

  return (
    <Card className={cx('report-actions', disabled && 'is-disabled', className)}>
      <div className="report-actions-head">
        <div className="report-actions-title">
          <span className="eyebrow">DELIVER</span>
          <h3>{t('report.title')}</h3>
          <p className="report-actions-lead">
            {t('report.subtitle.before')}
            <code className="code-inline">pr-review export-run</code>
            {t('report.subtitle.after')}
          </p>
        </div>
        <div className="report-actions-downloads">
          <a
            className="btn btn-ghost btn-sm"
            href={exportUrl('markdown')}
            download
            aria-disabled={disabled || undefined}
            onClick={(e) => {
              if (disabled) e.preventDefault()
            }}
          >
            {t('report.download.markdown')}
          </a>
          <a
            className="btn btn-ghost btn-sm"
            href={exportUrl('json')}
            // markdown 的文件名由服务端 Content-Disposition 给（pr<N>-<run8>.md）；
            // json 是内联 JSON 响应，没有该头，只能在这里给一个稳定文件名。
            download={runId ? `pr-review-${runId.slice(0, 8)}.json` : undefined}
            aria-disabled={disabled || undefined}
            onClick={(e) => {
              if (disabled) e.preventDefault()
            }}
          >
            {t('report.download.json')}
          </a>
        </div>
      </div>

      {disabled && (
        <Notice kind="info">
          {t('report.noRun')}
        </Notice>
      )}

      <div className="report-actions-bar">
        {phase === 'idle' && (
          <>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={disabled}
              onClick={() => void requestPreview()}
            >
               {t('report.publish')}
            </button>
            <span className="report-actions-hint">
               {t('report.publish.hint')}
            </span>
          </>
        )}

        {phase === 'previewing' && (
          <span className="report-actions-hint" role="status">
            <Spinner /> {t('report.preview.loading')}
          </span>
        )}

        {phase === 'previewed' && (
          <div className="report-actions-confirm">
            <div className="report-actions-warning">
              <strong>{t('report.confirm.title')}</strong>
              <span>{t('report.confirm.body')}</span>
            </div>
            <div className="row row-wrap">
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy}
                onClick={() => void confirmPublish()}
              >
                 {t('report.confirm.button')}
              </button>
              <button type="button" className="btn btn-ghost" onClick={reset}>
                 {t('report.cancel')}
              </button>
            </div>
          </div>
        )}

        {phase === 'publishing' && (
          <span className="report-actions-hint" role="status">
            <Spinner /> {t('report.publishing')}
          </span>
        )}

        {published && outcome && (
          <div className="report-actions-outcome">
            <Notice kind={outcome.status === 'already_published' ? 'warn' : 'success'}>
              {outcome.status === 'already_published'
                ? t('report.republished')
                : outcome.status === 'published'
                  ? t('report.published')
                  : t('report.notConfirmed')}
              {outcome.message ? ` ${outcome.message}` : ''}
            </Notice>
            <div className="row row-wrap report-actions-links">
              {outcome.comment_url ? (
                <a href={outcome.comment_url} target="_blank" rel="noreferrer noopener">
                   {t('report.open')}
                </a>
              ) : (
                <span className="dim">
                  {t('report.noLink')}
                </span>
              )}
              {outcome.status === 'already_published' && (
                <span className="dim">
                  {t('report.ledgerNote')}
                </span>
              )}
            </div>
            <div className="row row-wrap">
              <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>
                {t('report.repreview')}
              </button>
            </div>
          </div>
        )}

        {phase === 'failed' && failure && (
          <div className="report-actions-error" role="alert">
            <Notice kind="error">
              <strong>{failure.title}</strong>
              <span className="report-actions-error-detail">{failure.detail}</span>
            </Notice>
            <div className="row row-wrap">
              {failedStage === 'publish' && body !== '' && (
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={disabled}
                  onClick={() => void confirmPublish()}
                >
                  {t('report.retryPublish')}
                </button>
              )}
              <button
                type="button"
                className="btn btn-ghost"
                disabled={disabled}
                onClick={() => void requestPreview()}
              >
                {failedStage === 'publish' ? t('report.repreview') : t('report.retryPreview')}
              </button>
            </div>
          </div>
        )}
      </div>

      {showPreview && (
        <div className="report-actions-preview">
          <div className="report-actions-preview-head">
            <span className="report-actions-preview-title">
              {t('report.preview.title', { chars: body.length })}
            </span>
            <span className="row" style={{ gap: 'var(--ds-space-2)' }}>
              {copyState === 'ok' && <span className="report-actions-copied">{t('report.copied')}</span>}
              {copyState === 'fail' && (
                <span className="report-actions-copy-failed">{t('report.copyFailed')}</span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void copyBody()}
              >
                {t('report.copy')}
              </button>
            </span>
          </div>
          <pre className="code report-actions-preview-body">{body}</pre>
        </div>
      )}

      {!disabled && !published && (
        <p className="report-actions-footnote">
          {t('report.footer.before')}
          <code className="code-inline">export-run</code>
          {t('report.footer.after')}
        </p>
      )}
    </Card>
  )
}
