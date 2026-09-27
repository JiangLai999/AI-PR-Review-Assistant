import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  ConfigOptions,
  ConfigView,
  CredentialItem,
  CredentialReport,
  OptionItem,
  SaveConfigResponse,
} from '../api/types'
import { Card, CardHead, Chip, Notice, Section, Spinner } from '../components/ui'
import { setLang, t, useT } from '../i18n'

const API_FORMATS = ['openai', 'anthropic'] as const

/**
 * CLI 配置助手的阶段号（TUI `frontend/tui/src/app.tsx:1792-1808` 的 `stageNames` /
 * `screenStages`，运行时按 `:2761-2763` 渲染成 `N/6 · 阶段名`，实测帧见
 * `.pytest_claude/ai-pr-review-repo-context-check/frame-repo-context-zh.txt:9`
 * 的 `5/6 · 界面与输出`）。这里只做标注，取值以 CLI 为准。
 */
const STAGE_PROVIDER_KEY = 'settings.stage.provider'
const STAGE_WEB_ONLY_KEY = 'settings.stage.webOnly'
const STAGE_PREFERENCES_KEY = 'settings.stage.preferences'
const STAGE_SAVE_KEY = 'settings.stage.save'

const NUMERIC_FIELDS: { key: string; labelKey: string; hintKey: string; step?: number }[] = [
  { key: 'max_tokens', labelKey: 'settings.numeric.maxTokens.label', hintKey: 'settings.numeric.maxTokens.hint' },
  { key: 'timeout_seconds', labelKey: 'settings.numeric.timeout.label', hintKey: 'settings.numeric.timeout.hint' },
  {
    key: 'review_concurrency',
    labelKey: 'settings.numeric.concurrency.label',
    hintKey: 'settings.numeric.concurrency.hint',
  },
  {
    key: 'cross_file_max_files',
    labelKey: 'settings.numeric.crossFile.label',
    hintKey: 'settings.numeric.crossFile.hint',
  },
  { key: 'max_cost_per_run', labelKey: 'settings.numeric.costRun.label', hintKey: 'settings.numeric.costRun.hint', step: 0.1 },
  { key: 'max_cost_per_24h', labelKey: 'settings.numeric.cost24h.label', hintKey: 'settings.numeric.cost24h.hint', step: 0.5 },
]

const BOOL_FIELDS: { key: string; labelKey: string; hintKey: string }[] = [
  { key: 'enable_static_analysis', labelKey: 'settings.bool.staticAst.label', hintKey: 'settings.bool.staticAst.hint' },
  {
    key: 'enable_cross_file_review',
    labelKey: 'settings.bool.crossFile.label',
    hintKey: 'settings.bool.crossFile.hint',
  },
]

/** 设置页可提交的 6 个偏好键；对应 CLI 助手第 5 阶段同一份 `preferences`。 */
type PreferenceKey =
  | 'ui_language'
  | 'output_format'
  | 'chat_layout'
  | 'workbench_mode'
  | 'repo_context'
  | 'review_reasoning_effort'

/** `ConfigView.options` 里每个下拉对应的清单键（与后端 `options` 的键名一一对应）。 */
type OptionListKey =
  | 'ui_languages'
  | 'output_formats'
  | 'chat_layouts'
  | 'workbench_modes'
  | 'repo_contexts'
  | 'review_efforts'

interface PreferenceField {
  key: PreferenceKey
  options: OptionListKey
  labelKey: string
  hintKey: string
}

