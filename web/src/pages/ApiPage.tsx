import { Card, CardHead, Chip, Section } from '../components/ui'
import { useT } from '../i18n'

type Method = 'GET' | 'POST' | 'GET+POST'

/**
 * 端点表。
 *
 * 只有给人看的文案进词典（存 key，渲染时 `t(key)`）：
 * `descKey` / `inputKey` / `errorsKey` 与含中文示例的 `responseKey` / `bodyKey` / `curlKey`。
 * `path` / `body` / `response` / `curl` 是纯英文技术示例，保持原样不翻译。
 */
type Endpoint = {
  method: Method
  path: string
  descKey: string
  inputKey?: string
  body?: string
  bodyKey?: string
  response?: string
  responseKey?: string
  errorsKey?: string
  curl?: string
  curlKey?: string
}

type Group = {
  eyebrow: string
  titleKey: string
  endpoints: Endpoint[]
}

const GROUPS: Group[] = [
  {
    eyebrow: 'REVIEW',
    titleKey: 'api.group.review',
    endpoints: [
      {
        method: 'POST',
        path: '/api/plan',
        descKey: 'api.endpoint.plan.desc',
        body: `{ "pr_url": "https://github.com/owner/repo/pull/123" }`,
        response: `{ pr, filter, plan, validation, interface_impacts, run }`,
        errorsKey: 'api.endpoint.plan.errors',
        curl: `curl -X POST http://127.0.0.1:8787/api/plan \\
  -H "Content-Type: application/json" \\
  -d '{"pr_url":"https://github.com/owner/repo/pull/123"}'`,
      },
      {
        method: 'POST',
        path: '/api/review',
        descKey: 'api.endpoint.review.desc',
        body: `{ "pr_url": "https://github.com/owner/repo/pull/123", "async_job": true }`,
        responseKey: 'api.endpoint.review.response',
        errorsKey: 'api.endpoint.review.errors',
        curl: `curl -X POST http://127.0.0.1:8787/api/review \\
  -H "Content-Type: application/json" \\
  -d '{"pr_url":"https://github.com/owner/repo/pull/123","async_job":true}'`,
      },
      {
        method: 'GET',
        path: '/api/jobs',
        descKey: 'api.endpoint.jobs.desc',
        response: `{ jobs: [{ job_id, status, total_files, completed_files, current_file, progress, error, elapsed_seconds, run_id }, ...] }`,
        curl: `curl http://127.0.0.1:8787/api/jobs`,
      },
      {
        method: 'GET',
        path: '/api/jobs/{id}',
        descKey: 'api.endpoint.job.desc',
        inputKey: 'api.input.pathParamId',
        response: `{ status, total_files, completed_files, current_file, progress, error, elapsed_seconds, run_id }`,
        errorsKey: 'api.endpoint.job.errors',
        curl: `curl http://127.0.0.1:8787/api/jobs/<job_id>`,
      },
      {
        method: 'GET',
        path: '/api/jobs/{id}/events',
        descKey: 'api.endpoint.jobEvents.desc',
        inputKey: 'api.input.pathParamId',
        response: `data: {"completed_files":1,"total_files":4,"current_file":"src/app.py", ...}`,
        errorsKey: 'api.endpoint.jobEvents.errors',
        curl: `curl -N http://127.0.0.1:8787/api/jobs/<job_id>/events`,
      },
      {
        method: 'POST',
        path: '/api/jobs/{id}/cancel',
        descKey: 'api.endpoint.jobCancel.desc',
        inputKey: 'api.input.pathParamId',
        responseKey: 'api.endpoint.jobCancel.response',
        errorsKey: 'api.endpoint.jobCancel.errors',
        curl: `curl -X POST http://127.0.0.1:8787/api/jobs/<job_id>/cancel \\
  -H "Content-Type: application/json" -d '{}'`,
      },
      {
        method: 'POST',
        path: '/api/feedback',
        descKey: 'api.endpoint.feedback.desc',
        body: `{ "run_id": "...", "finding_id": "...", "status": "accepted", "note": "" }`,
        response: `{ "ok": true, "run_id": "...", "finding_id": "...", "status": "accepted" }`,
        errorsKey: 'api.endpoint.feedback.errors',
        curl: `curl -X POST http://127.0.0.1:8787/api/feedback \\
  -H "Content-Type: application/json" \\
  -d '{"run_id":"<run_id>","finding_id":"f-1","status":"accepted","note":""}'`,
      },
    ],
  },
  {
    eyebrow: 'REPORT',
    titleKey: 'api.group.report',
    endpoints: [
      {
        method: 'GET',
        path: '/api/report',
        descKey: 'api.endpoint.report.desc',
        inputKey: 'api.input.queryRunId',
        response: `{ run_id, run, review, plan, validation, interface_impacts, feedback }`,
        errorsKey: 'api.endpoint.report.errors',
        curl: `curl "http://127.0.0.1:8787/api/report?run_id=<run_id>"`,
      },
      {
        method: 'GET',
        path: '/api/report/export',
        descKey: 'api.endpoint.reportExport.desc',
        inputKey: 'api.input.queryExport',
        responseKey: 'api.endpoint.reportExport.response',
        errorsKey: 'api.endpoint.reportExport.errors',
        curl: `curl -OJ "http://127.0.0.1:8787/api/report/export?run_id=<run_id>&format=markdown"`,
      },
      {
        method: 'GET',
        path: '/api/history',
        descKey: 'api.endpoint.history.desc',
        inputKey: 'api.input.queryLimit',
        response: `{ runs: [...], statistics: {...} }`,
        curl: `curl "http://127.0.0.1:8787/api/history?limit=30"`,
      },
      {
        method: 'GET',
        path: '/api/benchmark',
        descKey: 'api.endpoint.benchmark.desc',
        inputKey: 'api.input.queryStrategy',
        response: `{ strategy, precision, recall, f1, false_positive_rate, line_accuracy, cases: [...] }`,
        curl: `curl "http://127.0.0.1:8787/api/benchmark?strategy=combined"`,
      },
    ],
  },
  {
    eyebrow: 'CONFIG',
    titleKey: 'api.group.config',
    endpoints: [
      {
        method: 'GET+POST',
        path: '/api/config',
        descKey: 'api.endpoint.config.desc',
        body: `{ "model_provider": { "model_name": "..." }, "api_key": "" }`,
        responseKey: 'api.endpoint.config.response',
        errorsKey: 'api.endpoint.config.errors',
        curl: `curl http://127.0.0.1:8787/api/config\ncurl -X POST http://127.0.0.1:8787/api/config \\
  -H "Content-Type: application/json" -d '{"api_key":""}'`,
      },
      {
        method: 'GET',
        path: '/api/credentials',
        descKey: 'api.endpoint.credentials.desc',
        inputKey: 'api.input.queryProbe',
        response: `{ github: {ok, masked}, model: {ok, masked}, ... }`,
        curl: `curl "http://127.0.0.1:8787/api/credentials?probe=1"`,
      },
      {
        method: 'GET',
        path: '/api/meta',
        descKey: 'api.endpoint.meta.desc',
        response: `{ rules, providers, tree_sitter, cross_file, static_analysis, model, ... }`,
        curl: `curl http://127.0.0.1:8787/api/meta`,
      },
      {
        method: 'GET',
        path: '/api/health',
        descKey: 'api.endpoint.health.desc',
        response: `{ "ok": true, "service": "ai-pr-review" }`,
        curl: `curl http://127.0.0.1:8787/api/health`,
      },
    ],
  },
  {
    eyebrow: 'DEMO',
    titleKey: 'api.group.demo',
    endpoints: [
      {
        method: 'GET',
        path: '/api/demo/cases',
        descKey: 'api.endpoint.demoCases.desc',
        response: `{ cases: [{ id, title, ... }, ...] }`,
        curl: `curl http://127.0.0.1:8787/api/demo/cases`,
      },
      {
        method: 'GET',
        path: '/api/demo/run',
        descKey: 'api.endpoint.demoRun.desc',
        inputKey: 'api.input.queryCase',
        response: `{ case, plan, findings, validation, ... }`,
        errorsKey: 'api.endpoint.demoRun.errors',
        curl: `curl "http://127.0.0.1:8787/api/demo/run?case=sql-injection"`,
      },
    ],
  },
  {
    eyebrow: 'PUBLISH',
    titleKey: 'api.group.publish',
    endpoints: [
      {
        method: 'POST',
        path: '/api/publish',
        descKey: 'api.endpoint.publish.desc',
        body: `{ "run_id": "<run_id>", "confirm": false }`,
        responseKey: 'api.endpoint.publish.response',
        errorsKey: 'api.endpoint.publish.errors',
        curl: `curl -X POST http://127.0.0.1:8787/api/publish \\
  -H "Content-Type: application/json" \\
  -d '{"run_id":"<run_id>","confirm":false}'`,
      },
      {
        method: 'POST',
        path: '/api/chat',
        descKey: 'api.endpoint.chat.desc',
        bodyKey: 'api.endpoint.chat.body',
        response: `{ reply, model, usage, context_meta: { bound_run, token_estimate, sections, truncated, note } }`,
        errorsKey: 'api.endpoint.chat.errors',
        curlKey: 'api.endpoint.chat.curl',
      },
    ],
  },
]

