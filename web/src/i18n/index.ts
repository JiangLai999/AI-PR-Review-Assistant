/**
 * 轻量 i18n 运行时（Phase 3b）。
 *
 * 设计要点：
 * - **语言来源**：`GET /api/config` 的 `preferences.ui_language`（Phase 2 起设置页可改），
 *   App 启动时 `setLang(...)`，设置页保存成功后再次 `setLang(...)` → 全站即时切换。
 * - **组件内**：`const t = useT()`；**非组件代码**：直接 `t(...)`（读当前语言，不订阅）。
 * - **插值**：词典里写 `{name}`，调用 `t('key', { name: 'x' })`。
 * - **复数**：`tn('key', count)` 自动取 `key.one` / `key.other`（中英都适用）。
 * - 词典按**命名空间拆文件**（shell/overview/settings/review），供多个 agent 并行填充而不冲突。
 */
import { useSyncExternalStore } from 'react'
import { shell, type Dict, type Namespace } from './shell'
import { overview } from './overview'
import { settings } from './settings'
import { review } from './review'
import { components } from './components'

export type Lang = 'zh-CN' | 'en-US'
export type { Dict, Namespace }

const NAMESPACES: Namespace[] = [shell, overview, settings, review, components]

const MERGED: Record<Lang, Dict> = (() => {
  const merged: Record<Lang, Dict> = { 'zh-CN': {}, 'en-US': {} }
  for (const namespace of NAMESPACES) {
    for (const lang of ['zh-CN', 'en-US'] as const) {
      for (const [key, value] of Object.entries(namespace[lang])) {
        if (import.meta.env.DEV && key in merged[lang]) {
          // 重复 key 会静默覆盖，开发期直接吵出来（生产构建不引入这段）
          console.warn(`[i18n] duplicate key across namespaces: ${key}`)
        }
        merged[lang][key] = value
      }
    }
  }
  return merged
})()

const listeners = new Set<() => void>()
let current: Lang = 'zh-CN'

/** 把任意后端取值归一成受支持语言（不认识的一律中文，与后端默认一致）。 */
export function normalizeLang(value: unknown): Lang {
  return String(value ?? '')
    .toLowerCase()
    .startsWith('en')
    ? 'en-US'
    : 'zh-CN'
}

export function getLang(): Lang {
  return current
}

/** 切换语言：更新 `<html lang>` 并通知订阅者（组件即时重渲染）。 */
export function setLang(value: unknown): void {
  const next = normalizeLang(value)
  if (next === current) return
  current = next
  if (typeof document !== 'undefined') document.documentElement.lang = next
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  )
}

/** 取词：当前语言缺失时回落中文，再缺失就原样返回 key（便于一眼看出漏翻）。 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const template = MERGED[current][key] ?? MERGED['zh-CN'][key] ?? key
  return interpolate(template, vars)
}

/** 复数取词：`key.one` / `key.other`（英文 1 用 one，其余用 other；中文两条通常同文案）。 */
export function tn(key: string, count: number, vars?: Record<string, string | number>): string {
  return t(`${key}.${count === 1 ? 'one' : 'other'}`, { count, ...vars })
}

/** 组件内取 `t`：语言变化时触发重渲染。 */
export function useT(): typeof t {
  useSyncExternalStore(subscribe, getLang, getLang)
  return t
}

/** 仅供测试/审计：列出当前语言的全部 key。 */
export function dictKeys(lang: Lang = current): string[] {
  return Object.keys(MERGED[lang]).sort()
}