const INTERFACE_FIELDS: PreferenceField[] = [
  {
    key: 'ui_language',
    options: 'ui_languages',
    labelKey: 'settings.pref.uiLanguage.label',
    hintKey: 'settings.pref.uiLanguage.hint',
  },
  {
    key: 'output_format',
    options: 'output_formats',
    labelKey: 'settings.pref.outputFormat.label',
    hintKey: 'settings.pref.outputFormat.hint',
  },
  {
    key: 'chat_layout',
    options: 'chat_layouts',
    labelKey: 'settings.pref.chatLayout.label',
    hintKey: 'settings.pref.chatLayout.hint',
  },
  {
    key: 'workbench_mode',
    options: 'workbench_modes',
    labelKey: 'settings.pref.workbenchMode.label',
    hintKey: 'settings.pref.workbenchMode.hint',
  },
]

const REVIEW_FIELDS: PreferenceField[] = [
  {
    key: 'repo_context',
    options: 'repo_contexts',
    labelKey: 'settings.pref.repoContext.label',
    hintKey: 'settings.pref.repoContext.hint',
  },
  {
    key: 'review_reasoning_effort',
    options: 'review_efforts',
    labelKey: 'settings.pref.reviewEffort.label',
    hintKey: 'settings.pref.reviewEffort.hint',
  },
]

const PREFERENCE_FIELDS: PreferenceField[] = [...INTERFACE_FIELDS, ...REVIEW_FIELDS]

const EMPTY_PREFERENCES: Record<PreferenceKey, string> = {
  ui_language: '',
  output_format: '',
  chat_layout: '',
  workbench_mode: '',
  repo_context: '',
  review_reasoning_effort: '',
}

function listOf(options: ConfigOptions | undefined, key: OptionListKey): OptionItem[] {
  const list = options?.[key]
  return Array.isArray(list) ? list : []
}

/**
 * 组装 6 个偏好键的提交内容。
 *
 * 后端没给这一项的清单 = 旧后端（或该项未上线）：**跳过**——`POST /api/config`
 * 对白名单外的键一律 400（`src/ai_pr_review/web_config.py:84-88`），
 * 提交反而是"看起来保存了、其实整单被拒"。空值同样跳过，避免用空串覆盖磁盘上的真值。
 */
function preferencePayload(
  options: ConfigOptions | undefined,
  values: Record<PreferenceKey, string>,
): Record<string, string> {
  const payload: Record<string, string> = {}
  for (const field of PREFERENCE_FIELDS) {
    if (listOf(options, field.options).length === 0) continue
    const value = values[field.key]
    if (value) payload[field.key] = value
  }
  return payload
}

/**
 * `POST /api/config`。这里刻意不走 `api.saveConfig`：client.ts 的 `request()` 在非 2xx 时
 * 只读响应体的 `error` 键，而本端点 `ok:false` 的 400 body 是
 * `{ok, changed, message, save_key_used, config}`（`src/ai_pr_review/web_server.py:409-419`），
 * 走统一通道会把 `message` 丢掉、界面只剩 "HTTP 400"。client.ts 不在本任务
 * write_scope 内，故就地适配一处（见 docs/claude-web-settings-parity.md 未决项）。
 */
async function postConfig(payload: Record<string, unknown>): Promise<SaveConfigResponse> {
  let response: Response
  try {
    response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch (error) {
    throw new Error(
      t('api.error.offline', {
        detail: error instanceof Error ? error.message : String(error),
      }),
    )
  }

  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    throw new Error(t('api.error.nonJson', { detail: text.slice(0, 200) }))
  }

  const record = (body ?? {}) as Record<string, unknown>
  if (!record.config) {
    // 凭证校验失败等分支的 body 是 `{error, credentials}`：只有 error 可展示。
    const message =
      typeof record.error === 'string' ? record.error : t('settings.error.saveHttp', { status: response.status })
    throw new Error(message)
  }
  return body as SaveConfigResponse
}

function StatusPill({ item }: { item: CredentialItem }) {
  const t = useT()
  return (
    <span className={`badge ${item.ok ? 'st-valid' : item.configured ? 'st-invalid' : 'st-needs_review'}`}>
      <i className="badge-dot" />
      {item.ok
        ? t('settings.credential.status.ok')
        : item.configured
          ? t('settings.credential.status.bad')
          : t('settings.credential.status.none')}
    </span>
  )
}

