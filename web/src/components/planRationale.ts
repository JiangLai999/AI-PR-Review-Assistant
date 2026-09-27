/**
 * 「规划依据」的**渲染时**本地化。
 *
 * 背景：规划依据是 `services/agent/planner.py` 确定性生成的句子，随 run 落库。
 * 后端从 2026-09-27 起按 `preferences.ui_language` 生成中英两版，但**老 run 里
 * 冻结的是当时的英文**（"Review scope is derived from the PR metadata and included
 * file set." / "Detected risk categories: …" / "… interface-sensitive terms …"），
 * 历史不可回溯翻译 —— 于是中文界面打开老 run 会看到英文。
 *
 * 这些句子全部由我们自己的代码产出、模板固定，所以前端可以做一次**语义映射**：
 * 认识 legacy 英文与新中英两版，统一渲染成**当前界面语言**。映射不上的一律返回
 * `null`（由调用方原样显示），绝不吞内容、也绝不猜。
 *
 * 纯函数、无 React 依赖：Node 24 的类型剥离可以直接 import 它做自测
 * （见 `web/tools/plan-rationale-check.mjs`）。
 */

export interface RationaleText {
  /** i18n key（词条在 `web/src/i18n/components.ts` 的 `panels.plan.rationale.*`）。 */
  key: string
  /** `{categories}` 这类插值参数。 */
  params?: Record<string, string>
}

export const SCOPE_KEY = 'panels.plan.rationale.scope'
export const CROSS_FILE_KEY = 'panels.plan.rationale.crossFile'
export const CATEGORIES_KEY = 'panels.plan.rationale.categories'
export const DEFAULT_INTENT_KEY = 'panels.intent.default'

/**
 * 认句子用的模板集合，**由调用方从词典取**（见 `ReviewPanels.planRationaleTemplates`）。
 *
 * 刻意不在这里写死中英句子：那等于在组件代码里再存一份文案 —— 既会打破 i18n 审计
 * （组件里不得有中文），也会跟词典慢慢对不上。这里只做"字符串比对"，不管文案内容。
 */
export interface RationaleTemplates {
  /** 各语言下「范围」那句的写法（跨语言识别用）。 */
  scope: string[]
  crossFile: string[]
  defaultIntent: string[]
}

/** 归一化：裁空白、折叠内部空白、转小写（中文不受影响）。 */
function normalize(line: string): string {
  return line.trim().replace(/\s+/g, ' ').toLowerCase()
}

/**
 * 改动前**已经冻结进库**的英文写法。
 *
 * 不进词典：这些句子后端已经不再生成，词典里放它们只会变成"永远不会用到的词条"；
 * 它们是纯 ASCII，也不会打破"组件里不得有中文"的审计。等老 run 都过期就可以删。
 */
const LEGACY_FORMS: Record<'scope' | 'crossFile', string> = {
  scope: 'Review scope is derived from the PR metadata and included file set.',
  crossFile: 'Multiple files or interface-sensitive terms require a cross-file pass.',
}

/**
 * legacy 那行的形状：`Detected risk categories: correctness, resource.`
 *
 * 只接受规范 id 的形状（`[a-z0-9_]`、逗号分隔）—— 用 `.+?` 会把
 * `Detected risk categories: .`（缺 id 的脏数据）也当成有效内容，
 * 于是在界面上渲染出「检测到风险类别：.」。
 */
const LEGACY_CATEGORIES =
  /^detected risk categories:\s*([a-z0-9_]+(?:\s*,\s*[a-z0-9_]+)*)\s*[.。]?$/

/**
 * 把一行规划依据（或计划意图的默认句）映射成词典 key；认不出来返回 null。
 *
 * `categoryLabel` 由调用方注入：类别 id → 当前语言文案（复用计划卡 chips 的同一套
 * id 映射，避免再存一份词汇表）。
 */
export function localizeRationale(
  line: string,
  templates: RationaleTemplates,
  categoryLabel: (id: string) => string,
  categorySeparator = ', ',
): RationaleText | null {
  const normalized = normalize(line)
  if (!normalized) return null
  if (matches([...templates.scope, LEGACY_FORMS.scope], normalized)) return { key: SCOPE_KEY }
  if (matches([...templates.crossFile, LEGACY_FORMS.crossFile], normalized)) {
    return { key: CROSS_FILE_KEY }
  }
  if (matches(templates.defaultIntent, normalized)) return { key: DEFAULT_INTENT_KEY }

  const categories = LEGACY_CATEGORIES.exec(normalized)
  if (categories) {
    const ids = categories[1].split(',').map((id) => id.trim())
    return {
      key: CATEGORIES_KEY,
      params: { categories: ids.map(categoryLabel).join(categorySeparator) },
    }
  }
  return null
}

/** 归一化后与任一语言的写法相同即命中。 */
function matches(forms: string[], normalized: string): boolean {
  return forms.some((form) => normalize(form) === normalized)
}
