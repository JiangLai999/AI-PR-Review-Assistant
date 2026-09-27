import { useEffect, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { api } from '../api/client'
import type { BenchmarkReport, HistoryResponse, MetaResponse } from '../api/types'
import { Card, CardHead, Chip, Metric, Section } from '../components/ui'
import { DemoPanel } from '../components/DemoPanel'
import { tn, useT } from '../i18n'
import { formatDuration, formatNumber, formatPercent, repoLabel } from '../lib/format'

/** 卡片文案只存 key，渲染时用 t() 取词（语言切换即时生效）。tag 是代码标识，保持不变。 */
const CAPABILITIES = [
  { titleKey: 'overview.capabilities.1.title', bodyKey: 'overview.capabilities.1.body', tag: 'ReviewPlanner' },
  { titleKey: 'overview.capabilities.2.title', bodyKey: 'overview.capabilities.2.body', tag: 'StaticAnalyzer' },
  { titleKey: 'overview.capabilities.3.title', bodyKey: 'overview.capabilities.3.body', tag: 'FindingValidator' },
  { titleKey: 'overview.capabilities.4.title', bodyKey: 'overview.capabilities.4.body', tag: 'SymbolIndex' },
  { titleKey: 'overview.capabilities.5.title', bodyKey: 'overview.capabilities.5.body', tag: 'ContextBuilder' },
  { titleKey: 'overview.capabilities.6.title', bodyKey: 'overview.capabilities.6.body', tag: 'Benchmark' },
]

const TRUST_POINTS = [
  ['01', 'overview.trust.p1.title', 'overview.trust.p1.body'],
  ['02', 'overview.trust.p2.title', 'overview.trust.p2.body'],
  ['03', 'overview.trust.p3.title', 'overview.trust.p3.body'],
  ['04', 'overview.trust.p4.title', 'overview.trust.p4.body'],
]

const PIPELINE = [
  ['01', 'overview.pipeline.1.title', 'overview.pipeline.1.body'],
  ['02', 'overview.pipeline.2.title', 'overview.pipeline.2.body'],
  ['03', 'overview.pipeline.3.title', 'overview.pipeline.3.body'],
  ['04', 'overview.pipeline.4.title', 'overview.pipeline.4.body'],
  ['05', 'overview.pipeline.5.title', 'overview.pipeline.5.body'],
  ['06', 'overview.pipeline.6.title', 'overview.pipeline.6.body'],
  ['07', 'overview.pipeline.7.title', 'overview.pipeline.7.body'],
  ['08', 'overview.pipeline.8.title', 'overview.pipeline.8.body'],
]

export function OverviewPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const t = useT()
  const pageRef = useRef<HTMLDivElement>(null)
  useGSAP(
    () => {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      if (reduceMotion) return
      // 只用位移做入场，绝不使用 autoAlpha/opacity 初始态：
      // 一旦补间被打断，元素会永久停留在不可见状态（曾导致审查页整屏空白）。
      const q = gsap.utils.selector(pageRef)
      const timeline = gsap.timeline({ defaults: { ease: 'power3.out' } })
      timeline
        .from(q('[data-anim="eyebrow"]'), { y: 14, duration: 0.45 })
        .from(q('[data-anim="title"]'), { y: 24, duration: 0.7 }, '-=0.2')
        .from(q('[data-anim="lead"]'), { y: 16, duration: 0.55 }, '-=0.35')
        .from(q('[data-anim="cta"]'), { y: 12, duration: 0.45 }, '-=0.3')
        .from(q('[data-anim="console"]'), { x: 28, rotation: 5, duration: 0.8 }, '-=0.65')
      gsap.from(q('[data-reveal]'), { y: 20, duration: 0.55, stagger: 0.06, delay: 0.35, ease: 'power2.out' })
    },
    { scope: pageRef },
  )
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null)
  const [meta, setMeta] = useState<MetaResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [h, b, m] = await Promise.all([
          api.history(30),
          api.benchmark('combined'),
          api.meta(),
        ])
        if (!alive) return
        setHistory(h)
        if (b && typeof b === 'object' && 'precision' in b) setBenchmark(b as BenchmarkReport)
        setMeta(m)
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const stats = history?.statistics ?? {}
  const runs = history?.runs?.length ?? 0
  const latest = history?.runs?.[0] ?? null

  return (
    <div ref={pageRef} className="overview-page">
      <div className="overview-hero">
        <div className="hero-copy">
          <div className="eyebrow" data-anim="eyebrow">
            {t('overview.hero.eyebrow')}
          </div>
          <h1 data-anim="title">
            {t('overview.hero.titleLine1')}
            <br />
            {t('overview.hero.titleLine2')}
          </h1>
          <p className="lead" style={{ marginTop: 'var(--ds-space-4)' }} data-anim="lead">
            {t('overview.hero.lead')}
          </p>

          <div className="row row-wrap" style={{ marginTop: 'var(--ds-space-5)' }} data-anim="cta">
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('review')}>
              {t('overview.hero.ctaReview')}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => onNavigate('benchmark')}
            >
              {t('overview.hero.ctaBenchmark')}
            </button>
            <span className="dim mono" style={{ fontSize: 'var(--ds-text-sm)' }}>
              v0.1.0 · MIT · Python 3.12+
            </span>
          </div>
        </div>

        <div className="hero-visual" data-anim="console">
          <div className="hero-console" aria-label={t('overview.hero.consoleAria')}>
            <div className="hero-console-top">
              <span className="console-dot" />
              <span className="console-dot" />
              <span className="console-dot" />
              <span className="mono console-label">last.run</span>
              <span className="console-status">{latest ? 'RECORDED' : 'NO DATA'}</span>
            </div>
            <div className="hero-console-body">
              {latest ? (
                <>
                  <div className="console-line dim">
                    <span>01</span>
                    <b>pr</b>
                    <em>{repoLabel(latest)}</em>
                    <strong>done</strong>
                  </div>
                  <div className="console-line dim">
                    <span>02</span>
                    <b>model</b>
                    <em>{latest.model || '—'}</em>
                    <strong>done</strong>
                  </div>
                  <div className="console-line dim">
                    <span>03</span>
                    <b>findings</b>
                    <em>
                      {tn('overview.hero.console.findings', latest.total_findings ?? 0, {
                        duration: formatDuration(latest.duration_seconds),
                      })}
                    </em>
                    <strong className="accent">saved</strong>
                  </div>
                  <div className="console-caret">
                    $ <span>pr-review history</span>
                    <i />
                  </div>
                </>
              ) : (
                <>
                  <div className="console-line dim">
                    <span>--</span>
                    <b>empty</b>
                    <em>{t('overview.hero.console.empty')}</em>
                    <strong>idle</strong>
                  </div>
                  <div className="console-caret">
                    $ <span>pr-review plan &lt;url&gt;</span>
                    <i />
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="trust-strip" data-reveal aria-label={t('overview.trust.aria')}>
        <div className="trust-strip-intro">
          <span className="eyebrow">WHY THIS WORKFLOW</span>
          <strong>{t('overview.trust.title')}</strong>
        </div>
        <div className="trust-strip-items">
          {TRUST_POINTS.map(([index, titleKey, bodyKey]) => (
            <div className="trust-point" key={index}>
              <span className="trust-point-index mono">{index}</span>
              <div>
                <b>{t(titleKey)}</b>
                <p>{t(bodyKey)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <DemoPanel />

      <Section eyebrow="SNAPSHOT" title={t('overview.snapshot.title')} data-reveal>
        {error && (
          <p
            className="muted"
            style={{ marginBottom: 'var(--ds-space-3)', fontSize: 'var(--ds-text-md)' }}
          >
            {t('overview.snapshot.error', { detail: error })}
          </p>
        )}
        <div className="metrics">
          <Metric
            label={t('overview.snapshot.runs')}
            value={formatNumber(runs)}
            hint={t('overview.snapshot.runsHint', { count: formatNumber(stats.total_runs) })}
          />
          <Metric label={t('overview.snapshot.prs')} value={formatNumber(stats.unique_prs)} />
          <Metric
            label={t('overview.snapshot.findings')}
            value={formatNumber(stats.total_findings)}
          />
          <Metric
            label={t('overview.snapshot.precision')}
            value={benchmark ? formatPercent(benchmark.precision, 0) : '—'}
            hint={
              benchmark
                ? t('overview.snapshot.precisionHint', {
                    recall: formatPercent(benchmark.recall, 0),
                  })
                : t('overview.snapshot.notLoaded')
            }
          />
          <Metric
            label={t('overview.snapshot.rules')}
            value={meta ? meta.rule_count : '—'}
            hint={t('overview.snapshot.rulesHint')}
          />
          <Metric
            label={t('overview.snapshot.providers')}
            value={meta ? meta.provider_count : '—'}
            hint={t('overview.snapshot.providersHint')}
          />
        </div>
      </Section>

      <Section data-reveal eyebrow="PIPELINE" title={t('overview.pipeline.title')}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          {PIPELINE.map(([step, titleKey, bodyKey]) => (
            <Card key={step} data-reveal>
              <div className="row" style={{ gap: 'var(--ds-space-3)', alignItems: 'baseline' }}>
                <span
                  className="mono"
                  style={{
                    fontSize: 'var(--ds-text-xl)',
                    fontWeight: 600,
                    color: 'var(--ds-color-border-strong)',
                    letterSpacing: '-0.02em',
                  }}
                >
                  {step}
                </span>
                <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{t(titleKey)}</h3>
              </div>
              <p
                className="muted"
                style={{
                  marginTop: 'var(--ds-space-2)',
                  fontSize: 'var(--ds-text-md)',
                  lineHeight: 1.6,
                }}
              >
                {t(bodyKey)}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      <Section data-reveal eyebrow="CAPABILITIES" title={t('overview.capabilities.title')}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          {CAPABILITIES.map((item) => (
            <Card key={item.tag} data-reveal>
              <div
                className="row"
                style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}
              >
                <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{t(item.titleKey)}</h3>
                <Chip>{item.tag}</Chip>
              </div>
              <p
                className="muted"
                style={{
                  marginTop: 'var(--ds-space-3)',
                  fontSize: 'var(--ds-text-md)',
                  lineHeight: 1.65,
                }}
              >
                {t(item.bodyKey)}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      {benchmark && (
        <Section
          eyebrow="ACCURACY"
          title={t('overview.accuracy.title')}
          description={t('overview.accuracy.description')}
          extra={
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onNavigate('benchmark')}
            >
              {t('overview.accuracy.detail')}
            </button>
          }
        >
          <Card flush >
            <CardHead
              title={t('overview.accuracy.strategy', { strategy: 'combined' })}
              extra={<Chip accent>{tn('overview.accuracy.cases', benchmark.case_count)}</Chip>}
            />
            <div className="card-body">
              <div className="metrics">
                <Metric
                  label={t('benchmark.metric.precision')}
                  value={formatPercent(benchmark.precision)}
                  small
                />
                <Metric
                  label={t('benchmark.metric.recall')}
                  value={formatPercent(benchmark.recall)}
                  small
                />
                <Metric
                  label={t('benchmark.metric.f1')}
                  value={formatPercent(benchmark.f1)}
                  small
                />
                <Metric
                  label={t('benchmark.metric.fpr')}
                  value={formatPercent(benchmark.false_positive_rate)}
                  small
                />
                <Metric
                  label={t('benchmark.metric.lineAccuracy')}
                  value={formatPercent(benchmark.line_accuracy)}
                  small
                />
              </div>
              <p
                className="dim"
                style={{ marginTop: 'var(--ds-space-4)', fontSize: 'var(--ds-text-sm)' }}
              >
                {t('overview.accuracy.note')}
              </p>
            </div>
          </Card>
        </Section>
      )}

      <Section data-reveal eyebrow="CLI" title={t('overview.cli.title')}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          <Card>
            <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{t('overview.cli.terminal')}</h3>
            <pre className="code" style={{ marginTop: 'var(--ds-space-3)' }}>
              {`pr-review <PR_URL>
pr-review plan <PR_URL>
pr-review benchmark --strategy all
pr-review history
pr-review stats
pr-review serve`}
            </pre>
          </Card>
          <Card>
            <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{t('overview.cli.http')}</h3>
            <pre className="code" style={{ marginTop: 'var(--ds-space-3)' }}>
              {t('overview.cli.endpoints')}
            </pre>
          </Card>
        </div>
      </Section>
    </div>
  )
}


