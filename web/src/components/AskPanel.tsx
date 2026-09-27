import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ChatContextMeta, ChatTurn } from '../api/types'
import { CollapsibleText } from './ReviewPanels'
import { Card, Notice, Spinner, cx } from './ui'
import { t, useT } from '../i18n'

/**
 * 「追问这次审查」面板。
 *
 * 绑定 `runId` 时问答**落库**，进入面板先拉 `GET /api/chat/history` 再渲染；
 * 未绑定 run 的普通对话不落库、不拉历史，仍是当前挂载期内存。
 * 请求体严格是 `{run_id?, text}`（契约见 docs/claude-web-ask-panel.md），所以
 * `language` 只落到容器的 `lang` 属性上，不会混进请求体。
 *
 * 回答用受限 Markdown 渲染器（`<CollapsibleText>` 内是 `<MarkdownLite>`，无
 * dangerouslySetInnerHTML，模型里的 HTML 只会当纯文本）且**每条都能折叠**：
 * 长回答默认折起，短回答默认展开但也留折叠控件。错误分支/截断警告/焦点归还
 * 逻辑保持不变。
 */
type Phase = 'idle' | 'asking' | 'answered' | 'failed'

type HistoryState = 'idle' | 'loading' | 'ready' | 'error'

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
  /** 墙钟耗时（毫秒）；历史里拿不到时为 null。 */
  durationMs: number | null
  /** `usage.total_tokens`；没有就为 null，界面不显示 token 行。 */
  totalTokens: number | null
  /** 服务端时间戳原样保存，显示时只截 `HH:MM:SS`。 */
  createdAt: string | null
  /** 是否已写入追问历史；false → 元信息标「未保存」。历史轮恒为 true。 */
  persisted: boolean | null
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

/** `duration_ms` → `1.8s` 这类展示串；没有耗时就返回 null。 */
function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms)) return null
  return `${(ms / 1000).toFixed(1)}s`
}

/** `created_at` → `HH:MM:SS`；解析不出时间就原样返回（不引日期库）。 */
function formatClock(value: string | null | undefined): string | null {
  if (!value) return null
  const match = /(\d{2}:\d{2}:\d{2})/.exec(value)
  return match ? match[1] : value
}

/** 历史里的 `context_meta` 可能是 `{}` 或缺字段，补全成本地展示用的形状。 */
function normalizeMeta(raw: Partial<ChatContextMeta> | null | undefined): ChatContextMeta | null {
  if (!raw || Object.keys(raw).length === 0) return null
  return {
    bound_run: raw.bound_run ?? null,
    token_estimate: raw.token_estimate ?? null,
    sections: raw.sections ?? [],
    truncated: Boolean(raw.truncated),
    note: raw.note ?? '',
  }
}

