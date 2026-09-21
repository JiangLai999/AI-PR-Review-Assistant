import { useCallback, useEffect, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { api } from './api/client'
import type { CredentialReport, ReviewResponse } from './api/types'
import { ErrorBoundary } from './components/ErrorBoundary'
import { cx } from './components/ui'
import { ParticleBackground } from './components/ParticleBackground'
import { ApiPage } from './pages/ApiPage'
import { BenchmarkPage } from './pages/BenchmarkPage'
import { HistoryPage } from './pages/HistoryPage'
import { OverviewPage } from './pages/OverviewPage'
import { ReviewPage } from './pages/ReviewPage'
import { SettingsPage } from './pages/SettingsPage'

gsap.registerPlugin(useGSAP)

type PageId = 'overview' | 'review' | 'history' | 'benchmark' | 'api' | 'settings'

const NAV: { id: PageId; label: string; icon: string }[] = [
  { id: 'overview', label: '概览', icon: '⌂' },
  { id: 'review', label: '审查工作台', icon: '↗' },
  { id: 'history', label: '历史审查', icon: '◷' },
  { id: 'benchmark', label: '准确率', icon: '⌁' },
  { id: 'api', label: '接口', icon: '{}' },
  { id: 'settings', label: '设置', icon: '⚙' },
]

const PAGE_FROM_HASH = (hash: string): PageId => {
  const id = hash.replace(/^#\/?/, '') as PageId
  return NAV.some((item) => item.id === id) ? id : 'overview'
}

export function App() {
  const [page, setPage] = useState<PageId>(() => PAGE_FROM_HASH(window.location.hash))
  const [result, setResult] = useState<ReviewResponse | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [credentials, setCredentials] = useState<CredentialReport | null>(null)
  const appRef = useRef<HTMLDivElement>(null)

  useGSAP(
    () => {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      if (reduceMotion) return
      // 只做位移，不碰 opacity/visibility。
      // 使用 autoAlpha 时，若补间被后续渲染打断，元素会永久停留在
      // visibility:hidden —— 这曾让审查页的标题与表单整片消失。
      gsap.fromTo('.topbar', { y: -18 }, { y: 0, duration: 0.7, ease: 'power3.out' })
      gsap.fromTo(
        '.main > .container',
        { y: 10 },
        { y: 0, duration: 0.65, delay: 0.12, ease: 'power2.out' },
      )
    },
    { scope: appRef },
  )

  // 保留审查结果，使页面切换不丢失当前上下文。
  const navigate = useCallback((next: string) => {
    const id = PAGE_FROM_HASH(`#/${next}`)
    setPage(id)
    window.location.hash = `#/${id}`
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    const onHashChange = () => setPage(PAGE_FROM_HASH(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const refreshService = useCallback(async () => {
    setOnline(null)
    try {
      await api.health()
      setOnline(true)
    } catch {
      setOnline(false)
    }
  }, [])

  const refreshCredentials = useCallback(async () => {
    try {
      setCredentials(await api.credentials(true))
    } catch {
      setCredentials(null)
    }
  }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        await api.health()
        if (alive) setOnline(true)
      } catch {
        if (alive) setOnline(false)
      }
      if (alive) await refreshCredentials()
    })()
    return () => {
      alive = false
    }
  }, [refreshCredentials])

  const handleResult = useCallback((next: ReviewResponse | null, id: string | null) => {
    setResult(next)
    setRunId(id)
  }, [])

  return (
    <div ref={appRef} className="shell workspace-shell">
      <ParticleBackground mode={page === 'review' ? 'focus' : 'idle'} />
      <aside className="workspace-sidebar" aria-label="工作区导航">
        <button type="button" className="sidebar-brand" onClick={() => navigate('overview')}>
          <span className="brand-mark brand-mark-image">
            <img src="/static/assets/site-icon.png" alt="AI PR Review Assistant" />
          </span>
          <span className="sidebar-brand-text"><strong>PR智审</strong><small>AI PR REVIEW</small></span>
        </button>
        <div className="sidebar-section-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="工作区">
          {NAV.map((item) => (
            <button key={item.id} type="button" className="sidebar-nav-item" aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}>
              <span className="sidebar-icon">{item.icon}</span><span>{item.label}</span>{item.id === 'review' && runId && <i className="sidebar-live-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-context"><span className="status-pulse" />LOCAL WORKSPACE</div>
          <div className="sidebar-meta">数据保存在本机<br />MIT License · v0.1.0</div>
        </div>
      </aside>
      <div className="workspace-content">
      <header className="workspace-statusbar">
        <div className="statusbar-left">
          <span className="statusbar-kicker">CURRENT WORKSPACE</span>
          <span className="statusbar-title">{page === 'review' ? 'Review session' : NAV.find((item) => item.id === page)?.label}</span>
        </div>
        <div className="statusbar-right">
          {/* 凭证健康沿用状态栏：任一异常都要在尝试之前就看得见，而不是填完表单才报错 */}
          {(credentials?.items ?? []).map((item) => (
            <button
              key={item.key}
              type="button"
              className={cx(
                'statusbar-health',
                item.ok ? 'is-online' : item.configured ? 'is-offline' : 'is-warn',
              )}
              title={`${item.label}：${item.detail}${item.fix_hint ? ` — ${item.fix_hint}` : ''}`}
              onClick={() => navigate('settings')}
            >
              {item.label} {item.ok ? '✓' : item.configured ? '✗' : '—'}
            </button>
          ))}
          <span className="statusbar-model">
            <span className="statusbar-model-dot" /> {credentials ? 'AI runtime' : 'Local AI runtime'}
          </span>
          <span className={cx('statusbar-health', online === false ? 'is-offline' : online ? 'is-online' : '')}>
            {online === null ? '检测中' : online ? 'Connected' : 'Offline'}
          </span>
        </div>
      </header>

      {online === false && (
        <div className="service-outage" role="alert">
          <div>
            <strong>本地服务未连接</strong>
            <span>请运行 <code>pr-review serve</code> 后重试，当前仍可浏览离线页面。</span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={() => void refreshService()}>
            重新连接
          </button>
        </div>
      )}

      <main className="main">
        <div className="container">
          {/* 每个视图单独兜底：某一页抛异常不应让整个工作台白屏 */}
          <ErrorBoundary key={page} scope={NAV.find((item) => item.id === page)?.label}>
            {page === 'overview' && <OverviewPage onNavigate={navigate} />}
            {page === 'review' && <ReviewPage initialResult={result} onResult={handleResult} />}
            {page === 'history' && <HistoryPage onNavigate={navigate} />}
            {page === 'benchmark' && <BenchmarkPage />}
            {page === 'api' && <ApiPage />}
            {page === 'settings' && <SettingsPage onSaved={refreshCredentials} />}
          </ErrorBoundary>
        </div>
      </main>

      <footer
        style={{
          borderTop: '1px solid var(--ds-color-border-subtle)',
          padding: 'var(--ds-space-5) 0',
          marginTop: 'auto',
        }}
      >
        <div
          className="container row row-wrap"
          style={{ justifyContent: 'space-between', gap: 'var(--ds-space-3)' }}
        >
          <span className="dim" style={{ fontSize: 'var(--ds-text-sm)' }}>
            AI PR Review Assistant · MIT License · 本地运行，数据不出本机
          </span>
          <span className="row" style={{ gap: 'var(--ds-space-4)' }}>
            <a
              href="https://github.com/JiangLai999/AI-PR-Review-Assistant"
              target="_blank"
              rel="noreferrer noopener"
              style={{ fontSize: 'var(--ds-text-sm)' }}
            >
              GitHub ↗
            </a>
            <a
              href="https://jianglai999.github.io/AI-PR-Review-Assistant-web/"
              target="_blank"
              rel="noreferrer noopener"
              style={{ fontSize: 'var(--ds-text-sm)' }}
            >
              项目官网 ↗
            </a>
          </span>
        </div>
      </footer>
      </div>
    </div>
  )
}
