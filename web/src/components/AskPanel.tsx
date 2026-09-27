import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ChatContextMeta } from '../api/types'
import { Card, Notice, Spinner, cx } from './ui'

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

const FAILURE_TEXT: Record<number, { title: string; detail: string; toSettings?: boolean }> = {
  0: { title: '无法连接到本地服务', detail: '请确认 pr-review serve 仍在运行，然后重试。' },
  400: { title: '问题内容不合法', detail: '请求缺少 text 字段。刷新页面后重试。' },
  404: {
    title: '该审查记录已不存在',
    detail: '这条 run 可能已被清理。可在「历史审查」里换一条记录，或重新跑一次完整审查。',
  },
  415: { title: '请求被本地服务拒绝', detail: '跨站或非 JSON 请求会被服务端挡掉；请从本机页面重试。' },
  502: { title: '模型调用失败', detail: '上游模型返回了错误，可稍后重试。' },
  503: {
    title: '未配置模型 API Key',
    detail: '请到「设置」页填写模型 Key，或把运行档位切到本地模型（Ollama 等）后重试。',
    toSettings: true,
  },
}

/** status → 可读文案。未知状态码给通用文案，并始终带上服务端原始 message。 */
export function describeChatFailure(status: number, message: string): Failure {
  const known = FAILURE_TEXT[status]
  return {
    status,
    title: known?.title ?? (status ? `追问失败（HTTP ${status}）` : '追问失败'),
    detail: [known?.detail, message ? `原始信息：${message}` : ''].filter(Boolean).join(' '),
    toSettings: known?.toSettings,
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
          <h3>追问这次审查</h3>
          <p className="ask-panel-lead">
            就这次审查继续提问。回答会连同报告上下文一起发给当前配置的模型；
            对话只留在当前页面，不落库，切走或刷新即清空。
          </p>
          {runId ? (
            <p className="ask-panel-context" data-bound="true">
              <span>只读上下文 · 审查记录</span>
              <code className="code-inline">{runId.slice(0, 8)}</code>
              {tokenEstimate !== null && <span>约 {Math.round(tokenEstimate)} tokens 上下文</span>}
            </p>
          ) : (
            <p className="ask-panel-context" data-bound="false">
              未绑定审查记录，将按普通对话回答
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
          aria-label="追问内容"
          placeholder={runId ? '例如：这条 critical 为什么只在特定分支触发？' : '例如：Python 里怎么写才不会有 SQL 注入？'}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // 输入法用 Enter 上屏候选词。不拦住的话会把半成品问题发出去。
            if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.keyCode === 229)) {
              event.preventDefault()
            }
          }}
        />
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          追问
        </button>
      </form>

      {busy && (
        <span className="ask-panel-hint" role="status">
          <Spinner /> 正在追问…
        </span>
      )}

      <div className="ask-panel-log" role="log" aria-live="polite" aria-label="追问记录">
        {turns.length === 0 && !busy && (
          <p className="ask-panel-empty">
            还没有追问。回答由模型生成，可能出错 —— 关键结论请回到上面的发现列表核对证据。
          </p>
        )}

        {turns.map((turn) => (
          <article key={turn.id} className="ask-panel-turn" data-error={turn.error ? 'true' : undefined}>
            <div className="ask-panel-question">
              <span className="ask-panel-role" aria-hidden="true">
                问
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
                      前往设置
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void ask(turn.question)}
                  >
                    重试
                  </button>
                </div>
              </div>
            ) : (
              <>
                {/* 上下文被裁剪时，警告条必须在回答**上方** —— 先说明这份回答的局限，再给结论。 */}
                {turn.meta?.truncated && (
                  <Notice kind="warn">
                    {turn.meta.note || '上下文被裁剪后才发给模型，这条回答可能漏掉部分发现。'}
                  </Notice>
                )}
                <pre className="ask-panel-answer">{turn.answer}</pre>
                <div className="ask-panel-meta">
                  <span>由 {turn.model || '当前配置的模型'} 回答</span>
                  {turn.meta?.sections?.length ? (
                    <span>上下文：{turn.meta.sections.join('、')}</span>
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