/** 把后端的 user/assistant 流水拼成本面板的问答对；落单的 user/assistant 也保留。 */
function turnsFromHistory(items: ChatTurn[]): Turn[] {
  const result: Turn[] = []
  let id = 0
  let pending: Turn | null = null
  for (const item of items) {
    if (item.role === 'user') {
      if (pending) result.push(pending)
      pending = {
        id: ++id,
        question: item.content,
        answer: '',
        model: '',
        meta: null,
        error: null,
        durationMs: null,
        totalTokens: null,
        createdAt: item.created_at || null,
        persisted: true,
      }
      continue
    }
    const meta = normalizeMeta(item.context_meta)
    const durationMs = item.duration_ms ?? null
    const totalTokens = item.usage?.total_tokens ?? null
    if (pending) {
      pending.answer = item.content
      pending.model = item.model || ''
      pending.meta = meta
      pending.durationMs = durationMs
      pending.totalTokens = totalTokens
      pending.createdAt = item.created_at || pending.createdAt
      result.push(pending)
      pending = null
    } else {
      result.push({
        id: ++id,
        question: '',
        answer: item.content,
        model: item.model || '',
        meta,
        error: null,
        durationMs,
        totalTokens,
        createdAt: item.created_at || null,
        persisted: true,
      })
    }
  }
  if (pending) result.push(pending)
  return result
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
  const [historyState, setHistoryState] = useState<HistoryState>('idle')
  const [historyError, setHistoryError] = useState<Failure | null>(null)
  const [historyRetryKind, setHistoryRetryKind] = useState<'load' | 'clear'>('load')
  const [clearing, setClearing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const nextIdRef = useRef(1)
  /** 提交后要把焦点还给输入框，但必须等这次提交的渲染落地（见下面的 useEffect）。 */
  const refocusRef = useRef(false)
  /** 递增序号：换 run / 重拉时让在途请求作废，避免旧响应覆盖新会话。 */
  const loadSeqRef = useRef(0)

  /**
   * 拉取当前 run 的追问历史并整段替换本地轮次。
   * **失败时不碰 `turns`**（保留已有内容），只挂一条可重试的错误提示。
   */
  async function loadHistory() {
    if (!runId) return
    const seq = ++loadSeqRef.current
    setHistoryState('loading')
    setHistoryError(null)
    try {
      const payload = await api.chatHistory(runId)
      if (seq !== loadSeqRef.current) return
      setTurns(turnsFromHistory(payload.turns))
      nextIdRef.current = payload.turns.length + 1
      setHistoryState('ready')
    } catch (error) {
      if (seq !== loadSeqRef.current) return
      setHistoryState('error')
      setHistoryError(toFailure(error))
      setHistoryRetryKind('load')
    }
  }

  async function clearHistory() {
    if (!runId || turns.length === 0 || clearing) return
    if (!window.confirm(t('ask.history.clearConfirm'))) return
    setClearing(true)
    setHistoryError(null)
    try {
      await api.clearChatHistory(runId)
      setTurns([])
      setHistoryState('ready')
    } catch (error) {
      setHistoryError(toFailure(error))
      setHistoryRetryKind('clear')
    } finally {
      setClearing(false)
    }
  }

  function retryHistory() {
    if (historyRetryKind === 'clear') void clearHistory()
    else void loadHistory()
  }

  // 换 run：先清掉上一条审查的问答（挂在新报告下会误导人），再拉这条 run 的历史。
  // 未绑定 run 时不请求历史，保持普通对话形态。
  useEffect(() => {
    setPhase('idle')
    setDraft('')
    setTurns([])
    setHistoryError(null)
    setHistoryRetryKind('load')
    loadSeqRef.current++
    if (!runId) {
      setHistoryState('idle')
      return
    }
    void loadHistory()
    // loadHistory 跟随当前 render 的 runId，这里只在 runId 变化时重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          durationMs: payload.duration_ms ?? null,
          totalTokens: payload.usage?.total_tokens ?? null,
          createdAt: payload.created_at ?? null,
          persisted: payload.persisted,
        },
      ])
      setPhase('answered')
    } catch (error) {
      setTurns((prev) => [
        ...prev,
        {
          id,
          question,
          answer: '',
          model: '',
          meta: null,
          error: toFailure(error),
          durationMs: null,
          totalTokens: null,
          createdAt: null,
          persisted: null,
        },
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
        {turns.length > 0 && (
          <div className="ask-panel-head-actions">
            <p className="ask-panel-status">
              {runId
                ? t('ask.history.statusSaved', { count: turns.length })
                : t('ask.history.statusUnsaved', { count: turns.length })}
            </p>
            {runId && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={busy || clearing}
                onClick={() => void clearHistory()}
              >
                {t('ask.history.clear')}
              </button>
            )}
          </div>
        )}
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

      {historyState === 'loading' && (
        <span className="ask-panel-hint" role="status">
          <Spinner /> {t('ask.history.loading')}
        </span>
      )}

      {historyError && (
        <div className="ask-panel-history-error">
          <Notice kind="error">
            <strong>{historyError.title}</strong>
            <span className="ask-panel-error-detail">{historyError.detail}</span>
          </Notice>
          <div className="row row-wrap">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy || clearing || historyState === 'loading'}
              onClick={retryHistory}
            >
              {t('ask.retry')}
            </button>
          </div>
        </div>
      )}

      <div className="ask-panel-log" role="log" aria-live="polite" aria-label={t('ask.log.aria')}>
        {turns.length === 0 && !busy && historyState !== 'loading' && !historyError && (
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
                <div className="ask-panel-answer">
                  {/* 每条回答都可折叠（用户明确要求「无论文本大小均可折叠」）；
                      历史回填的轮次与现场提问走的是同一个分支，行为一致。 */}
                  <CollapsibleText text={turn.answer} />
                </div>
                <div className="ask-panel-meta">
                  <span>
                    {t('ask.answeredBy', { model: turn.model || t('ask.modelFallback') })}
                  </span>
                  {formatDuration(turn.durationMs) && (
                    <span>{formatDuration(turn.durationMs)}</span>
                  )}
                  {turn.totalTokens != null && (
                    <span>{t('ask.meta.tokens', { count: turn.totalTokens })}</span>
                  )}
                  {formatClock(turn.createdAt) && <span>{formatClock(turn.createdAt)}</span>}
                  {turn.meta?.sections?.length ? (
                    <span>
                      {t('ask.sections', {
                        sections: turn.meta.sections.join(t('ask.sectionSeparator')),
                      })}
                    </span>
                  ) : null}
                  {turn.persisted === false && (
                    <span className="ask-panel-unsaved">{t('ask.history.unsaved')}</span>
                  )}
                </div>
              </>
            )}
          </article>
        ))}
      </div>
    </Card>
  )
}
