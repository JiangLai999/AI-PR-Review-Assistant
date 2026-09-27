import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ChatContextMeta } from '../api/types'
import { Card, Notice, Spinner, cx } from './ui'
import { t, useT } from '../i18n'

/**
 * 「追问这次审查」面板（Phase 3）。
 *
 * 只做**当前挂载期内**的多轮记忆：不落库、不写 localStorage，离开页面或刷新即清空。
 * 请求体严格是 `{run_id?, text}`（契约见 docs/claude-web-ask-panel.md），所以
 * `language` 只落到容器的 `lang` 属性上，不会混进请求体。
 *
 * 回答一律用 <pre> 等宽渲染（保留换行、转义 HTML），**不引入 Markdown 依赖**：
 * 模型输出里的 `<img onerror=...>` 之类必须是纯文本，而不是能执行的东西。
 */
type Phase = 'idle' | 'asking' | 'answered' | 'failed'

interface Failure {
  /** HTTP 状态码；0 表示连不上本地服务。 */
  status: number
  title: string
  detail: string
  /** 503（没配 Key）时在错误块里给一个去设置页的入口。 */
  toSettings?: boolean
}

interface Turn {
  id: number
  question: string
  /** 成功时的回答；失败轮为空串。 */
  answer: string
  model: string
  meta: ChatContextMeta | null
  /** 失败轮的错误描述；成功轮为 null。 */
  error: Failure | null
}

/** 有专属文案的状态码（key 形如 `ask.failure.<status>.title/detail`）。 */
const KNOWN_FAILURE_STATUSES = new Set([0, 400, 404, 415, 502, 503])

/** status → 可读文案。未知状态码给通用文案，并始终带上服务端原始 message。 */
export function describeChatFailure(status: number, message: string): Failure {
  const known = KNOWN_FAILURE_STATUSES.has(status)
  const title = known
    ? t(`ask.failure.${status}.title`)
    : status
      ? t('ask.failure.genericStatus', { status })
      : t('ask.failure.generic')
  const detail = known ? t(`ask.failure.${status}.detail`) : ''
  return {
    status,
    title,
    detail: [detail, message ? t('ask.failure.raw', { message }) : ''].filter(Boolean).join(' '),
    // 503 = 没配模型 Key：给一个去设置页的入口（文案里已经引导了）
    toSettings: status === 503,
  }
}

function toFailure(error: unknown): Failure {
  if (error instanceof ApiError) return describeChatFailure(error.status, error.message)
  const message = error instanceof Error ? error.message : String(error)
  return describeChatFailure(0, message)
}

