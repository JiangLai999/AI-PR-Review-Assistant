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
import { setLang, useT } from './i18n'

gsap.registerPlugin(useGSAP)

type PageId = 'overview' | 'review' | 'history' | 'benchmark' | 'api' | 'settings'

/** 导航标签存 i18n key（模块级常量不能调 t()，渲染时再取词）。 */
const NAV: { id: PageId; labelKey: string; icon: string }[] = [
  { id: 'overview', labelKey: 'nav.overview', icon: '⌂' },
  { id: 'review', labelKey: 'nav.review', icon: '↗' },
  { id: 'history', labelKey: 'nav.history', icon: '◷' },
  { id: 'benchmark', labelKey: 'nav.benchmark', icon: '⌁' },
  { id: 'api', labelKey: 'nav.api', icon: '{}' },
  { id: 'settings', labelKey: 'nav.settings', icon: '⚙' },
]

const PAGE_FROM_HASH = (hash: string): PageId => {
  const id = hash.replace(/^#\/?/, '') as PageId
  return NAV.some((item) => item.id === id) ? id : 'overview'
}

export function App() {
  const t = useT()
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
      // 语言来自后端配置（Phase 2 起设置页可改）：先取一次，页面才不会中英混排。
      try {
        const config = await api.config()
        if (alive) setLang(config.preferences?.ui_language)
      } catch {
        // 读不到配置就保持默认中文，不挡首屏
      }
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
      <aside className="workspace-sidebar" aria-label={t('app.sidebar.aria')}>
        <button type="button" className="sidebar-brand" onClick={() => navigate('overview')}>
          <span className="brand-mark brand-mark-image">
            <img src="/static/assets/site-icon.png" alt="AI PR Review Assistant" />
          </span>
          <span className="sidebar-brand-text"><strong>{t('app.brand')}</strong><small>{t('app.brand.sub')}</small></span>
        </button>
        <div className="sidebar-section-label">{t('app.sidebar.workspace')}</div>
        <nav className="sidebar-nav" aria-label={t('app.sidebar.ariaNav')}>
          {NAV.map((item) => (
            <button key={item.id} type="button" className="sidebar-nav-item" aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}>
              <span className="sidebar-icon">{item.icon}</span><span>{t(item.labelKey)}</span>{item.id === 'review' && runId && <i className="sidebar-live-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-context"><span className="status-pulse" />{t('app.sidebar.local')}</div>
          <div className="sidebar-meta">{t('app.sidebar.meta')}<br />MIT License · v0.1.0</div>
        </div>
      </aside>
      <div className="workspace-content">
      <header className="workspace-statusbar">
        <div className="statusbar-left">
          <span className="statusbar-kicker">{t('app.statusbar.kicker')}</span>
          <span className="statusbar-title">{page === 'review' ? t('app.statusbar.reviewSession') : t(NAV.find((item) => item.id === page)?.labelKey ?? 'nav.overview')}</span>
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
            <span className="statusbar-model-dot" /> {credentials ? t('app.statusbar.runtime') : t('app.statusbar.localRuntime')}
          </span>
          <span className={cx('statusbar-health', online === false ? 'is-offline' : online ? 'is-online' : '')}>
            {online === null ? t('app.statusbar.checking') : online ? t('app.statusbar.connected') : t('app.statusbar.offline')}
          </span>
        </div>
      </header>

      {online === false && (
        <div className="service-outage" role="alert">
          <div>
            <strong>{t('app.outage.title')}</strong>
            <span>{t('app.outage.body', { command: 'pr-review serve' })}</span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={() => void refreshService()}>
            {t('app.outage.retry')}
          </button>
        </div>
      )}

      <main className="main">
        <div className="container">
          {/* 每个视图单独兜底：某一页抛异常不应让整个工作台白屏 */}
          <ErrorBoundary key={page} scope={t(NAV.find((item) => item.id === page)?.labelKey ?? 'nav.overview')}>
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
            {t('app.footer.note')}
          </span>
          <span className="row" style={{ gap: 'var(--ds-space-4)' }}>
            <a
              href="https://github.com/JiangLai999/AI-PR-Review-Assistant"
              target="_blank"
              rel="noreferrer noopener"
              style={{ fontSize: 'var(--ds-text-sm)' }}
            >
              {t('app.footer.github')}
            </a>
            <a
              href="https://jianglai999.github.io/AI-PR-Review-Assistant-web/"
              target="_blank"
              rel="noreferrer noopener"
              style={{ fontSize: 'var(--ds-text-sm)' }}
            >
              {t('app.footer.website')}
            </a>
          </span>
        </div>
      </footer>
      </div>
    </div>
  )
}
