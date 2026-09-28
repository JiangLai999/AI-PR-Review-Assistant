import type {
  BenchmarkReport,
  ChatHistoryResponse,
  ChatResponse,
  ClearChatHistoryResponse,
  DemoCasesResponse,
  DemoResult,
  ConfigView,
  CredentialReport,
  FeedbackStatus,
  HistoryResponse,
  ImportCliConfigResponse,
  JobSnapshot,
  MetaResponse,
  PublishResponse,
  ReportExportFormat,
  ReportResponse,
  ReviewResponse,
  SaveConfigResponse,
} from './types'
import { t } from '../i18n'

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
      t('api.error.offline', {
        detail: error instanceof Error ? error.message : String(error),
      }),
      0,
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError(
        t('api.error.nonJson', { detail: text.slice(0, 200) }),
        response.status,
      )
    }
  }

  if (!response.ok) {
    // 后端两种失败形状都要认：`/api/publish` 用 `{error, code}`，
    // `/api/config` 的 `ok=false` 用 `{ok:false, message}`——只读 `error` 会把
    // 设置页的 400 原因吞成 "HTTP 400"（claude 复核时指出）。
    const detail =
      payload && typeof payload === 'object'
        ? ((payload as { error?: unknown; message?: unknown }).error ??
          (payload as { message?: unknown }).message)
        : undefined
    const message = detail === undefined || detail === null || detail === ''
      ? t('api.error.http', { status: response.status })
      : String(detail)
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

  /**
   * 把 CLI 侧**实际生效**的合并结果导入 Web 这份配置（`POST /api/config/import-cli`）。
   *
   * 覆盖动作：调用点必须先做二次确认，缺 `confirm: true` 服务端回 400。
   * 404 = 没有可导入的来源（CLI 侧没有配置文件，或 Web 配置名反推不出 CLI 路径），
   * 响应体的 `error` 可直接展示；`request()` 已在非 2xx 时读它。
   */
  importCliConfig: (confirm: boolean) =>
    request<ImportCliConfigResponse>('/api/config/import-cli', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
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

  /**
   * 对某次审查追问（Phase 3）。带 `runId` 时服务端把该 run 的报告摘成上下文；
   * 不带时是普通对话 —— 此时 body 里连 `run_id` 键都不出现，服务端按无绑定处理。
   *
   * 失败形状：400 缺 text / 404 run 查不到 / 415 跨站守卫 / 502 模型调用失败 /
   * 503 未配置 API Key，都以 `ApiError.status` 抛给调用方（映射见 AskPanel）。
   */
  chat: (runId: string | null | undefined, text: string) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(runId ? { run_id: runId, text } : { text }),
    }),

  /**
   * 读取某次审查的追问历史。未知 run → 404；缺 run_id → 400；
   * `limit` 超出 1–1000 也返回 400（省略时走服务端默认 200）。
   */
  chatHistory: (runId: string, limit?: number) =>
    request<ChatHistoryResponse>(
      `/api/chat/history?run_id=${encodeURIComponent(runId)}` +
        (limit === undefined ? '' : `&limit=${limit}`),
    ),

  /** 清空某次审查的追问历史。幂等：没有记录时 `deleted: 0`。 */
  clearChatHistory: (runId: string) =>
    request<ClearChatHistoryResponse>('/api/chat/history/clear', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId }),
    }),

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
