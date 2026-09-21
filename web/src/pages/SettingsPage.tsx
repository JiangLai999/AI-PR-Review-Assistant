import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { ConfigView, CredentialReport, CredentialItem } from '../api/types'
import { Card, CardHead, Chip, Notice, Section, Spinner } from '../components/ui'

const API_FORMATS = ['openai', 'anthropic'] as const

const NUMERIC_FIELDS: { key: string; label: string; hint: string; step?: number }[] = [
  { key: 'max_tokens', label: '单次最大输出 tokens', hint: '影响单次模型回复长度' },
  { key: 'timeout_seconds', label: '请求超时（秒）', hint: '模型响应慢就调大' },
  { key: 'review_concurrency', label: '并发审查文件数', hint: '越大越快，但更容易触发限流' },
  { key: 'cross_file_max_files', label: '跨文件分析文件数上限', hint: '参与接口影响对比的文件数量' },
  { key: 'max_cost_per_run', label: '单次运行成本上限（$）', hint: '超过则中止本次审查', step: 0.1 },
  { key: 'max_cost_per_24h', label: '24 小时成本上限（$）', hint: '滑动窗口总量', step: 0.5 },
]

const BOOL_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: 'enable_static_analysis', label: '启用静态与 AST 规则', hint: '规则命中不消耗模型调用' },
  {
    key: 'enable_cross_file_review',
    label: '启用跨文件 AI 审查',
    hint: '会额外消耗一次模型调用；关闭时仅做确定性的接口影响分析',
  },
]

function StatusPill({ item }: { item: CredentialItem }) {
  return (
    <span className={`badge ${item.ok ? 'st-valid' : item.configured ? 'st-invalid' : 'st-needs_review'}`}>
      <i className="badge-dot" />
      {item.ok ? '正常' : item.configured ? '异常' : '未配置'}
    </span>
  )
}

