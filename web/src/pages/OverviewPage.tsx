import { useEffect, useRef, useState } from 'react'
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { api } from '../api/client'
import type { BenchmarkReport, HistoryResponse, MetaResponse } from '../api/types'
import { Card, CardHead, Chip, Metric, Section } from '../components/ui'
import { DemoPanel } from '../components/DemoPanel'
import { formatDuration, formatNumber, formatPercent, repoLabel } from '../lib/format'

const CAPABILITIES = [
  {
    title: '智能审查规划',
    body: '在调用模型之前先生成确定性的 ReviewPlan：风险等级、风险类别、优先文件、审查策略与是否需要跨文件分析。',
    tag: 'ReviewPlanner',
  },
  {
    title: '规则 + AI 双路分析',
    body: '15 条确定性规则（逐行安全规则 + Python AST 语法级规则）与模型结论合并去重，规则命中带来源标记。',
    tag: 'StaticAnalyzer',
  },
  {
    title: '证据链校验',
    body: '每条结论都校验文件、行号、是否落在变更行、代码片段是否真实存在，标记 valid / needs_review / invalid。',
    tag: 'FindingValidator',
  },
  {
    title: '跨文件接口影响',
    body: '建立符号索引，与 PR base 版本对比签名（参数、返回类型、async、基类），并定位真实外部调用方。',
    tag: 'SymbolIndex',
  },
  {
    title: '语法级上下文',
    body: 'tree-sitter 解析 Python / JavaScript / TypeScript，提取 imports、函数签名、类与继承；未安装时自动降级到正则。',
    tag: 'ContextBuilder',
  },
  {
    title: '可量化的准确率',
    body: '内置已知缺陷样例库，输出精确率、召回率、F1、误报率与行号准确率，用于防止策略退化。',
    tag: 'Benchmark',
  },
]

const TRUST_POINTS = [
  ['01', '先规划', '先生成风险与审查范围，再调用模型。'],
  ['02', '有证据', '文件、行号、Diff 关联逐条校验。'],
  ['03', '可复盘', '结果、成本、反馈全部保存在本机。'],
  ['04', '可演示', '离线 Demo 与 Benchmark 随时可用。'],
]

const PIPELINE = [
  ['01', '获取 PR', '解析 GitHub PR URL，抓取元数据、diff、文件列表与文件内容。'],
  ['02', '智能过滤', '跳过纯删除、超大与不相关文件，支持 force include 白名单。'],
  ['03', '构建上下文', 'tree-sitter 语法树 → 正则提取 → diff 窗口，三级降级保证不崩。'],
  ['04', '生成计划', '按 PR 意图与变更特征计算风险等级、优先文件与审查策略。'],
  ['05', '逐文件审查', '并发调用模型输出结构化 findings，受单次与 24 小时预算双重约束。'],
  ['06', '规则与证据', '合并确定性规则命中，再逐条校验证据是否对应真实变更行。'],
  ['07', '跨文件影响', '对比 base 签名，定位会被破坏的外部调用方。'],
  ['08', '报告与落库', '渲染 terminal / markdown / json / GitHub 评论，并写入 SQLite 支持复盘。'],
]

