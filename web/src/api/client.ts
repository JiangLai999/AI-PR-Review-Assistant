import type {
  BenchmarkReport,
  DemoCasesResponse,
  DemoResult,
  ConfigView,
  CredentialReport,
  FeedbackStatus,
  HistoryResponse,
  JobSnapshot,
  MetaResponse,
  PublishResponse,
  ReportExportFormat,
  ReportResponse,
  ReviewResponse,
  SaveConfigResponse,
} from './types'

const BASE = ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (error) {
    // 主动取消不是错误，交给调用方按「已取消」处理
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      `无法连接到本地服务：${error instanceof Error ? error.message : String(error)}`,
      0,
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError(`服务返回了非 JSON 内容：${text.slice(0, 200)}`, response.status)
    }
  }

  if (!response.ok) {
    const message =
      payload && typeof payload === 'object' && 'error' in payload
        ? String((payload as { error: unknown }).error)
        : `HTTP ${response.status}`
    throw new ApiError(message, response.status)
  }
  return payload as T
}

export const api = {
  health: () => request<{ ok: boolean; service: string }>('/api/health'),

  demoCases: () => request<DemoCasesResponse>('/api/demo/cases'),

  demoRun: (caseKey = 'sql-injection') =>
    request<DemoResult>(`/api/demo/run?case=${encodeURIComponent(caseKey)}`),

  plan: (prUrl: string, signal?: AbortSignal) =>
    request<ReviewResponse>('/api/plan', {
      method: 'POST',
      body: JSON.stringify({ pr_url: prUrl }),
      signal,
    }),

  review: (prUrl: string, signal?: AbortSignal) =>
    request<ReviewResponse>('/api/review', {
      method: 'POST',
      body: JSON.stringify({ pr_url: prUrl }),
      signal,
    }),

  history: (limit = 30) => request<HistoryResponse>(`/api/history?limit=${limit}`),

  meta: () => request<MetaResponse>('/api/meta'),

  credentials: (probe = true) =>
    request<CredentialReport>(`/api/credentials${probe ? '' : '?probe=0'}`),

  config: () => request<ConfigView>('/api/config'),

  saveConfig: (payload: Record<string, unknown>) =>
    request<SaveConfigResponse>('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  startReviewJob: (prUrl: string) =>
    request<JobSnapshot>('/api/review', {
      method: 'POST',
      body: JSON.stringify({ pr_url: prUrl, async_job: true }),
    }),

  job: (jobId: string) => request<JobSnapshot>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    request<{ ok: boolean; message: string }>(`/api/jobs/${jobId}/cancel`, {
      method: 'POST',
      body: '{}',
    }),

  report: (runId: string) =>
    request<ReportResponse>(`/api/report?run_id=${encodeURIComponent(runId)}`),

  /**
   * 发布审查评论。`confirm=false` 只拿预览，服务端保证不向 GitHub 写任何内容；
   * 只有 `confirm=true` 才会真的发帖，所以调用点必须由「二次确认」驱动。
   */
  publish: (runId: string, confirm: boolean) =>
    request<PublishResponse>('/api/publish', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, confirm }),
    }),

  /**
   * 导出走浏览器原生下载（服务端返回 text/markdown 或 json 的附件响应），
   * 因此只给 URL 给 <a download> 用，不经过 request() 的 JSON 解析通道。
   */
  exportReportUrl: (runId: string, format: ReportExportFormat) =>
    `/api/report/export?run_id=${encodeURIComponent(runId)}&format=${format}`,

  feedback: (runId: string, findingId: string, status: FeedbackStatus, note = '') =>
    request<{ ok: boolean }>('/api/feedback', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, finding_id: findingId, status, note }),
    }),

  benchmark: (strategy: string) =>
    request<BenchmarkReport | Record<string, BenchmarkReport>>(
      `/api/benchmark?strategy=${encodeURIComponent(strategy)}`,
    ),
}