const CLI: [string, string][] = [
  ['pr-review <PR_URL>', 'api.cli.run'],
  ['pr-review plan <PR_URL>', 'api.cli.plan'],
  ['pr-review benchmark', 'api.cli.benchmark'],
  ['pr-review demo', 'api.cli.demo'],
  ['pr-review feedback', 'api.cli.feedback'],
  ['pr-review history', 'api.cli.history'],
  ['pr-review stats', 'api.cli.stats'],
  ['pr-review serve', 'api.cli.serve'],
]

/** 运行边界：[titleKey, bodyKey]。 */
const BOUNDARIES: [string, string][] = [
  ['api.boundary.local.title', 'api.boundary.local.body'],
  ['api.boundary.limit.title', 'api.boundary.limit.body'],
  ['api.boundary.cors.title', 'api.boundary.cors.body'],
  ['api.boundary.secrets.title', 'api.boundary.secrets.body'],
  ['api.boundary.cost.title', 'api.boundary.cost.body'],
]

function MethodBadge({ method }: { method: Method }) {
  const labels: Method[] = ['GET', 'POST', 'GET+POST']
  return (
    <span className="row" style={{ gap: 4 }}>
      {labels
        .filter((m) => method === m || method === 'GET+POST')
        .map((m) => (
          <span
            key={m}
            className="badge"
            style={{
              background: m === 'GET' ? 'var(--ds-state-valid-bg)' : 'var(--ds-color-brand-soft)',
              color: m === 'GET' ? 'var(--ds-state-valid)' : 'var(--ds-color-brand-deep)',
            }}
          >
            {m}
          </span>
        ))}
    </span>
  )
}

