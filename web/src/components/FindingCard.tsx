import { useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import type { FeedbackStatus, Finding } from '../api/types'
import { api } from '../api/client'
import { EvidenceBadge, SeverityBadge, cx } from './ui'
import { useT } from '../i18n'

/** 反馈选项只存 i18n key（模块级常量不能固化语言）。 */
const FEEDBACK_OPTIONS: { value: FeedbackStatus; labelKey: string }[] = [
  { value: 'accepted', labelKey: 'finding.feedback.accepted' },
  { value: 'rejected', labelKey: 'finding.feedback.rejected' },
  { value: 'fixed', labelKey: 'finding.feedback.fixed' },
  { value: 'needs_review', labelKey: 'finding.feedback.needs_review' },
]

function sourceLabel(sources?: string[]): string {
  if (!sources?.length) return 'ai_analysis'
  return sources.join(' + ')
}

export function FindingCard({
  finding,
  runId,
  index,
  initialFeedback,
}: {
  finding: Finding
  runId?: string | null
  index: number
  initialFeedback?: string
}) {
  const t = useT()
  const [open, setOpen] = useState(index === 0)
  const [feedback, setFeedback] = useState<string | undefined>(initialFeedback)
  const [saving, setSaving] = useState<FeedbackStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  // 展开时轻微淡入下滑；收起直接隐藏（高度动画在 React 条件渲染下收益低）。
  useGSAP(
    () => {
      if (!open || !bodyRef.current) return
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      gsap.from(bodyRef.current, { opacity: 0, y: -6, duration: 0.28, ease: 'power2.out' })
    },
    { dependencies: [open] },
  )

  const status = finding.evidence_status ?? 'unverified'
  const issues = finding.evidence_issues ?? []
  const lineLabel =
    finding.line_end && finding.line_end !== finding.line_start
      ? `${finding.line_start}–${finding.line_end}`
      : String(finding.line_start)

  async function submit(value: FeedbackStatus) {
    if (!runId || !finding.finding_id) {
      setError(t('finding.feedback.missingIds'))
      return
    }
    setSaving(value)
    setError(null)
    try {
      await api.feedback(runId, finding.finding_id, value)
      setFeedback(value)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(null)
    }
  }

  return (
    <article className="finding">
      <div
        className="finding-head"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((v) => !v)
          }
        }}
      >
        <span className="chevron" data-open={open}>
          ▸
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row row-wrap" style={{ gap: 'var(--ds-space-2)' }}>
            <SeverityBadge value={finding.severity} />
            <span className="finding-title">{finding.title}</span>
          </div>
          <div className="finding-meta">
            <span>
              {finding.file}:{lineLabel}
            </span>
            <span>·</span>
            <span>{finding.category}</span>
            <span>·</span>
            <span>{t('finding.confidence', { value: finding.confidence.toFixed(2) })}</span>
            <span>·</span>
            <span>{sourceLabel(finding.sources)}</span>
            {feedback && (
              <>
                <span>·</span>
                <span className="fb-tag">{t('finding.feedback.marked', { value: feedback })}</span>
              </>
            )}
          </div>
        </div>
        <EvidenceBadge value={status} />
      </div>

      {open && (
        <div ref={bodyRef} className="finding-body">
          <div className="finding-field">
            <span className="finding-field-label">{t('finding.field.problem')}</span>
            <p className="finding-text">{finding.problem}</p>
          </div>
          <div className="finding-field">
            <span className="finding-field-label">{t('finding.field.suggestion')}</span>
            <p className="finding-text">{finding.suggestion}</p>
          </div>

          {finding.code_snippet && (
            <div className="finding-field">
              <span className="finding-field-label">{t('finding.field.snippet')}</span>
              <pre className="code">{finding.code_snippet}</pre>
            </div>
          )}

          {issues.length > 0 && (
            <div className="finding-field">
              <span className="finding-field-label">{t('finding.field.evidenceIssues')}</span>
              <ul
                className="finding-text"
                style={{ margin: 0, paddingLeft: '1.15em', display: 'grid', gap: 3 }}
              >
                {issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="finding-actions">
            <span className="finding-field-label" style={{ alignSelf: 'center' }}>
              {t('finding.feedback.title')}
            </span>
            {FEEDBACK_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={cx('btn', 'btn-ghost', feedback === option.value && 'btn-secondary')}
                disabled={saving !== null}
                onClick={() => submit(option.value)}
              >
                {saving === option.value ? t('finding.feedback.saving') : t(option.labelKey)}
              </button>
            ))}
            {error && (
              <span style={{ color: 'var(--ds-sev-critical)', fontSize: 'var(--ds-text-sm)' }}>
                {error}
              </span>
            )}
          </div>
        </div>
      )}
    </article>
  )
}
