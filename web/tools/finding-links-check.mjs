/**
 * findingLinks 自测（Node 24 靠类型剥离直接 import .ts，不需要测试框架）。
 *
 * 跑法：`node tools/finding-links-check.mjs`（在 web/ 下）。
 *
 * 覆盖四件事：
 * 1) **sha256**：与 node:crypto 逐条对齐，且含一条**真机验证过**的常量
 *    （`docs/PR_WORKFLOW.md` 在真实 GitHub PR 页面里的 diff 锚哈希，4/4 复现）；
 * 2) **diff 行锚**：URL 形状、行号优先 line_end、任一字段缺失/不可信一律 null；
 * 3) **路径哈希缓存**：同一路径只算一次、失败不钉死、并发共享同一次计算；
 * 4) **blob 行锚回归**：现有「文件:行」链接的拼法与降级条件不被本轮改动破坏。
 *
 * 断言里出现的哈希值都是**外部常量**（node:crypto 或真机 URL），不是被测实现的输出，
 * 否则这工具只能证明"它等于它自己"。
 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  blobUrl,
  createPathHasher,
  diffAnchorUrl,
  diffUrl,
  repoRoot,
  sha256Hex,
} from '../src/components/findingLinks.ts'

const failures = []
let passed = 0

function check(label, ok, detail = '') {
  if (ok) {
    passed += 1
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` :: ${detail}` : ''}`)
  }
}

const nodeSha = (text) => createHash('sha256').update(text, 'utf8').digest('hex')

/** 真机验证过的常量：docs/PR_WORKFLOW.md → GitHub PR Files changed 锚里的哈希。 */
const PR_WORKFLOW_HASH = 'c167cbdb90bd7a66140839bc0fc33468e4efba7349a786f703aabc22d0e99b80'
/** 空串的 sha256（公开常量）。 */
const EMPTY_HASH = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'

const PR_URL = 'https://github.com/owner/repo/pull/12'

console.log('--- 1. sha256（路径哈希） ---')
{
  check(
    'sha256：真机常量 docs/PR_WORKFLOW.md',
    (await sha256Hex('docs/PR_WORKFLOW.md')) === PR_WORKFLOW_HASH,
    await sha256Hex('docs/PR_WORKFLOW.md'),
  )
  check('sha256：空串 = 公开常量', (await sha256Hex('')) === EMPTY_HASH, await sha256Hex(''))

  // 与 node:crypto 对拍：含空格、中文路径、大小写敏感的路径。
  const paths = ['src/a b.ts', '路径/中文 文件.ts', 'docs/PR_WORKFLOW.md', 'A/B.TS', 'a/b.ts']
  for (const path of paths) {
    const mine = await sha256Hex(path)
    check(`sha256：与 node:crypto 一致 ${JSON.stringify(path)}`, mine === nodeSha(path), `${mine} vs ${nodeSha(path)}`)
  }
  check(
    'sha256：路径大小写敏感（a/b.ts ≠ A/B.TS）',
    (await sha256Hex('a/b.ts')) !== (await sha256Hex('A/B.TS')),
  )
  check(
    'sha256：是 64 位小写十六进制',
    /^[0-9a-f]{64}$/.test((await sha256Hex('x')) ?? ''),
  )
}

