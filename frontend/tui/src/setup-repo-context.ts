/**
 * 配置助手第 5 阶段的「仓库上下文」（`repo_context`）三选一
 * （docs/repo-aware-review-plan.md §4.6；协议见 docs/claude-repo-config.md §1/§2）。
 *
 * 三个约定，与 `setup-routing.ts` 同源：
 *
 *   1. **取值清单的 owner 是后端**：`config.options.repo_context.options` 给什么就渲染什么
 *      （`REPO_CONTEXT_MODES`，config.py:629），前端不硬编码 `off | tests | tests+imports`。
 *      下面的 `FALLBACK_REPO_CONTEXT_OPTIONS` 只在旧后端 / options 读取失败时兜住这一屏，
 *      与 `fallbackRuntimeProfiles` 同一惯例。
 *   2. **标签中英双语**：后端 label 是 `中文 / English` 双语串（`REPO_CONTEXT_LABELS`，
 *      jsonl_server.py:127），这里按 `ui_language` 取其中一侧——路由细化页也是这么做的，
 *      否则 en-US 的助手里会混进中文选项。
 *   3. **推荐档 = 默认档 = `tests+imports`**（`config.DEFAULT_REPO_CONTEXT`）。后端快照里
 *      的当前值缺失 / 不在清单里时，预选回落到推荐档，而不是清单第一项（`off`）——用户
 *      在助手里看到的默认值必须与后端 `DEFAULT_REPO_CONTEXT` 一致。
 */

export type RepoContextOption = {
  value: string
  label: string
}

/** `config.options.repo_context` / `model.status.repo_context` 的形状。 */
export type RepoContextOptions = {
  value?: string
  options?: RepoContextOption[]
}

/** 推荐档：`config.DEFAULT_REPO_CONTEXT` 的字面量（后端是 owner）。 */
export const RECOMMENDED_REPO_CONTEXT = "tests+imports"

/**
 * 后端 `REPO_CONTEXT_MODES` 的兜底副本（含与 `REPO_CONTEXT_LABELS` 逐字一致的 label）。
 *
 * 仅用于 `config.options` 缺这一块时（旧后端）不让这一屏空掉；正常情况下永远以后端为准。
 */
export const FALLBACK_REPO_CONTEXT_OPTIONS: RepoContextOption[] = [
  { value: "off", label: "关闭 / Off" },
  { value: "tests", label: "仅测试文件 / Tests only" },
  { value: "tests+imports", label: "测试与依赖 / Tests + imports" },
]

/** 每档的说明（后端 `options[].label` 只有名字，描述由前端补，同 `PRESET_DESCRIPTIONS`）。 */
const REPO_CONTEXT_NOTES: Record<string, { zh: string; en: string }> = {
  off: {
    zh: "不读取任何仓库文件，零额外请求（行为与改造前一致）",
    en: "no repository files are read, zero extra requests",
  },
  tests: {
    zh: "只带进该 PR 的测试文件",
    en: "only the test files touched by this PR",
  },
  "tests+imports": {
    zh: "测试文件 + 它们导入的模块（推荐）",
    // 描述在 74 列对话框里只有 ~65 列可用（select 内缩进 3 列），超宽会换行顶掉布局。
    en: "test files + their imports (recommended)",
  },
}

const isEnglish = (language?: string): boolean =>
  String(language ?? "zh-CN").toLowerCase().startsWith("en")

/**
 * 后端双语 label 取一侧：`"测试与依赖 / Tests + imports"` → `测试与依赖` / `Tests + imports`。
 *
 * 没有分隔符（后端将来只给单语 label）时原样返回，绝不拼出空串——label 的 owner 是后端。
 */
export function bilingualLabel(label: string, language?: string): string {
  const parts = String(label ?? "").split(" / ")
  if (parts.length < 2) return String(label ?? "")
  return (isEnglish(language) ? parts[parts.length - 1] : parts[0]).trim()
}

