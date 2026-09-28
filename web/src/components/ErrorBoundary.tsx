import { Component, type ErrorInfo, type ReactNode } from 'react'
import { t } from '../i18n'

interface Props {
  children: ReactNode
  /** 出错时展示的上下文说明，例如"概览页"。 */
  scope?: string
  /** 重试入口：通常是让上层重置状态或重新挂载子树。 */
  onRetry?: () => void
}

interface State {
  error: Error | null
}

/**
 * 错误边界。
 *
 * 之前任何组件抛异常都会让整个应用白屏，而历史 / 准确率 / 接口三页都是
 * 裸 `useEffect` 请求，一旦接口异常就直接崩掉整站。这里把故障限制在单个
 * 视图内，并给出可操作的重试入口。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 本地工具没有远端上报，打印到控制台便于排查
    console.error(t('error.console'), error, info.componentStack)
  }

  private reset = (): void => {
    this.setState({ error: null })
    this.props.onRetry?.()
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    const scope = this.props.scope ? `「${this.props.scope}」` : t('error.view')
    return (
      <div className="notice notice-error" role="alert" style={{ flexDirection: 'column', gap: 12 }}>
        <div className="row" style={{ gap: 10 }}>
          <span className="notice-icon">!</span>
          <strong>{t('error.title', { scope })}</strong>
        </div>
        <p style={{ fontSize: 'var(--ds-text-md)', lineHeight: 1.65 }}>
          {error.message || t('error.unknown')}
        </p>
        <div className="row" style={{ gap: 10 }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={this.reset}>
            {t('error.retry')}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => window.location.reload()}
          >
            {t('error.reload')}
          </button>
        </div>
        <details style={{ width: '100%' }}>
          <summary style={{ cursor: 'pointer', fontSize: 'var(--ds-text-sm)' }}>
            {t('error.stack')}
          </summary>
          <pre className="code" style={{ marginTop: 8, maxHeight: 220 }}>
            {error.stack || String(error)}
          </pre>
        </details>
      </div>
    )
  }
}