console.log('\n--- 2. diff 行锚 URL ---')
{
  const expected = `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R42`
  check(
    'diff：完整形状（真机哈希 + 单行）',
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH, 'docs/PR_WORKFLOW.md', 42, 42) === expected,
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH, 'docs/PR_WORKFLOW.md', 42, 42),
  )
  check(
    'diff：行号优先 line_end（9 > 3 → R9）',
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH, 'docs/PR_WORKFLOW.md', 3, 9) ===
      `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R9`,
  )
  check(
    'diff：line_end 缺失 → R<line_start>',
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH, 'docs/PR_WORKFLOW.md', 7, undefined) ===
      `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R7`,
  )
  check(
    'diff：line_end 小于 line_start → 回退 R<line_start>',
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH, 'docs/PR_WORKFLOW.md', 7, 2) ===
      `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R7`,
  )
  check(
    'diff：大写哈希归一成小写（GitHub 锚是小写）',
    diffUrl(PR_URL, 12, PR_WORKFLOW_HASH.toUpperCase(), 'docs/PR_WORKFLOW.md', 1, 1) ===
      `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R1`,
  )
  check(
    'diff：哈希覆盖**原始路径**，URL 里不出现路径（中文/空格不进 URL）',
    !diffUrl(PR_URL, 12, nodeSha('路径/中文 文件.ts'), '路径/中文 文件.ts', 5, 5).includes('%'),
  )

  const nullCases = [
    ['prUrl 缺失', [undefined, 12, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['prUrl 不是 PR 链接', ['https://github.com/owner/repo', 12, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['prNumber 缺失', [PR_URL, undefined, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['prNumber 为 0', [PR_URL, 0, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['prNumber 为负', [PR_URL, -3, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['prNumber 非整数', [PR_URL, 12.5, PR_WORKFLOW_HASH, 'a.ts', 1, 1]],
    ['路径为空', [PR_URL, 12, PR_WORKFLOW_HASH, '', 1, 1]],
    ['路径只有空白', [PR_URL, 12, PR_WORKFLOW_HASH, '   ', 1, 1]],
    ['哈希缺失', [PR_URL, 12, null, 'a.ts', 1, 1]],
    ['哈希不是 sha256（长度不对）', [PR_URL, 12, 'abc123', 'a.ts', 1, 1]],
    ['哈希非十六进制', [PR_URL, 12, 'z'.repeat(64), 'a.ts', 1, 1]],
    ['行号缺失', [PR_URL, 12, PR_WORKFLOW_HASH, 'a.ts', undefined, undefined]],
    ['行号为 0', [PR_URL, 12, PR_WORKFLOW_HASH, 'a.ts', 0, 0]],
    ['行号为负', [PR_URL, 12, PR_WORKFLOW_HASH, 'a.ts', -4, -1]],
  ]
  for (const [label, args] of nullCases) {
    check(`diff：${label} → null`, diffUrl(...args) === null, String(diffUrl(...args)))
  }
}

console.log('\n--- 3. diffAnchorUrl（一步到位 + 缓存） ---')
{
  const url = await diffAnchorUrl(PR_URL, 12, 'docs/PR_WORKFLOW.md', 3, 9)
  check(
    'diffAnchorUrl：端到端等于真机锚',
    url === `${PR_URL}/files#diff-${PR_WORKFLOW_HASH}R9`,
    url,
  )
  check(
    'diffAnchorUrl：prNumber 缺失 → null（哈希算得出来也不给链接）',
    (await diffAnchorUrl(PR_URL, undefined, 'docs/PR_WORKFLOW.md', 3, 9)) === null,
  )
  check(
    'diffAnchorUrl：空路径不触发哈希计算',
    (await diffAnchorUrl(PR_URL, 12, '   ', 3, 9, () => Promise.reject(new Error('不该被调用')))) === null,
  )

  let calls = 0
  const counting = createPathHasher((file) => {
    calls += 1
    return Promise.resolve(nodeSha(file))
  })
  const [first, second] = await Promise.all([counting('src/a.ts'), counting('src/a.ts')])
  await counting('src/a.ts')
  check(
    '缓存：同一路径并发 3 次只算 1 次',
    calls === 1 && first === nodeSha('src/a.ts') && first === second,
    `calls=${calls}`,
  )

  let attempts = 0
  const flaky = createPathHasher(() => {
    attempts += 1
    return Promise.resolve(attempts === 1 ? null : nodeSha('p'))
  })
  const bad = await flaky('p')
  const good = await flaky('p')
  check(
    '缓存：失败结果不钉死（第二次重算并拿到哈希）',
    bad === null && good === nodeSha('p') && attempts === 2,
    `attempts=${attempts}`,
  )

  let okCalls = 0
  const cachedOk = createPathHasher(() => {
    okCalls += 1
    return Promise.resolve(PR_WORKFLOW_HASH)
  })
  await cachedOk('p')
  await cachedOk('q')
  await cachedOk('p')
  check('缓存：按路径分别记忆（p 算 1 次、q 算 1 次，共 2 次）', okCalls === 2, `calls=${okCalls}`)
}

console.log('\n--- 4. blob 行锚（回归） ---')
{
  const sha = 'a'.repeat(40)
  check(
    'blob：区间 → #L3-L9',
    blobUrl(PR_URL, sha, 'docs/PR_WORKFLOW.md', 3, 9) ===
      `https://github.com/owner/repo/blob/${sha}/docs/PR_WORKFLOW.md#L3-L9`,
    blobUrl(PR_URL, sha, 'docs/PR_WORKFLOW.md', 3, 9),
  )
  check(
    'blob：单行 → #L3',
    blobUrl(PR_URL, sha, 'docs/PR_WORKFLOW.md', 3, 3) ===
      `https://github.com/owner/repo/blob/${sha}/docs/PR_WORKFLOW.md#L3`,
  )
  check(
    'blob：路径按段编码（空格 → %20，斜杠保留）',
    blobUrl(PR_URL, sha, 'docs/a b.md', 1, 1)?.endsWith('/blob/' + sha + '/docs/a%20b.md#L1') === true,
    blobUrl(PR_URL, sha, 'docs/a b.md', 1, 1),
  )
  check(
    'blob：SHA 归一成小写',
    blobUrl(PR_URL, 'ABCDEF1', 'a.ts', 1, 1)?.includes('/blob/abcdef1/') === true,
  )
  check(
    'blob：缺 head_sha → null',
    blobUrl(PR_URL, undefined, 'a.ts', 1, 1) === null &&
      blobUrl(PR_URL, 'unknown', 'a.ts', 1, 1) === null,
  )
  check('blob：行号非正 → null', blobUrl(PR_URL, sha, 'a.ts', 0, 0) === null)
  check('repoRoot：解析 owner/repo', repoRoot(PR_URL) === 'https://github.com/owner/repo')
  check(
    'repoRoot：不是 PR 链接 → null',
    repoRoot('https://github.com/owner/repo') === null &&
      repoRoot('https://github.com/owner/repo/issues/12') === null &&
      repoRoot(undefined) === null,
  )
}

console.log('\n--- 5. 浏览器安全（不引 node 内建） ---')
{
  const source = readFileSync(fileURLToPath(new URL('../src/components/findingLinks.ts', import.meta.url)), 'utf8')
  check(
    '源码不 import node:*（组件与自测共用同一份实现）',
    !/from\s+'node:/.test(source) && !/require\(/.test(source),
  )
  // 注释里可以提 node:crypto（说明"为什么不用它"），代码里不行 → 先剥注释再断言。
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '')
  check(
    '源码只用 crypto.subtle（剥掉注释后不出现 node:）',
    code.includes('globalThis.crypto') && !code.includes('node:'),
  )
}

console.log(`\n${passed} passed, ${failures.length} failed`)
if (failures.length === 0) {
  console.log('ALL PASS')
} else {
  console.log(`FAILURES: ${failures.join(' | ')}`)
  process.exitCode = 1
}