export function ApiPage() {
  const t = useT()
  let index = 0
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">REFERENCE</div>
        <h1>{t('api.hero.title')}</h1>
        <p className="lead">
          {t('api.hero.lead')}
          <span className="mono">docs/API.md</span>
          {t('api.hero.leadTail')}
        </p>
      </div>

      {GROUPS.map((group) => (
        <Section key={group.titleKey} eyebrow={group.eyebrow} title={t(group.titleKey)}>
          <div className="stack">
            {group.endpoints.map((endpoint) => {
              index += 1
              return (
                <Card key={`${endpoint.method}-${endpoint.path}`} flush>
                  <CardHead
                    title={
                      <span className="row" style={{ gap: 'var(--ds-space-3)' }}>
                        <MethodBadge method={endpoint.method} />
                        <span className="mono" style={{ fontSize: 'var(--ds-text-md)' }}>
                          {endpoint.path}
                        </span>
                      </span>
                    }
                    extra={<Chip>{index}</Chip>}
                  />
                  <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
                    <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                      {t(endpoint.descKey)}
                    </p>
                    {endpoint.inputKey && (
                      <div>
                        <span className="finding-field-label">{t('api.field.input')}</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {t(endpoint.inputKey)}
                        </pre>
                      </div>
                    )}
                    {(endpoint.bodyKey || endpoint.body) && (
                      <div>
                        <span className="finding-field-label">{t('api.field.body')}</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {endpoint.bodyKey ? t(endpoint.bodyKey) : endpoint.body}
                        </pre>
                      </div>
                    )}
                    <div>
                      <span className="finding-field-label">{t('api.field.response')}</span>
                      <pre className="code" style={{ marginTop: 5 }}>
                        {endpoint.responseKey ? t(endpoint.responseKey) : endpoint.response}
                      </pre>
                    </div>
                    {endpoint.errorsKey && (
                      <div>
                        <span className="finding-field-label">{t('api.field.errors')}</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {t(endpoint.errorsKey)}
                        </pre>
                      </div>
                    )}
                    <div>
                      <span className="finding-field-label">curl</span>
                      <pre className="code" style={{ marginTop: 5 }}>
                        {endpoint.curlKey ? t(endpoint.curlKey) : endpoint.curl}
                      </pre>
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>
        </Section>
      ))}

      <Section eyebrow="STATIC" title={t('api.static.title')}>
        <Card>
          <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
            <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
              {t('api.static.body1')}
              <span className="mono">/static/*</span>
              {t('api.static.body2')}
              <span className="mono">base=/static/</span>
              {t('api.static.body3')}
              <span className="mono">/api/</span>
              {t('api.static.body4')}
            </p>
            <pre className="code">{`curl http://127.0.0.1:8787/static/\ncurl http://127.0.0.1:8787/`}</pre>
          </div>
        </Card>
      </Section>

      <Section eyebrow="CLI" title={t('api.cli.title')}>
        <Card flush>
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>{t('api.cli.col.command')}</th>
                  <th>{t('api.cli.col.desc')}</th>
                </tr>
              </thead>
              <tbody>
                {CLI.map(([cmd, descKey]) => (
                  <tr key={cmd}>
                    <td className="mono" style={{ fontSize: 'var(--ds-text-sm)', whiteSpace: 'nowrap' }}>
                      {cmd}
                    </td>
                    <td className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                      {t(descKey)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <Section eyebrow="BOUNDARIES" title={t('api.boundary.title')}>
        <Card>
          <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
            {BOUNDARIES.map(([titleKey, bodyKey]) => (
              <div
                key={titleKey}
                className="row"
                style={{ alignItems: 'flex-start', gap: 'var(--ds-space-3)' }}
              >
                <span className="badge st-valid" style={{ marginTop: 2 }}>
                  ✓
                </span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 'var(--ds-text-md)' }}>{t(titleKey)}</div>
                  <div className="muted" style={{ fontSize: 'var(--ds-text-sm)' }}>
                    {t(bodyKey)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </Section>
    </>
  )
}