function PreferenceSelect({
  field,
  options,
  value,
  onChange,
}: {
  field: PreferenceField
  options: ConfigOptions | undefined
  value: string
  onChange: (key: PreferenceKey, value: string) => void
}) {
  const list = listOf(options, field.options)
  const supported = list.length > 0
  const t = useT()
  // 后端给了清单但没有当前值（例如配置文件里是别的取值）：把真值原样放进下拉，
  // 不要让控件事先跳到第一个选项、把用户没改过的设置悄悄改掉。
  const stale = supported && Boolean(value) && !list.some((item) => item.value === value)

  return (
    <div className="field">
      <label className="label" htmlFor={`pref-${field.key}`}>
        {t(field.labelKey)}
      </label>
      <select
        id={`pref-${field.key}`}
        className="select"
        value={value}
        disabled={!supported}
        onChange={(e) => onChange(field.key, e.target.value)}
      >
        {!supported && <option value={value}>{t('settings.unsupported')}</option>}
        {stale && <option value={value}>{t('settings.pref.staleOption', { value })}</option>}
        {list.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
        {supported
          ? t(field.hintKey)
          : t('settings.pref.unsupportedHint', {
              unsupported: t('settings.unsupported'),
              options: field.options,
            })}
      </span>
    </div>
  )
}

/** 一组偏好下拉（界面与输出 / 审查偏好共用同一套渲染）。 */
function PreferenceGroup({
  eyebrow,
  title,
  description,
  fields,
  options,
  values,
  onChange,
}: {
  eyebrow: string
  title: string
  description: string
  fields: PreferenceField[]
  options: ConfigOptions | undefined
  values: Record<PreferenceKey, string>
  onChange: (key: PreferenceKey, value: string) => void
}) {
  const t = useT()
  const allUnsupported = fields.every((field) => listOf(options, field.options).length === 0)
  return (
    <Section
      eyebrow={eyebrow}
      title={title}
      description={description}
      extra={<Chip>{t(STAGE_PREFERENCES_KEY)}</Chip>}
    >
      <Card flush>
        <div className="card-body stack">
          {allUnsupported && (
            <Notice kind="info">{t('settings.pref.unsupportedNotice')}</Notice>
          )}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 'var(--ds-space-4)',
            }}
          >
            {fields.map((field) => (
              <PreferenceSelect
                key={field.key}
                field={field}
                options={options}
                value={values[field.key]}
                onChange={onChange}
              />
            ))}
          </div>
        </div>
      </Card>
    </Section>
  )
}