export function OverviewPage({ onNavigate }: { onNavigate: (page: string) => void }) {
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
            AI PR REVIEW AGENT · 本地工作台
          </div>
          <h1 data-anim="title">
            把 GitHub PR 审查
            <br />
            做成可解释、可复盘的智能工作流
          </h1>
          <p className="lead" style={{ marginTop: 'var(--ds-space-4)' }} data-anim="lead">
            不是一次性的模型调用，而是一条带规划、规则、证据校验与跨文件接口分析的审查流水线。
            所有结论都可追溯到具体的文件与变更行。
          </p>

          <div className="row row-wrap" style={{ marginTop: 'var(--ds-space-5)' }} data-anim="cta">
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('review')}>
              开始一次审查
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => onNavigate('benchmark')}
            >
              查看准确率
            </button>
            <span className="dim mono" style={{ fontSize: 'var(--ds-text-sm)' }}>
              v0.1.0 · MIT · Python 3.12+
            </span>
          </div>
        </div>

        <div className="hero-visual" data-anim="console">
          <div className="hero-console" aria-label="最近一次审查">
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
                      {latest.total_findings ?? 0} 条 · {formatDuration(latest.duration_seconds)}
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
                    <em>还没有审查记录</em>
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

      <div className="trust-strip" data-reveal aria-label="产品工作流承诺">
        <div className="trust-strip-intro">
          <span className="eyebrow">WHY THIS WORKFLOW</span>
          <strong>不是黑盒结论，而是可验证的工程证据。</strong>
        </div>
        <div className="trust-strip-items">
          {TRUST_POINTS.map(([index, title, body]) => (
            <div className="trust-point" key={title}>
              <span className="trust-point-index mono">{index}</span>
              <div>
                <b>{title}</b>
                <p>{body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <DemoPanel />

      <Section eyebrow="SNAPSHOT" title="当前状态" data-reveal>
        {error && (
          <p
            className="muted"
            style={{ marginBottom: 'var(--ds-space-3)', fontSize: 'var(--ds-text-md)' }}
          >
            部分数据未能载入：{error}
          </p>
        )}
        <div className="metrics">
          <Metric
            label="历史审查"
            value={formatNumber(runs)}
            hint={`累计 ${formatNumber(stats.total_runs)} 次运行`}
          />
          <Metric label="覆盖 PR" value={formatNumber(stats.unique_prs)} />
          <Metric label="发现问题" value={formatNumber(stats.total_findings)} />
          <Metric
            label="规则准确率"
            value={benchmark ? formatPercent(benchmark.precision, 0) : '—'}
            hint={benchmark ? `召回率 ${formatPercent(benchmark.recall, 0)}` : '未载入'}
          />
          <Metric
            label="确定性规则"
            value={meta ? meta.rule_count : '—'}
            hint="逐行规则 + AST 规则（去重）"
          />
          <Metric
            label="支持供应商"
            value={meta ? meta.provider_count : '—'}
            hint="OpenAI 兼容 + Anthropic"
          />
        </div>
      </Section>

      <Section data-reveal eyebrow="PIPELINE" title="从 PR 链接到审查报告">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          {PIPELINE.map(([step, title, body]) => (
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
                <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{title}</h3>
              </div>
              <p
                className="muted"
                style={{
                  marginTop: 'var(--ds-space-2)',
                  fontSize: 'var(--ds-text-md)',
                  lineHeight: 1.6,
                }}
              >
                {body}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      <Section data-reveal eyebrow="CAPABILITIES" title="关键能力">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          {CAPABILITIES.map((item) => (
            <Card key={item.title} data-reveal>
              <div
                className="row"
                style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}
              >
                <h3 style={{ fontSize: 'var(--ds-text-base)' }}>{item.title}</h3>
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
                {item.body}
              </p>
            </Card>
          ))}
        </div>
      </Section>

      {benchmark && (
        <Section
          eyebrow="ACCURACY"
          title="基准测试结果"
          description="精选已知缺陷样例集上的实测成绩，用于防止规则退化与误报增加。"
          extra={
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onNavigate('benchmark')}
            >
              查看明细 →
            </button>
          }
        >
          <Card flush >
            <CardHead
              title="combined 策略"
              extra={<Chip accent>{benchmark.case_count} 个样例</Chip>}
            />
            <div className="card-body">
              <div className="metrics">
                <Metric label="精确率" value={formatPercent(benchmark.precision)} small />
                <Metric label="召回率" value={formatPercent(benchmark.recall)} small />
                <Metric label="F1" value={formatPercent(benchmark.f1)} small />
                <Metric
                  label="误报率"
                  value={formatPercent(benchmark.false_positive_rate)}
                  small
                />
                <Metric
                  label="行号准确率"
                  value={formatPercent(benchmark.line_accuracy)}
                  small
                />
              </div>
              <p
                className="dim"
                style={{ marginTop: 'var(--ds-space-4)', fontSize: 'var(--ds-text-sm)' }}
              >
                这是精选回归样例集的成绩，代表规则在该集合上的表现，不等同于真实 PR 上的泛化准确率。
              </p>
            </div>
          </Card>
        </Section>
      )}

      <Section data-reveal eyebrow="CLI" title="同一个引擎，两种用法">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 'var(--ds-space-4)',
          }}
        >
          <Card>
            <h3 style={{ fontSize: 'var(--ds-text-base)' }}>命令行</h3>
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
            <h3 style={{ fontSize: 'var(--ds-text-base)' }}>本地 HTTP 接口</h3>
            <pre className="code" style={{ marginTop: 'var(--ds-space-3)' }}>
              {`POST /api/plan       生成审查计划
POST /api/review     执行完整审查
GET  /api/history    历史与统计
GET  /api/report     按 run_id 取报告
GET  /api/benchmark  准确率报告
POST /api/feedback   记录人工反馈`}
            </pre>
          </Card>
        </div>
      </Section>
    </div>
  )
}