export function SettingsPage({ onSaved }: { onSaved?: () => void }) {
  const [config, setConfig] = useState<ConfigView | null>(null)
  const [report, setReport] = useState<CredentialReport | null>(null)
  const [probing, setProbing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error' | 'info'; text: string } | null>(null)

  const [providerName, setProviderName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiFormat, setApiFormat] = useState<string>('openai')
  const [apiKey, setApiKey] = useState('')
  const [githubToken, setGithubToken] = useState('')
  const [numbers, setNumbers] = useState<Record<string, number>>({})
  const [flags, setFlags] = useState<Record<string, boolean>>({})

  const hydrate = useCallback((view: ConfigView) => {
    setConfig(view)
    setProviderName(view.provider_name)
    setBaseUrl(view.base_url)
    setModel(view.model)
    setApiFormat(view.api_format)
    setApiKey('')
    setGithubToken('')
    const nums: Record<string, number> = {}
    const bools: Record<string, boolean> = {}
    for (const field of NUMERIC_FIELDS) {
      const value = view.settings[field.key]
      nums[field.key] = typeof value === 'number' ? value : Number(value ?? 0)
    }
    for (const field of BOOL_FIELDS) {
      bools[field.key] = Boolean(view.settings[field.key])
    }
    setNumbers(nums)
    setFlags(bools)
  }, [])

  const load = useCallback(async () => {
    try {
      const view = await api.config()
      hydrate(view)
    } catch (e) {
      setMessage({ kind: 'error', text: `读取配置失败：${e instanceof Error ? e.message : e}` })
    }
  }, [hydrate])

  useEffect(() => {
    void load()
  }, [load])

  async function probe() {
    setProbing(true)
    setMessage(null)
    try {
      setReport(await api.credentials(true))
    } catch (e) {
      setMessage({ kind: 'error', text: `探测失败：${e instanceof Error ? e.message : e}` })
    } finally {
      setProbing(false)
    }
  }

  // 配置就绪后自动探测一次：打开设置页就该看到真实状态，
  // 而不是先显示"还没有探测结果"等用户手点。
  const autoProbed = useRef(false)
  useEffect(() => {
    if (!config || autoProbed.current) return
    autoProbed.current = true
    void probe()
    // probe 每次渲染都是新引用，这里只关心 config 首次就绪
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config])


  async function save(validate: boolean) {
    setSaving(true)
    setMessage(null)
    try {
      const payload: Record<string, unknown> = {
        provider_name: providerName,
        base_url: baseUrl,
        model,
        api_format: apiFormat,
        persist_secrets: true,
        validate,
        ...numbers,
        ...flags,
      }
      if (apiKey.trim()) payload.api_key = apiKey.trim()
      if (githubToken.trim()) payload.github_token = githubToken.trim()

      const result = await api.saveConfig(payload)
      hydrate(result.config)
      setMessage({ kind: 'ok', text: result.message })
      await probe()
      onSaved?.()
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e)
      setMessage({ kind: 'error', text })
      await probe()
    } finally {
      setSaving(false)
    }
  }

  const presetHint = useMemo(() => {
    if (!config) return ''
    const preset = config.available_providers.find((p) => p.name === providerName)
    return preset ? preset.base_url : ''
  }, [config, providerName])

  if (!config) {
    return (
      <Card>
        <div className="card-body stack">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton" style={{ height: 48 }} />
          ))}
        </div>
      </Card>
    )
  }

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">SETTINGS</div>
        <h1>设置</h1>
        <p className="lead">
          在这里配置模型供应商与凭证。所有内容只写入本机配置文件，不会上传到任何地方。
          密钥字段留空表示<b>保持原值不变</b>。
        </p>
      </div>

      {message && (
        <div style={{ marginBottom: 'var(--ds-space-4)' }}>
          <Notice kind={message.kind === 'ok' ? 'success' : message.kind === 'info' ? 'info' : 'error'}>
            {message.text}
          </Notice>
        </div>
      )}

      <Section
        eyebrow="CREDENTIALS"
        title="凭证健康"
        description="点「重新探测」会真实请求 GitHub 与模型端点，用来区分「没填」和「填错」。"
        extra={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void probe()} disabled={probing}>
            {probing ? <Spinner /> : null}
            重新探测
          </button>
        }
      >
        <Card flush>
          <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
            {(report?.items ?? []).length === 0 && (
              <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                还没有探测结果。点击右上角「重新探测」开始检查。
              </p>
            )}
            {report?.items.map((item) => (
              <div
                key={item.key}
                style={{
                  border: '1px solid var(--ds-color-border-subtle)',
                  borderRadius: 'var(--ds-radius-media)',
                  padding: 'var(--ds-space-4)',
                  background: item.ok ? 'transparent' : 'var(--ds-sev-critical-bg)',
                }}
              >
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <strong style={{ fontSize: 'var(--ds-text-md)' }}>{item.label}</strong>
                  <StatusPill item={item} />
                </div>
                <p className="muted" style={{ marginTop: 6, fontSize: 'var(--ds-text-md)', lineHeight: 1.6 }}>
                  {item.detail}
                </p>
                {!item.ok && item.fix_hint && (
                  <p style={{ marginTop: 6, fontSize: 'var(--ds-text-sm)', color: 'var(--ds-sev-medium)' }}>
                    修复建议：{item.fix_hint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
      </Section>

      <Section eyebrow="PROVIDER" title="模型供应商">
        <Card flush>
          <CardHead
            title="连接方式"
            extra={<Chip>{config.config_path.split(/[\\/]/).pop()}</Chip>}
          />
          <div className="card-body stack">
            <div className="field">
              <label className="label" htmlFor="provider">
                供应商预设
              </label>
              <select
                id="provider"
                className="select"
                value={providerName}
                onChange={(e) => {
                  const name = e.target.value
                  setProviderName(name)
                  const preset = config.available_providers.find((p) => p.name === name)
                  if (preset) {
                    if (preset.base_url) setBaseUrl(preset.base_url)
                    if (preset.api_format) setApiFormat(preset.api_format)
                    if (preset.default_model && !model) setModel(preset.default_model)
                  }
                }}
              >
                <option value="custom">custom（自定义端点）</option>
                {config.available_providers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.display_name}（{p.name}）
                  </option>
                ))}
              </select>
              {presetHint && (
                <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                  该预设默认端点：{presetHint}
                </span>
              )}
            </div>

            <div className="field">
              <label className="label" htmlFor="base-url">
                Base URL（OpenAI 兼容端点，通常以 /v1 结尾）
              </label>
              <input
                id="base-url"
                className="input"
                value={baseUrl}
                spellCheck={false}
                placeholder="https://api.deepseek.com/v1"
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>

            <div className="row row-wrap" style={{ gap: 'var(--ds-space-4)' }}>
              <div className="field" style={{ flex: '1 1 260px' }}>
                <label className="label" htmlFor="model">
                  模型名
                </label>
                <input
                  id="model"
                  className="input"
                  value={model}
                  spellCheck={false}
                  placeholder="deepseek-flash"
                  onChange={(e) => setModel(e.target.value)}
                />
              </div>
              <div className="field" style={{ flex: '0 0 180px' }}>
                <label className="label" htmlFor="api-format">
                  API 格式
                </label>
                <select
                  id="api-format"
                  className="select"
                  value={apiFormat}
                  onChange={(e) => setApiFormat(e.target.value)}
                >
                  {API_FORMATS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field">
              <label className="label" htmlFor="api-key">
                模型 API Key
                {config.api_key_set && (
                  <span className="dim"> — 当前已配置（{config.api_key_masked}），留空则不改动</span>
                )}
              </label>
              <input
                id="api-key"
                className="input"
                type="password"
                value={apiKey}
                spellCheck={false}
                autoComplete="off"
                placeholder={config.api_key_set ? '留空表示保持现有密钥' : 'sk-…'}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="gh-token">
                GitHub Token
                {config.github_token_set && (
                  <span className="dim">
                    {' '}
                    — 当前已配置（{config.github_token_masked}），留空则不改动
                  </span>
                )}
              </label>
              <input
                id="gh-token"
                className="input"
                type="password"
                value={githubToken}
                spellCheck={false}
                autoComplete="off"
                placeholder={config.github_token_set ? '留空表示保持现有 Token' : 'ghp_…'}
                onChange={(e) => setGithubToken(e.target.value)}
              />
              <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                只需 repo 权限；用于读取 PR 元数据与 diff。
              </span>
            </div>
          </div>
        </Card>
      </Section>

      <Section eyebrow="BEHAVIOUR" title="执行与成本">
        <Card flush>
          <div className="card-body stack">
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 'var(--ds-space-4)',
              }}
            >
              {NUMERIC_FIELDS.map((field) => (
                <div className="field" key={field.key}>
                  <label className="label" htmlFor={field.key}>
                    {field.label}
                  </label>
                  <input
                    id={field.key}
                    className="input"
                    type="number"
                    step={field.step ?? 1}
                    value={numbers[field.key] ?? 0}
                    onChange={(e) =>
                      setNumbers((prev) => ({ ...prev, [field.key]: Number(e.target.value) }))
                    }
                  />
                  <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                    {field.hint}
                  </span>
                </div>
              ))}
            </div>

            <hr className="divider" style={{ margin: 0 }} />

            <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
              {BOOL_FIELDS.map((field) => (
                <label
                  key={field.key}
                  className="row"
                  style={{ gap: 'var(--ds-space-3)', alignItems: 'center', cursor: 'pointer' }}
                >
                  <input
                    type="checkbox"
                    className="checkbox-field"
                    checked={flags[field.key] ?? false}
                    onChange={(e) =>
                      setFlags((prev) => ({ ...prev, [field.key]: e.target.checked }))
                    }
                  />
                  <span>
                    <span style={{ fontSize: 'var(--ds-text-md)' }}>{field.label}</span>
                    <br />
                    <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                      {field.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </Card>
      </Section>

      <Section eyebrow="SAVE" title="保存">
        <Card>
          <div className="stack">
            <p className="muted" style={{ fontSize: 'var(--ds-text-md)', lineHeight: 1.65 }}>
              保存会把密钥以明文写入上方的配置文件（这是本机工具，不做额外加密）。
              「校验后保存」会先真实请求一次 GitHub 与模型端点，任一不通就拒绝写入，
              避免把错误配置落盘。
            </p>
            <div className="row row-wrap">
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving}
                onClick={() => void save(true)}
              >
                {saving ? <Spinner /> : null}
                校验后保存
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving}
                onClick={() => void save(false)}
              >
                直接保存
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={saving}
                onClick={() => void load()}
              >
                放弃改动
              </button>
            </div>
          </div>
        </Card>
      </Section>
    </>
  )
}