export function SettingsPage({ onSaved }: { onSaved?: () => void }) {
  const t = useT()
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
  const [preferences, setPreferences] = useState<Record<PreferenceKey, string>>(EMPTY_PREFERENCES)

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
    // 6 个偏好：旧后端没有 `preferences`，全部落空串（控件此时也是禁用态）。
    const prefs = { ...EMPTY_PREFERENCES }
    for (const field of PREFERENCE_FIELDS) {
      const value = view.preferences?.[field.key]
      if (typeof value === 'string') prefs[field.key] = value
    }
    setPreferences(prefs)
  }, [])

  const load = useCallback(async () => {
    try {
      const view = await api.config()
      hydrate(view)
    } catch (e) {
      setMessage({
        kind: 'error',
        text: t('settings.message.loadFailed', { detail: e instanceof Error ? e.message : String(e) }),
      })
    }
  }, [hydrate, t])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * 重新探测凭证。
   *
   * `silent=true` 时不碰顶部提示：保存之后也要刷新凭证面板，但 `setMessage(null)`
   * 会把刚拿到的保存结果（成功文案 / 后端 400 的 message）当场冲掉 —— 用户就再也
   * 看不到"到底保存成功没有"。手动点「重新探测」才清提示。
   */
  async function probe({ silent = false }: { silent?: boolean } = {}) {
    setProbing(true)
    if (!silent) setMessage(null)
    try {
      setReport(await api.credentials(true))
    } catch (e) {
      if (!silent) {
        setMessage({
          kind: 'error',
          text: t('settings.message.probeFailed', { detail: e instanceof Error ? e.message : String(e) }),
        })
      }
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

  const setPreference = useCallback((key: PreferenceKey, value: string) => {
    setPreferences((prev) => ({ ...prev, [key]: value }))
  }, [])

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
        ...preferencePayload(config?.options, preferences),
      }
      if (apiKey.trim()) payload.api_key = apiKey.trim()
      if (githubToken.trim()) payload.github_token = githubToken.trim()

      const result = await postConfig(payload)
      if (!result.ok) {
        // 后端明确拒绝（ok:false + message）：原样显示 message，绝不落到成功分支，
        // 也不 hydrate —— 用户刚填的密钥不能被服务端旧值冲掉。
        await probe({ silent: true })
        setMessage({ kind: 'error', text: result.message || t('settings.message.saveRejected') })
        return
      }
      hydrate(result.config)
      // 界面语言本身就是一个保存项：保存成功后立刻切语言，改完 English 当场全站生效。
      setLang(result.config.preferences?.ui_language)
      await probe({ silent: true })
      setMessage({ kind: 'ok', text: result.message })
      onSaved?.()
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e)
      await probe({ silent: true })
      setMessage({ kind: 'error', text })
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
        <h1>{t('settings.hero.title')}</h1>
        <p className="lead">
          {t('settings.hero.lead')}
          <b>{t('settings.hero.leadStrong')}</b>
          {t('settings.hero.leadTail')}
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
        title={t('settings.credentials.title')}
        description={t('settings.credentials.desc')}
        extra={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void probe()} disabled={probing}>
            {probing ? <Spinner /> : null}
            {t('settings.credentials.probe')}
          </button>
        }
      >
        <Card flush>
          <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
            {(report?.items ?? []).length === 0 && (
              <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                {t('settings.credentials.empty')}
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
                    {t('settings.credentials.fixHint', { hint: item.fix_hint })}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
      </Section>

      <Section
        eyebrow="STAGE 2–4 · PROVIDER & CREDENTIALS"
        title={t('settings.provider.title')}
        description={t('settings.provider.desc')}
        extra={<Chip>{t(STAGE_PROVIDER_KEY)}</Chip>}
      >
        <Card flush>
          <CardHead
            title={t('settings.provider.connection')}
            extra={
              <span className="row" style={{ gap: 'var(--ds-space-2)' }}>
                {config.runtime_profile && (
                  <Chip accent>{t('settings.provider.runtime', { profile: config.runtime_profile })}</Chip>
                )}
                <Chip>{config.config_path.split(/[\\/]/).pop()}</Chip>
              </span>
            }
          />
          <div className="card-body stack">
            <div className="field">
              <label className="label" htmlFor="provider">
                {t('settings.provider.presetLabel')}
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
                <option value="custom">{t('settings.provider.customOption')}</option>
                {config.available_providers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {t('settings.provider.presetOption', { display: p.display_name, name: p.name })}
                  </option>
                ))}
              </select>
              {presetHint && (
                <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                  {t('settings.provider.presetHint', { url: presetHint })}
                </span>
              )}
            </div>

            <div className="field">
              <label className="label" htmlFor="base-url">
                {t('settings.provider.baseUrlLabel')}
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
                  {t('settings.provider.modelLabel')}
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
                  {t('settings.provider.formatLabel')}
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
                {t('settings.provider.apiKeyLabel')}
                {config.api_key_set && (
                  <span className="dim">
                    {t('settings.provider.configuredNote', { masked: config.api_key_masked })}
                  </span>
                )}
              </label>
              <input
                id="api-key"
                className="input"
                type="password"
                value={apiKey}
                spellCheck={false}
                autoComplete="off"
                placeholder={config.api_key_set ? t('settings.provider.apiKeyKeep') : 'sk-…'}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="gh-token">
                GitHub Token
                {config.github_token_set && (
                  <span className="dim">
                    {t('settings.provider.configuredNote', { masked: config.github_token_masked })}
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
                placeholder={config.github_token_set ? t('settings.provider.tokenKeep') : 'ghp_…'}
                onChange={(e) => setGithubToken(e.target.value)}
              />
              <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                {t('settings.provider.tokenHint')}
              </span>
            </div>
          </div>
        </Card>
      </Section>

      <Section
        eyebrow="BEHAVIOUR · WEB ONLY"
        title={t('settings.cost.title')}
        description={t('settings.cost.desc')}
        extra={<Chip>{t(STAGE_WEB_ONLY_KEY)}</Chip>}
      >
        <Card flush>
          <div className="card-body stack">
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 'var(--ds-space-4)',
              }}
            >
              {NUMERIC_FIELDS.map((field) => {
                // 范围来自后端 options.numeric_ranges（单一真相源）；旧后端没有就退回本地 step。
                const range = config.options?.numeric_ranges?.[field.key]
                return (
                  <div className="field" key={field.key}>
                    <label className="label" htmlFor={field.key}>
                      {t(field.labelKey)}
                    </label>
                    <input
                      id={field.key}
                      className="input"
                      type="number"
                      min={range?.min}
                      max={range?.max}
                      step={range?.step ?? field.step ?? 1}
                      value={numbers[field.key] ?? 0}
                      onChange={(e) =>
                        setNumbers((prev) => ({ ...prev, [field.key]: Number(e.target.value) }))
                      }
                    />
                    <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                      {t(field.hintKey)}
                      {range && (range.min !== undefined || range.max !== undefined) && (
                        <>
                          {' '}
                          {t('settings.cost.range', { min: range.min ?? '-∞', max: range.max ?? '+∞' })}
                        </>
                      )}
                    </span>
                  </div>
                )
              })}
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
                    <span style={{ fontSize: 'var(--ds-text-md)' }}>{t(field.labelKey)}</span>
                    <br />
                    <span className="dim" style={{ fontSize: 'var(--ds-text-2xs)' }}>
                      {t(field.hintKey)}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </Card>
      </Section>

      <PreferenceGroup
        eyebrow="STAGE 5 · UI & OUTPUT"
        title={t('settings.group.interface.title')}
        description={t('settings.group.interface.desc')}
        fields={INTERFACE_FIELDS}
        options={config.options}
        values={preferences}
        onChange={setPreference}
      />

      <PreferenceGroup
        eyebrow="STAGE 5 · REVIEW PREFERENCES"
        title={t('settings.group.review.title')}
        description={t('settings.group.review.desc')}
        fields={REVIEW_FIELDS}
        options={config.options}
        values={preferences}
        onChange={setPreference}
      />

      <Section
        eyebrow="STAGE 6 · SAVE"
        title={t('settings.save.title')}
        description={t('settings.save.desc')}
        extra={<Chip>{t(STAGE_SAVE_KEY)}</Chip>}
      >
        <Card>
          <div className="stack">
            <p className="muted" style={{ fontSize: 'var(--ds-text-md)', lineHeight: 1.65 }}>
              {t('settings.save.body')}
            </p>
            <div className="row row-wrap">
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving}
                onClick={() => void save(true)}
              >
                {saving ? <Spinner /> : null}
                {t('settings.save.validate')}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving}
                onClick={() => void save(false)}
              >
                {t('settings.save.direct')}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={saving}
                onClick={() => void load()}
              >
                {t('settings.save.discard')}
              </button>
            </div>
          </div>
        </Card>
      </Section>
    </>
  )
}
