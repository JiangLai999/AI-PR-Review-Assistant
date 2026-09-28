import { useEffect, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import type { FeedbackStatus, Finding } from '../api/types'
import { api } from '../api/client'
// `.jsx` 后缀是**必须的**：同目录下 `markdownLite.ts` 与 `MarkdownLite.tsx` 只差大小写，
// 在大小写不敏感的文件系统（Windows）上写 `./MarkdownLite` 会解析到前者。与 AskPanel 一致。
import { MarkdownLite } from './MarkdownLite.jsx'
import { blobUrl, diffAnchorUrl } from './findingLinks'
import { Chip, EvidenceBadge, SeverityBadge, cx } from './ui'
import { useT } from '../i18n'

/** 反馈选项只存 i18n key（模块级常量不能固化语言）。 */
const FEEDBACK_OPTIONS: { value: FeedbackStatus; labelKey: string }[] = [
  { value: 'accepted', labelKey: 'finding.feedback.accepted' },
  { value: 'rejected', labelKey: 'finding.feedback.rejected' },
  { value: 'fixed', labelKey: 'finding.feedback.fixed' },
  { value: 'needs_review', labelKey: 'finding.feedback.needs_review' },
]

/** 反馈值 → 词条 key：顶部 chip 与动作条按钮共用同一套文案，避免两处各写一遍。 */
const FEEDBACK_LABEL_KEY: Record<string, string> = Object.fromEntries(
  FEEDBACK_OPTIONS.map((option) => [option.value, option.labelKey]),
)

/** 文件后缀 → 代码块语言标签；未知后缀留 `text`（MarkdownLite 不显示占位标签）。 */
const LANG_BY_EXT: Record<string, string> = {
  py: 'python',
  pyi: 'python',
  ts: 'ts',
  tsx: 'ts',
  js: 'js',
  jsx: 'js',
  mjs: 'js',
  cjs: 'js',
  md: 'markdown',
  markdown: 'markdown',
}

function sourceLabel(sources?: string[]): string {
  if (!sources?.length) return 'ai_analysis'
  return sources.join(' + ')
}

function codeLang(file: string): string {
  const dot = file.lastIndexOf('.')
  if (dot < 0) return 'text'
  return LANG_BY_EXT[file.slice(dot + 1).toLowerCase()] ?? 'text'
}

/**
 * 片段里只要有**一行以 3+ 反引号开头**，围栏就会被 MarkdownLite 提前闭合
 * （它的 FENCE_RE 不要求闭合围栏与开围栏等长）。这种片段（例如被审查的 Markdown
 * 文档）退回朴素 `<pre>`，而不是渲染出半截代码 + 一堆散段落。
 */
function fenceSafe(code: string): boolean {
  return !/^ {0,3}`{3,}/m.test(code)
}

/** 包一层围栏交给 MarkdownLite：白拿 lang 标签 + 复制按钮 + >15 行折叠。 */
function fencedCode(code: string, lang: string): string {
  const runs = code.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  const marker = '`'.repeat(Math.max(3, longest + 1))
  return `${marker}${lang}\n${code}\n${marker}`
}

export function FindingCard({
  finding,
  runId,
  index,
  initialFeedback,
  prUrl,
  headSha,
  prNumber,
}: {
  finding: Finding
  runId?: string | null
  index: number
  initialFeedback?: string
  /** PR 页面链接；与 `headSha` 一起才能把「文件:行」变成可点的 GitHub 行锚。 */
  prUrl?: string
  headSha?: string
  /** PR 编号；与 `prUrl` 一起才能拼出「在 Files changed 里定位」的 diff 锚。 */
  prNumber?: number
}) {
  const t = useT()
  const [open, setOpen] = useState(index === 0)
  const [feedback, setFeedback] = useState<string | undefined>(initialFeedback)
  const [saving, setSaving] = useState<FeedbackStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [diffHref, setDiffHref] = useState<string | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  /**
   * 「打开 diff」的链接要算 sha256(path)，是异步的；拿不到就保持 null → 该动作**不渲染**
   * （宁可不给，也不给错链接）。哈希按路径在模块级缓存，一屏多条 finding 不会重复算。
   */
  useEffect(() => {
    let alive = true
    setDiffHref(null)
    void diffAnchorUrl(prUrl, prNumber, finding.file, finding.line_start, finding.line_end).then(
      (href) => {
        if (alive) setDiffHref(href)
      },
    )
    return () => {
      alive = false
    }
  }, [prUrl, prNumber, finding.file, finding.line_start, finding.line_end])

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
  const locationLabel = `${finding.file}:${lineLabel}`
  const locationUrl = blobUrl(prUrl, headSha, finding.file, finding.line_start, finding.line_end)
  // 尾随换行会让 MarkdownLite 多渲染一行空白，先削掉；片段内容本身不做任何改动。
  const snippet = finding.code_snippet?.replace(/\n+$/, '') ?? ''
  const feedbackLabel =
    feedback && FEEDBACK_LABEL_KEY[feedback] ? t(FEEDBACK_LABEL_KEY[feedback]) : feedback

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
        </div>
        <EvidenceBadge value={status} />
      </div>

      {/* 元信息 chip 序列放在展开按钮**之外**：里面有 GitHub 链接，
          交互元素不能嵌在 role="button" 里（否则键盘/读屏都够不着它）。 */}
      <div className="finding-meta finding-meta-row">
        {locationUrl ? (
          <a
            className="chip chip-link"
            href={locationUrl}
            target="_blank"
            rel="noreferrer noopener"
            title={t('finding.location.open', { location: locationLabel })}
          >
            <span className="chip-label">{t('finding.location.file')}</span>
            <span className="mono">{locationLabel}</span>
            <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <Chip>{locationLabel}</Chip>
        )}
        {/* 第二个动作：跳到 PR 的 Files changed 并定位到该文件那一段。
            算不出 sha256（或拿不到 pr_number）时整条不渲染 —— 见上面的 useEffect。 */}
        {diffHref && (
          <a
            className="chip chip-link"
            href={diffHref}
            target="_blank"
            rel="noreferrer noopener"
            title={t('finding.location.diffOpen', { location: locationLabel })}
          >
            <span className="chip-label">{t('finding.location.diff')}</span>
            <span aria-hidden="true">↗</span>
          </a>
        )}
        <Chip>{finding.category}</Chip>
        <Chip>{t('finding.confidence', { value: finding.confidence.toFixed(2) })}</Chip>
        <Chip>{sourceLabel(finding.sources)}</Chip>
        {feedbackLabel && (
          <Chip accent>{t('finding.feedback.marked', { value: feedbackLabel })}</Chip>
        )}
      </div>

      {open && (
        <div ref={bodyRef} className="finding-body">
          {/* 问题/建议走 MarkdownLite：模型常在这两段里写 `code`、**加粗**、列表，
              纯文本渲染会把反引号、星号原样露出来（用户样例里就有 `raw.get(...)`）。 */}
          <div className="finding-field">
            <span className="finding-field-label">{t('finding.field.problem')}</span>
            <MarkdownLite text={finding.problem} className="finding-text" />
          </div>
          <div className="finding-field">
            <span className="finding-field-label">{t('finding.field.suggestion')}</span>
            <MarkdownLite text={finding.suggestion} className="finding-text" />
          </div>

          {snippet && (
            <div className="finding-field">
              <span className="finding-field-label">{t('finding.field.snippet')}</span>
              {fenceSafe(snippet) ? (
                <MarkdownLite text={fencedCode(snippet, codeLang(finding.file))} />
              ) : (
                <pre className="code">{snippet}</pre>
              )}
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

          {/* 动作条与详情分离：虚线分隔 + 独立成块，避免和上面的证据说明混成一坨。 */}
          <div className="finding-actions-bar">
            <span className="finding-field-label">{t('finding.feedback.title')}</span>
            <div className="finding-actions">
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
            </div>
            {error && <span className="finding-actions-error">{error}</span>}
          </div>
        </div>
      )}
    </article>
  )
}
