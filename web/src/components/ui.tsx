import { useRef } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import type { EvidenceStatus, Severity } from '../api/types'

/** 小工具：拼接类名，自动丢弃 falsy 项。 */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'CRITICAL',
  high: 'HIGH',
  medium: 'MEDIUM',
  low: 'LOW',
  info: 'INFO',
}

const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  valid: '证据有效',
  needs_review: '待人工确认',
  invalid: '证据不成立',
  unverified: '未校验',
}

export function SeverityBadge({ value }: { value: Severity }) {
  return (
    <span className={cx('badge', `sev-${value}`)}>
      <i className="badge-dot" />
      {SEVERITY_LABEL[value] ?? value}
    </span>
  )
}

export function EvidenceBadge({ value }: { value: EvidenceStatus }) {
  return (
    <span className={cx('badge', `st-${value}`)}>
      <i className="badge-dot" />
      {EVIDENCE_LABEL[value] ?? value}
    </span>
  )
}

export function Chip({ children, accent }: { children: ReactNode; accent?: boolean }) {
  return <span className={cx('chip', accent && 'chip-accent')}>{children}</span>
}

export function Card({
  children,
  className,
  flush,
  style,
}: {
  children: ReactNode
  className?: string
  flush?: boolean
  style?: CSSProperties
}) {
  return (
    <div className={cx('card', flush && 'card-flush', className)} style={style}>
      {children}
    </div>
  )
}

export function CardHead({ title, extra }: { title: ReactNode; extra?: ReactNode }) {
  return (
    <div className="card-head">
      <h3>{title}</h3>
      {extra}
    </div>
  )
}

export function Section({
  eyebrow,
  title,
  description,
  extra,
  children,
  ...rest
}: {
  eyebrow?: string
  title?: ReactNode
  description?: ReactNode
  extra?: ReactNode
  children?: ReactNode
} & Record<`data-${string}`, string | boolean | undefined>) {
  return (
    <section className="section" {...rest}>
      {(eyebrow || title) && (
        <div className="section-head">
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && <h2>{title}</h2>}
            {description && (
              <p className="muted" style={{ marginTop: 6, fontSize: 'var(--ds-text-md)' }}>
                {description}
              </p>
            )}
          </div>
          {extra}
        </div>
      )}
      {children}
    </section>
  )
}

export function Metric({
  label,
  value,
  hint,
  small,
  zero,
}: {
  label: string
  value: ReactNode
  hint?: string
  small?: boolean
  /** 数值为 0 / — 等空态时置 true，降透明度弱化 */
  zero?: boolean
}) {
  const valueRef = useRef<HTMLDivElement>(null)
  const prevNumberRef = useRef(0)

  // 整数指标做数字滚动（0 → n）；非数字值（时间、金额、—）直接渲染。
  useGSAP(
    () => {
      if (typeof value !== 'number') return
      const el = valueRef.current
      if (!el) return
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el.textContent = String(value)
        prevNumberRef.current = value
        return
      }
      const counter = { v: prevNumberRef.current }
      const tween = gsap.to(counter, {
        v: value,
        duration: 0.7,
        ease: 'power2.out',
        onUpdate: () => {
          el.textContent = String(Math.round(counter.v))
        },
      })
      prevNumberRef.current = value
      return () => {
        tween.kill()
      }
    },
    { dependencies: [value] },
  )

  return (
    <div className="metric" data-zero={zero ? 'true' : undefined}>
      <div className="metric-key">{label}</div>
      <div ref={valueRef} className={cx('metric-value', small && 'metric-value-sm')}>
        {value}
      </div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  )
}

export function Notice({
  kind = 'info',
  children,
  action,
}: {
  kind?: 'info' | 'error' | 'success' | 'warn'
  children: ReactNode
  action?: ReactNode
}) {
  const mark = { info: 'i', error: '!', success: '✓', warn: '!' }[kind]
  return (
    <div className={cx('notice', `notice-${kind}`)} role={kind === 'error' ? 'alert' : undefined}>
      <span className="notice-icon">{mark}</span>
      <span style={{ flex: 1, minWidth: 0 }}>{children}</span>
      {action}
    </div>
  )
}

export function Empty({
  mark = '[ ]',
  title,
  children,
}: {
  mark?: string
  title: string
  children?: ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-mark">{mark}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

export function ProgressBar({ value, indeterminate }: { value?: number; indeterminate?: boolean }) {
  if (indeterminate) {
    return (
      <div className="progress progress-indeterminate" role="progressbar" aria-busy="true">
        <div className="progress-fill" style={{ width: '100%' }} />
      </div>
    )
  }
  return (
    <div className="progress" role="progressbar" aria-valuenow={value ?? 0}>
      <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, value ?? 0))}%` }} />
    </div>
  )
}
