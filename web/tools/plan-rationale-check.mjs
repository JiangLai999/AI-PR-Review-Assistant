/**
 * 「规划依据」渲染时本地化 自测（Node 24 类型剥离直接 import .ts，不需要测试框架）。
 *
 * 跑法：`node tools/plan-rationale-check.mjs`（在 web/ 下）。
 *
 * 重点验的是**老 run**：库里冻结的是改动前的英文模板（"… included file set."、
 * "Detected risk categories: …"、"… interface-sensitive terms …"），中文界面必须也能
 * 显示中文。认不出来的行必须返回 null（调用方原样显示），绝不吞内容。
 */
import { localizeRationale } from '../src/components/planRationale.ts'

/**
 * 模板来自"词典"（这里用替身）。**两种语言的写法都要给**，才能验证
 * 「英文冻结的老 run 在中文界面也被认出来」以及反向（中文冻结 → 英文界面）。
 */
const templates = {
  scope: [
    '审查范围由 PR 元数据与纳入审查的文件集推导得出。',
    'Review scope is derived from the PR metadata and the included file set.',
  ],
  crossFile: [
    '涉及多个文件或接口敏感改动，需要做一次跨文件复核。',
    'Multiple files or interface-sensitive changes require a cross-file pass.',
  ],
  defaultIntent: [
    '审查该 PR 的正确性与安全风险。',
    'Review the pull request for correctness and security risks.',
  ],
}

/** 自测用的类别词典：unknown id 原样回退（与前端 idText 的契约一致）。 */
const labels = {
  security: '安全',
  resource: '资源',
  concurrency: '并发',
  correctness: '正确性',
  performance: '性能',
  error_handling: '错误处理',
}
const categoryLabel = (id) => labels[id] ?? id
const localize = (line, separator) => localizeRationale(line, templates, categoryLabel, separator)

let passed = 0
const failures = []
function check(label, ok, detail = '') {
  if (ok) {
    passed += 1
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` :: ${detail}` : ''}`)
  }
}

// ------------------------------------------------- legacy 三条（库里真实存在的）
{
  const scope = localize('Review scope is derived from the PR metadata and included file set.')
  check('legacy 范围句 → scope key', scope?.key === 'panels.plan.rationale.scope', JSON.stringify(scope))

  const cross = localize(
    'Multiple files or interface-sensitive terms require a cross-file pass.',
  )
  check(
    'legacy 跨文件句 → crossFile key',
    cross?.key === 'panels.plan.rationale.crossFile',
    JSON.stringify(cross),
  )

  const categories = localize('Detected risk categories: correctness.')
  check('legacy 类别句 → categories key', categories?.key === 'panels.plan.rationale.categories')
  check(
    'legacy 类别句：id 走注入的词典',
    categories?.params?.categories === '正确性',
    JSON.stringify(categories?.params),
  )

  const multi = localize(
    'Detected risk categories: security, resource, error_handling.',
    '、',
  )
  check(
    'legacy 类别句：多 id + 中文分隔符',
    multi?.params?.categories === '安全、资源、错误处理',
    JSON.stringify(multi?.params),
  )

  const unknownId = localize('Detected risk categories: made_up_id.')
  check(
    '未知类别 id 原样回退',
    unknownId?.params?.categories === 'made_up_id',
    JSON.stringify(unknownId?.params),
  )
}

// ------------------------------------------------------- 新模板（中英双向）
{
  const enScope = localize(
    'Review scope is derived from the PR metadata and the included file set.',
  )
  check('新英文范围句 → scope key', enScope?.key === 'panels.plan.rationale.scope')

  const zhScope = localize('审查范围由 PR 元数据与纳入审查的文件集推导得出。')
  check('中文范围句 → scope key（切到英文界面也能映射）', zhScope?.key === 'panels.plan.rationale.scope')

  const enCross = localize(
    'Multiple files or interface-sensitive changes require a cross-file pass.',
  )
  check('新英文跨文件句 → crossFile key', enCross?.key === 'panels.plan.rationale.crossFile')

  const zhCross = localize('涉及多个文件或接口敏感改动，需要做一次跨文件复核。')
  check('中文跨文件句 → crossFile key', zhCross?.key === 'panels.plan.rationale.crossFile')
}

// ---------------------------------------------------------------- 默认意图
{
  check(
    'legacy 默认意图 → panels.intent.default',
    localize('Review the pull request for correctness and security risks.')?.key ===
      'panels.intent.default',
  )
  check(
    '中文默认意图 → panels.intent.default',
    localize('审查该 PR 的正确性与安全风险。')?.key === 'panels.intent.default',
  )
}

// ---------------------------------------------------------------- 形状与兜底
{
  check('空串 → null', localize('') === null)
  check('纯空白 → null', localize('   \n  ') === null)
  check(
    '真实 PR 标题（用户内容）→ null，绝不改写',
    localize('refactor: modularize workspace flows') === null,
  )
  check('随意句子 → null', localize('因为这次改动动了认证链路，所以需要跨文件复核。') === null)
  check(
    '大小写/多余空白不影响匹配',
    localize('  review   scope IS derived from the pr metadata and included file set.  ')?.key ===
      'panels.plan.rationale.scope',
  )
  check('类别句缺 id → null（不产出空列表）', localize('Detected risk categories: .') === null)
  check('类别句含非法 id 形状 → null', localize('Detected risk categories: foo bar.') === null)
  check(
    '模板为空时也不崩（词典缺条目）',
    localizeRationale('Review scope is derived from the PR metadata and included file set.', {
      scope: [],
      crossFile: [],
      defaultIntent: [],
    }, categoryLabel)?.key === 'panels.plan.rationale.scope',
  )
}

console.log(
  failures.length === 0 ? `\n${passed} passed, 0 failed\nALL PASS` : `\nFAILURES: ${failures.length}`,
)
process.exitCode = failures.length === 0 ? 0 : 1