/**
 * 快照侧当前值的归一化。
 *
 * 同名键在后端有两种形状（刻意，见 docs/claude-repo-config.md §6.2）：
 * `config.snapshot.repo_context` 是纯字符串，`model.status.repo_context` 是
 * `{value, options}`。而 App 会把 `model.status` 的结果并进同一个 `RuntimeSnapshot`
 * （`app.tsx` 的 `onApplied` 分支），所以 `runtime.repo_context` 两种形状都可能出现——
 * 这里统一收敛成字符串，认不出来就返回空串（预选随后回落到推荐档）。
 */
export function repoContextStoredValue(source: unknown): string {
  if (typeof source === "string") return source
  if (source && typeof source === "object") {
    const value = (source as RepoContextOptions).value
    return typeof value === "string" ? value : ""
  }
  return ""
}

/** 这一屏要渲染的选项清单：后端优先，缺了才用兜底表。 */
export function repoContextChoices(source?: RepoContextOptions): RepoContextOption[] {
  const fromBackend = source?.options ?? []
  return fromBackend.length > 0 ? fromBackend : FALLBACK_REPO_CONTEXT_OPTIONS
}

/** 选项显示名（按 `ui_language` 单语）。 */
export function repoContextLabel(option: RepoContextOption, language?: string): string {
  return bilingualLabel(option.label, language)
}

/** 选项说明：`值 · 说明`，未知档位只留值，绝不编造文案。 */
export function repoContextDescription(option: RepoContextOption, language?: string): string {
  const note = REPO_CONTEXT_NOTES[option.value]
  if (!note) return option.value
  return `${option.value} · ${isEnglish(language) ? note.en : note.zh}`
}

/**
 * 预选序号：精确匹配 → 推荐档 → 第一项，绝不越界。
 *
 * 后端当前值不在清单里（旧配置 / 未来档位）时选推荐档：它与后端
 * `DEFAULT_REPO_CONTEXT` 一致，用户不动这一屏就等于提交推荐档。
 */
export function repoContextIndexOf(list: readonly RepoContextOption[], value?: string): number {
  const exact = list.findIndex((option) => option.value === String(value ?? ""))
  if (exact >= 0) return exact
  const recommended = list.findIndex((option) => option.value === RECOMMENDED_REPO_CONTEXT)
  return recommended >= 0 ? recommended : 0
}

/** 选中项的取值；清单为空时回落到推荐档（不可能发生，但不返回空串）。 */
export function repoContextValue(
  list: readonly RepoContextOption[],
  index: number,
): string {
  const bounded = Math.min(Math.max(index, 0), Math.max(0, list.length - 1))
  return list[bounded]?.value ?? RECOMMENDED_REPO_CONTEXT
}

/** 确认页那一行的显示值：清单里的双语 label，不在清单里就退回该值本身。 */
export function repoContextSummary(
  list: readonly RepoContextOption[],
  value: string,
  language?: string,
): string {
  const option = list.find((item) => item.value === value)
  if (option) return repoContextLabel(option, language)
  const fallback = FALLBACK_REPO_CONTEXT_OPTIONS.find((item) => item.value === value)
  return fallback ? repoContextLabel(fallback, language) : value
}

/**
 * `config.setup` 载荷里的 `repo_context`。
 *
 * 永远**显式**发送用户在助手里看到的档位（与 `ui_language` / `output_format` /
 * `workbench_mode` 一致），不做"等于默认值就不发送"的特例：后端把字段缺失当"保持不变"
 * 的部分更新（jsonl_server.py:893），显式发送等于"保存屏幕上这一项"。因此**未改动**时
 * 载荷里的值 = 后端当前值，全新配置的当前值就是 `tests+imports`（推荐档）。
 *
 * 空串（清单为空且没有兜底时才会发生）返回空对象 = 不发送，把语义交回后端的"保持不变"。
 */
export function setupRepoContextField(value: string): Record<string, string> {
  const normalized = String(value ?? "").trim().toLowerCase()
  return normalized ? { repo_context: normalized } : {}
}
