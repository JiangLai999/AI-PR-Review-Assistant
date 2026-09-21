import { Card, CardHead, Chip, Section } from '../components/ui'

type Endpoint = {
  method: 'GET' | 'POST'
  path: string
  desc: string
  body?: string
  response: string
}

const ENDPOINTS: Endpoint[] = [
  {
    method: 'GET',
    path: '/api/health',
    desc: '健康检查，用于确认本地服务已就绪。',
    response: `{ "ok": true, "service": "ai-pr-review" }`,
  },
  {
    method: 'POST',
    path: '/api/plan',
    desc: '抓取 PR、过滤文件并生成审查计划，不调用模型。',
    body: `{ "pr_url": "https://github.com/owner/repo/pull/123" }`,
    response: `{ pr, filter, plan, validation, interface_impacts, run }`,
  },
  {
    method: 'POST',
    path: '/api/review',
    desc: '执行完整审查：逐文件调用模型、合并规则命中、校验证据并落库。',
    body: `{ "pr_url": "https://github.com/owner/repo/pull/123" }`,
    response: `{ pr, filter, plan, validation, review, interface_impacts, run }`,
  },
  {
    method: 'GET',
    path: '/api/history?limit=30',
    desc: '返回历史运行记录与聚合统计。limit 范围 1–200。',
    response: `{ runs: [...], statistics: {...} }`,
  },
  {
    method: 'GET',
    path: '/api/report?run_id=<id>',
    desc: '按运行 ID 取回完整报告：审查结果、计划、证据校验、接口影响与人工反馈。',
    response: `{ run_id, run, review, plan, validation, interface_impacts, feedback }`,
  },
  {
    method: 'GET',
    path: '/api/benchmark?strategy=combined',
    desc: '返回基准测试报告。strategy 可选 static / ast / combined / all。',
    response: `{ strategy, precision, recall, f1, false_positive_rate, cases: [...] }`,
  },
  {
    method: 'POST',
    path: '/api/feedback',
    desc: '记录人工对某条 finding 的判断。status 可选 accepted / rejected / fixed / needs_review。',
    body: `{ "run_id": "...", "finding_id": "...", "status": "accepted", "note": "" }`,
    response: `{ "ok": true, "run_id": "...", "finding_id": "...", "status": "accepted" }`,
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

export function ApiPage() {
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">REFERENCE</div>
        <h1>接口与命令</h1>
        <p className="lead">
          工作台是 Python 标准库服务端 + 本地 HTTP 接口之上的前端。所有能力都可以脱离界面，
          直接用命令行或 HTTP 调用。
        </p>
      </div>

      <Section eyebrow="HTTP" title="本地接口">
        <div className="stack">
          {ENDPOINTS.map((endpoint, index) => (
            <Card key={endpoint.path} flush>
              <CardHead
                title={
                  <span className="row" style={{ gap: 'var(--ds-space-3)' }}>
                    <span
                      className="badge"
                      style={{
                        background:
                          endpoint.method === 'GET' ? 'var(--ds-state-valid-bg)' : 'var(--ds-color-brand-soft)',
                        color:
                          endpoint.method === 'GET' ? 'var(--ds-state-valid)' : 'var(--ds-color-brand-deep)',
                      }}
                    >
                      {endpoint.method}
                    </span>
                    <span className="mono" style={{ fontSize: 'var(--ds-text-md)' }}>
                      {endpoint.path}
                    </span>
                  </span>
                }
                extra={<Chip>{index + 1}</Chip>}
              />
              <div className="card-body stack" style={{ gap: 'var(--ds-space-3)' }}>
                <p className="muted" style={{ fontSize: 'var(--ds-text-md)' }}>
                  {endpoint.desc}
                </p>
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
              </div>
            </Card>
          ))}
        </div>
      </Section>

      <Section eyebrow="CLI" title="命令行等价能力">
        <Card flush >
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
              ['凭据不外传', 'GitHub Token 与模型 API Key 只从本地配置读取，界面不会展示明文。'],
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
