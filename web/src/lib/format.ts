/** 展示层格式化工具。 */

import { t } from '../i18n'

export function formatDuration(seconds?: number): string {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(2)} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

export function formatCost(value?: number): string {
  if (value === undefined || value === null) return '—'
  if (value === 0) return '$0'
  if (value < 0.0001) return `$${value.toExponential(2)}`
  return `$${value.toFixed(4)}`
}

export function formatNumber(value?: number | string): string {
  if (value === undefined || value === null || value === '') return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return String(value)
  return n.toLocaleString('zh-CN')
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

/** 把 ISO 或 "YYYY-MM-DD HH:MM:SS" 时间统一成可读形式。 */
export function formatTime(value?: string): string {
  if (!value) return '—'
  const normalized = value.includes('T') ? value : value.replace(' ', 'T') + 'Z'
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

export function repoLabel(run: {
  repo_owner?: string
  repo_name?: string
  pr_number?: number
}): string {
  const repo = [run.repo_owner, run.repo_name].filter(Boolean).join('/')
  if (!repo) return '—'
  return run.pr_number ? `${repo}#${run.pr_number}` : repo
}

/** 校验输入是否像 GitHub PR URL，用于给出即时反馈。 */
export function parsePrUrl(value: string): { ok: boolean; hint?: string } {
  const trimmed = value.trim()
  if (!trimmed) return { ok: false, hint: t('url.required') }
  if (!/^https?:\/\//i.test(trimmed)) {
    return { ok: false, hint: t('url.scheme') }
  }
  if (!/^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+\/pull\/\d+/i.test(trimmed)) {
    return { ok: false, hint: t('url.shape') }
  }
  return { ok: true }
}
