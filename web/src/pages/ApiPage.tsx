import { Card, CardHead, Chip, Section } from '../components/ui'

type Method = 'GET' | 'POST' | 'GET+POST'

type Endpoint = {
  method: Method
  path: string
  desc: string
  input?: string
  body?: string
  response: string
  errors?: string
  curl: string
}

type Group = {
  eyebrow: string
  title: string
  endpoints: Endpoint[]
}

const GROUPS: Group[] = [
  {
    eyebrow: 'REVIEW',
    title: '审查',
    endpoints: [
      {
        method: 'POST',
        path: '/api/plan',
        desc: '抓取 PR、过滤文件并生成审查计划，不调用模型。',
        body: `{ "pr_url": "https://github.com/owner/repo/pull/123" }`,
        response: `{ pr, filter, plan, validation, interface_impacts, run }`,
        errors: '400 pr_url 缺失 · 415 跨站或非 JSON',
        curl: `curl -X POST http://127.0.0.1:8787/api/plan \\
  -H "Content-Type: application/json" \\
  -d '{"pr_url":"https://github.com/owner/repo/pull/123"}'`,
      },
      {
        method: 'POST',
        path: '/api/review',
        desc: '同步执行完整审查；async_job:true 时改走任务化，立即返回 job_id。',
        body: `{ "pr_url": "https://github.com/owner/repo/pull/123", "async_job": true }`,
        response: `同步：{ pr, filter, plan, validation, review, interface_impacts, run }\n异步：202 { job_id, status, total_files, ... }`,
        errors: '400 pr_url 缺失 · 415 跨站或非 JSON',
        curl: `curl -X POST http://127.0.0.1:8787/api/review \\
  -H "Content-Type: application/json" \\
  -d '{"pr_url":"https://github.com/owner/repo/pull/123","async_job":true}'`,
      },
      {
        method: 'GET',
        path: '/api/jobs',
        desc: '最近任务列表（固定 10 条）。',
        response: `{ jobs: [{ job_id, status, total_files, completed_files, current_file, progress, error, elapsed_seconds, run_id }, ...] }`,
        curl: `curl http://127.0.0.1:8787/api/jobs`,
      },
      {
        method: 'GET',
        path: '/api/jobs/{id}',
        desc: '任务快照：状态、文件进度、错误与耗时。',
        input: '路径参数 id = job_id',
        response: `{ status, total_files, completed_files, current_file, progress, error, elapsed_seconds, run_id }`,
        errors: '404 任务不存在',
        curl: `curl http://127.0.0.1:8787/api/jobs/<job_id>`,
      },
      {
        method: 'GET',
        path: '/api/jobs/{id}/events',
        desc: 'SSE 进度流（text/event-stream），逐文件推送进度事件。',
        input: '路径参数 id = job_id',
        response: `data: {"completed_files":1,"total_files":4,"current_file":"src/app.py", ...}`,
        errors: '404 任务不存在',
        curl: `curl -N http://127.0.0.1:8787/api/jobs/<job_id>/events`,
      },
      {
        method: 'POST',
        path: '/api/jobs/{id}/cancel',
        desc: '服务端真取消，取消在文件边界生效。',
        input: '路径参数 id = job_id',
        response: `{ "ok": true, "job_id": "...", "message": "已请求停止。" }`,
        errors: '404 任务不存在或已结束 · 415 跨站或非 JSON',
        curl: `curl -X POST http://127.0.0.1:8787/api/jobs/<job_id>/cancel \\
  -H "Content-Type: application/json" -d '{}'`,
      },
      {
        method: 'POST',
        path: '/api/feedback',
        desc: '记录人工对某条 finding 的判断并落库。',
        body: `{ "run_id": "...", "finding_id": "...", "status": "accepted", "note": "" }`,
        response: `{ "ok": true, "run_id": "...", "finding_id": "...", "status": "accepted" }`,
        errors: '400 字段缺失 · 404 run/finding 不存在 · 415 跨站或非 JSON',
        curl: `curl -X POST http://127.0.0.1:8787/api/feedback \\
  -H "Content-Type: application/json" \\
  -d '{"run_id":"<run_id>","finding_id":"f-1","status":"accepted","note":""}'`,
      },
    ],
  },
  {
    eyebrow: 'REPORT',
    title: '报告与历史',
    endpoints: [
      {
        method: 'GET',
        path: '/api/report',
        desc: '单次 run 的完整报告：审查、计划、证据校验、接口影响与人工反馈。',
        input: 'query: run_id',
        response: `{ run_id, run, review, plan, validation, interface_impacts, feedback }`,
        errors: '400 run_id 缺失 · 404 run 不存在',
        curl: `curl "http://127.0.0.1:8787/api/report?run_id=<run_id>"`,
      },
      {
        method: 'GET',
        path: '/api/report/export',
        desc: '导出报告。markdown 走 text/markdown 并带附件名 pr<N>-<run8>.md；json 与 /api/report 同形。',
        input: 'query: run_id, format=markdown|json',
        response: `markdown：正文 + Content-Disposition: attachment; filename="pr<N>-<run8>.md"\njson：同 /api/report`,
        errors: '400 参数缺失或 format 非法 · 404 run 不存在',
        curl: `curl -OJ "http://127.0.0.1:8787/api/report/export?run_id=<run_id>&format=markdown"`,
      },
      {
        method: 'GET',
        path: '/api/history',
        desc: '历史 run 列表与聚合统计。limit 范围 1–200。',
        input: 'query: limit（可选）',
        response: `{ runs: [...], statistics: {...} }`,
        curl: `curl "http://127.0.0.1:8787/api/history?limit=30"`,
      },
      {
        method: 'GET',
        path: '/api/benchmark',
        desc: '基准准确率：precision / recall / F1 / 行号准确率，并附逐 case 明细。',
        input: 'query: strategy=static|ast|combined|all',
        response: `{ strategy, precision, recall, f1, false_positive_rate, line_accuracy, cases: [...] }`,
        curl: `curl "http://127.0.0.1:8787/api/benchmark?strategy=combined"`,
      },
    ],
  },
  {
    eyebrow: 'CONFIG',
    title: '配置与凭证',
    endpoints: [
      {
        method: 'GET+POST',
        path: '/api/config',
        desc: 'GET 读配置视图；POST 保存配置。掩码或留空 = 不改；未知键拒绝。',
        body: `{ "model_provider": { "model_name": "..." }, "api_key": "" }`,
        response: `GET：{ provider, base_url, model, api_format, api_key(masked), available_providers }\nPOST：{ ok, changed, rejected? }`,
        errors: '415 跨站或非 JSON · POST 未知键 → ok=false',
        curl: `curl http://127.0.0.1:8787/api/config\ncurl -X POST http://127.0.0.1:8787/api/config \\
  -H "Content-Type: application/json" -d '{"api_key":""}'`,
      },
      {
        method: 'GET',
        path: '/api/credentials',
        desc: '凭证健康检查。只返回掩码，绝不明文；probe=1 时做一次连通性探测。',
        input: 'query: probe=0|1',
        response: `{ github: {ok, masked}, model: {ok, masked}, ... }`,
        curl: `curl "http://127.0.0.1:8787/api/credentials?probe=1"`,
      },
      {
        method: 'GET',
        path: '/api/meta',
        desc: '运行环境：规则数、供应商数、tree-sitter、跨文件开关、静态分析开关、模型。',
        response: `{ rules, providers, tree_sitter, cross_file, static_analysis, model, ... }`,
        curl: `curl http://127.0.0.1:8787/api/meta`,
      },
      {
        method: 'GET',
        path: '/api/health',
        desc: '存活探针，用于确认本地服务已就绪。',
        response: `{ "ok": true, "service": "ai-pr-review" }`,
        curl: `curl http://127.0.0.1:8787/api/health`,
      },
    ],
  },
  {
    eyebrow: 'DEMO',
    title: '演示',
    endpoints: [
      {
        method: 'GET',
        path: '/api/demo/cases',
        desc: '离线演示用例清单。',
        response: `{ cases: [{ id, title, ... }, ...] }`,
        curl: `curl http://127.0.0.1:8787/api/demo/cases`,
      },
      {
        method: 'GET',
        path: '/api/demo/run',
        desc: '离线演示结果，无需 Token / API Key。',
        input: 'query: case',
        response: `{ case, plan, findings, validation, ... }`,
        errors: '404 case 不存在',
        curl: `curl "http://127.0.0.1:8787/api/demo/run?case=sql-injection"`,
      },
    ],
  },
  {
    eyebrow: 'PUBLISH',
    title: '发布',
    endpoints: [
      {
        method: 'POST',
        path: '/api/publish',
        desc: '发布审查评论到 GitHub PR。confirm=false 只预览不碰 GitHub；confirm=true 才真正发布。',
        body: `{ "run_id": "<run_id>", "confirm": false }`,
        response: `预览：{ status: "preview", comment_chars, ... }\n发布：{ status: "published"|"already_published", comment_url, comment_id }`,
        errors:
          '400 run_id 缺失 · 404 run 不存在 · 409 无 GitHub PR 链接 · 415 跨站或非 JSON · 502 GitHub 侧失败 · 503 未配置 Token',
        curl: `curl -X POST http://127.0.0.1:8787/api/publish \\
  -H "Content-Type: application/json" \\
  -d '{"run_id":"<run_id>","confirm":false}'`,
      },
      {
        method: 'POST',
        path: '/api/chat',
        desc: '对某次已完成的审查追问（无状态）。带 run_id 会注入该次审查的摘要与 findings；不带则按普通对话回答。',
        body: `{ "run_id": "<run_id，可选>", "text": "<问题>" }`,
        response: `{ reply, model, usage, context_meta: { bound_run, token_estimate, sections, truncated, note } }`,
        errors: '400 text 缺失 · 404 run 不存在 · 415 跨站或非 JSON · 502 上游模型失败 · 503 未配置模型 API Key',
        curl: `curl -X POST http://127.0.0.1:8787/api/chat \\
  -H "Content-Type: application/json" \\
  -d '{"run_id":"<run_id>","text":"这次审查有几个 finding？"}'`,
      },
    ],
  },
]