export function AskPanel({
  runId,
  language,
  className,
}: {
  /** 要追问的那次审查；缺省时退化成普通对话（后端同样支持）。 */
  runId?: string
  /** 预留：目前只作为容器 lang 属性，不做文案切换（界面文案由 i18n 任务统一处理）。 */
  language?: string
  className?: string
}) {
  const t = useT()
  const [phase, setPhase] = useState<Phase>('idle')
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const nextIdRef = useRef(1)
  /** 提交后要把焦点还给输入框，但必须等这次提交的渲染落地（见下面的 useEffect）。 */
  const refocusRef = useRef(false)

  // 换 run 就清空会话：上一条审查的问答挂在新报告下面会误导人。
  useEffect(() => {
    setPhase('idle')
    setTurns([])
    setDraft('')
  }, [runId])

  // asking 期间输入框是 disabled，浏览器会忽略 focus()；所以在请求回调里同步还焦点是
  // 无效的（那一刻 DOM 还没重渲染）。改成等 phase 落地后再聚焦：
  // 只有真的提交过（refocusRef）才抢焦点，避免页面加载时把视口拽到面板上。
  useEffect(() => {
    if (!refocusRef.current || phase === 'asking') return
    refocusRef.current = false
    inputRef.current?.focus()
  }, [phase])

  const busy = phase === 'asking'
  const canSubmit = !busy && draft.trim().length > 0

  // token 估算只在「服务端确认绑定的就是这块面板的 run」时才显示：换一条 run 后，
  // 旧回答留下的数字会挂在新上下文上。
  const lastMeta = [...turns].reverse().find((turn) => turn.meta)?.meta ?? null
  const tokenEstimate =
    lastMeta && (lastMeta.bound_run ?? null) === (runId ?? null) ? lastMeta.token_estimate : null

  async function ask(text: string) {
    const question = text.trim()
    if (!question || busy) return
    const id = nextIdRef.current++
    setDraft('')
    setPhase('asking')
    refocusRef.current = true
    try {
      const payload = await api.chat(runId, question)
      setTurns((prev) => [
        ...prev,
        {
          id,
          question,
          answer: payload.reply ?? '',
          model: payload.model ?? '',
          meta: payload.context_meta ?? null,
          error: null,
        },
      ])
      setPhase('answered')
    } catch (error) {
      setTurns((prev) => [
        ...prev,
        { id, question, answer: '', model: '', meta: null, error: toFailure(error) },
      ])
      setPhase('failed')
    }
  }

  return (
    <Card className={cx('ask-panel', className)}>
      <div className="ask-panel-head" lang={language}>
        <div className="ask-panel-title">
          <span className="eyebrow">FOLLOW-UP</span>
          <h3>{t('ask.title')}</h3>
          <p className="ask-panel-lead">{t('ask.intro')}</p>
          {runId ? (
            <p className="ask-panel-context" data-bound="true">
              <span>{t('ask.context.bound')}</span>
              <code className="code-inline">{runId.slice(0, 8)}</code>
              {tokenEstimate !== null && (
                <span>{t('ask.context.tokens', { count: Math.round(tokenEstimate) })}</span>
              )}
            </p>
          ) : (
            <p className="ask-panel-context" data-bound="false">
              {t('ask.context.unbound')}
            </p>
          )}
        </div>
      </div>

      <form
        className="ask-panel-form"
        aria-busy={busy || undefined}
        onSubmit={(event) => {
          event.preventDefault()
          void ask(draft)
        }}
      >
        <input
          ref={inputRef}
          id="ask-panel-input"
          className="input ask-panel-input"
          type="text"
          autoComplete="off"
          value={draft}
          disabled={busy}
          aria-label={t('ask.aria')}
          placeholder={runId ? t('ask.placeholder.bound') : t('ask.placeholder.unbound')}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // 输入法用 Enter 上屏候选词。不拦住的话会把半成品问题发出去。
            if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.keyCode === 229)) {
              event.preventDefault()
            }
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          {t('ask.submit')}
        </button>
      </form>

      {busy && (
        <span className="ask-panel-hint" role="status">
          <Spinner /> {t('ask.asking')}
        </span>
      )}

      <div className="ask-panel-log" role="log" aria-live="polite" aria-label={t('ask.log.aria')}>
        {turns.length === 0 && !busy && (
          <p className="ask-panel-empty">{t('ask.empty')}</p>
        )}

        {turns.map((turn) => (
          <article key={turn.id} className="ask-panel-turn" data-error={turn.error ? 'true' : undefined}>
            <div className="ask-panel-question">
              <span className="ask-panel-role" aria-hidden="true">
                {t('ask.role.q')}
              </span>
              <p>{turn.question}</p>
            </div>

            {turn.error ? (
              <div className="ask-panel-error">
                <Notice kind="error">
                  <strong>{turn.error.title}</strong>
                  <span className="ask-panel-error-detail">{turn.error.detail}</span>
                </Notice>
                <div className="row row-wrap">
                  {turn.error.toSettings && (
                    <a className="btn btn-ghost btn-sm" href="#/settings">
                      {t('ask.gotoSettings')}
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void ask(turn.question)}
                  >
                    {t('ask.retry')}
                  </button>
                </div>
              </div>
            ) : (
              <>
                {/* 上下文被裁剪时，警告条必须在回答**上方** —— 先说明这份回答的局限，再给结论。 */}
                {turn.meta?.truncated && (
                  <Notice kind="warn">
                    {turn.meta.note || t('ask.truncatedFallback')}
                  </Notice>
                )}
                <pre className="ask-panel-answer">{turn.answer}</pre>
                <div className="ask-panel-meta">
                  <span>
                    {t('ask.answeredBy', { model: turn.model || t('ask.modelFallback') })}
                  </span>
                  {turn.meta?.sections?.length ? (
                    <span>
                      {t('ask.sections', {
                        sections: turn.meta.sections.join(t('ask.sectionSeparator')),
                      })}
                    </span>
                  ) : null}
                </div>
              </>
            )}
          </article>
        ))}
      </div>
    </Card>
  )
}
