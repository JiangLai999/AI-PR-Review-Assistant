import { useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import type { FeedbackStatus, Finding } from '../api/types'
import { api } from '../api/client'
import { EvidenceBadge, SeverityBadge, cx } from './ui'

const FEEDBACK_OPTIONS: { value: FeedbackStatus; label: string }[] = [
  { value: 'accepted', label: '确认问题' },
  { value: 'rejected', label: '误报' },
  { value: 'fixed', label: '已修复' },
  { value: 'needs_review', label: '待确认' },
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
      setError('该结果缺少 run_id 或 finding_id，无法记录反馈。')
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
            <span>置信度 {finding.confidence.toFixed(2)}</span>
            <span>·</span>
            <span>{sourceLabel(finding.sources)}</span>
            {feedback && (
              <>
                <span>·</span>
                <span className="fb-tag">已标记：{feedback}</span>
              </>
            )}
          </div>
        </div>
        <EvidenceBadge value={status} />
      </div>

      {open && (
        <div ref={bodyRef} className="finding-body">
          <div className="finding-field">
            <span className="finding-field-label">问题</span>
            <p className="finding-text">{finding.problem}</p>
          </div>
          <div className="finding-field">
            <span className="finding-field-label">建议</span>
            <p className="finding-text">{finding.suggestion}</p>
          </div>

          {finding.code_snippet && (
            <div className="finding-field">
              <span className="finding-field-label">代码片段</span>
              <pre className="code">{finding.code_snippet}</pre>
            </div>
          )}

          {issues.length > 0 && (
            <div className="finding-field">
              <span className="finding-field-label">证据校验说明</span>
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
              人工反馈
            </span>
            {FEEDBACK_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={cx('btn', 'btn-ghost', feedback === option.value && 'btn-secondary')}
                disabled={saving !== null}
                onClick={() => submit(option.value)}
              >
                {saving === option.value ? '记录中…' : option.label}
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