const CLI = [
  ['pr-review <PR_URL>', '对指定 PR 执行完整审查'],
  ['pr-review plan <PR_URL>', '只生成审查计划，不调用模型'],
  ['pr-review benchmark', '运行基准测试（--strategy all 可横向比较）'],
  ['pr-review demo', '离线演示规划、静态规则与证据校验'],
  ['pr-review feedback', '记录 finding 的人工反馈'],
  ['pr-review history', '查看历史运行记录'],
  ['pr-review stats', '查看聚合统计'],
  ['pr-review serve', '启动本工作台'],
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
  let index = 0
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">REFERENCE</div>
        <h1>接口与命令</h1>
        <p className="lead">
          工作台是 Python 标准库服务端 + 本地 HTTP 接口之上的前端。共 18 条 API 与静态资源路由；
          所有能力都可以脱离界面，直接用命令行或 HTTP 调用。完整契约见 <span className="mono">docs/API.md</span>。
        </p>
      </div>

      {GROUPS.map((group) => (
        <Section key={group.title} eyebrow={group.eyebrow} title={group.title}>
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
                      {endpoint.desc}
                    </p>
                    {endpoint.input && (
                      <div>
                        <span className="finding-field-label">入参</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {endpoint.input}
                        </pre>
                      </div>
                    )}
                    {endpoint.body && (
                      <div>
                        <span className="finding-field-label">请求体</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {endpoint.body}
                        </pre>
                      </div>
                    )}
                    <div>
                      <span className="finding-field-label">响应</span>
                      <pre className="code" style={{ marginTop: 5 }}>
                        {endpoint.response}
                      </pre>
                    </div>
                    {endpoint.errors && (
                      <div>
                        <span className="finding-field-label">错误码</span>
                        <pre className="code" style={{ marginTop: 5 }}>
                          {endpoint.errors}
                        </pre>
                      </div>
                    )}
                    <div>
                      <span className="finding-field-label">curl</span>
                      <pre className="code" style={{ marginTop: 5 }}>
                        {endpoint.curl}
                      </pre>
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>
        </Section>
      ))}

      <Section eyebrow="STATIC" title="静态资源">
        <Card>
          <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
            <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
              前端构建产物挂在 <span className="mono">/static/*</span>（<span className="mono">base=/static/</span>），
              含 SPA fallback：未命中的非 <span className="mono">/api/</span> 路径回退到入口页。
            </p>
            <pre className="code">{`curl http://127.0.0.1:8787/static/\ncurl http://127.0.0.1:8787/`}</pre>
          </div>
        </Card>
      </Section>

      <Section eyebrow="CLI" title="命令行等价能力">
        <Card flush>
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>命令</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {CLI.map(([cmd, desc]) => (
                  <tr key={cmd}>
                    <td className="mono" style={{ fontSize: 'var(--ds-text-sm)', whiteSpace: 'nowrap' }}>
                      {cmd}
                    </td>
                    <td className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                      {desc}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Section>

      <Section eyebrow="BOUNDARIES" title="运行边界">
        <Card>
          <div className="stack" style={{ gap: 'var(--ds-space-3)' }}>
            {[
              ['仅监听本机', '服务绑定 127.0.0.1，不对局域网或公网开放。'],
              ['请求体上限 64 KB', '超过上限的请求在读取前即被拒绝并关闭连接。'],
              [
                '写端点同源守卫',
                '全部 POST 要求 Content-Type: application/json 且同源，否则 415；OPTIONS → 405，不返回任何 Access-Control-* 头。',
              ],
              ['凭据不外传', 'GitHub Token 与模型 API Key 只从本地配置读取，界面与接口都不会展示明文。'],
              ['费用由模型产生', '计划模式零成本；完整审查按你配置的供应商计费，受单次与 24 小时预算约束。'],
            ].map(([title, body]) => (
              <div key={title} className="row" style={{ alignItems: 'flex-start', gap: 'var(--ds-space-3)' }}>
                <span className="badge st-valid" style={{ marginTop: 2 }}>
                  ✓
                </span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 'var(--ds-text-md)' }}>{title}</div>
                  <div className="muted" style={{ fontSize: 'var(--ds-text-sm)' }}>
                    {body}
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
