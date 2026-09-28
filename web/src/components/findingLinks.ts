/**
 * GitHub 链接构造：blob 行锚 + PR「Files changed」diff 行锚。
 *
 * 纯函数 + `crypto.subtle`（浏览器与 Node 18+ 都内置的 WebCrypto），**不引 node:crypto**：
 * 同一份代码既给组件用，也能被 `web/tools/finding-links-check.mjs` 用 Node 的类型剥离
 * 直接 import 跑断言。本文件不能有 JSX / enum（理由同 markdownLite.ts）。
 *
 * 全局约定：**要么给出完整链接、要么 null**。半个链接比没有链接更糟 —— 点了 404 还
 * 不知道是页面错了还是行号错了。所以任何一处入参缺失/不可信都返回 null，由调用方降级
 * （降级方式见 FindingCard：位置退回纯文本 chip，diff 动作干脆不渲染）。
 */

/** GitHub commit SHA：只认十六进制（7~40 位）。`unknown` 之类一律不拼链接。 */
const SHA_RE = /^[0-9a-f]{7,40}$/i

/** diff 锚里的路径哈希固定是 64 位小写十六进制（sha256）。 */
const PATH_HASH_RE = /^[0-9a-f]{64}$/

/** `https://github.com/o/r/pull/12` → `https://github.com/o/r`；不是 PR 链接则返回 null。 */
export function repoRoot(prUrl?: string): string | null {
  const match = /^(https?:\/\/[^/]+\/[^/]+\/[^/]+)\/pull\/\d+/.exec(prUrl?.trim() ?? '')
  return match ? match[1] : null
}

/** 路径按段编码（不编码 `/`）：文件名里的空格/中文不会把 URL 拆坏。 */
function encodePath(file: string): string {
  return file
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/')
}

/**
 * 拼 GitHub blob 行锚；**要么给出完整链接、要么 null**（调用方降级成纯文本）。
 *
 * prUrl / headSha / 文件名 / 起始行任一缺失或不可信，就不拼半个链接。`runId` 不参与
 * 拼接（URL 里没有它），因此不作为可点条件：计划模式的 demo 结果没有 run 也应该能跳。
 */
export function blobUrl(
  prUrl: string | undefined,
  headSha: string | undefined,
  file: string,
  lineStart: number,
  lineEnd: number,
): string | null {
  const root = repoRoot(prUrl)
  const sha = headSha?.trim() ?? ''
  if (!root || !SHA_RE.test(sha)) return null
  if (!file.trim() || !Number.isInteger(lineStart) || lineStart <= 0) return null
  const path = encodePath(file)
  const anchor =
    Number.isInteger(lineEnd) && lineEnd > lineStart ? `#L${lineStart}-L${lineEnd}` : `#L${lineStart}`
  return `${root}/blob/${sha.toLowerCase()}/${path}${anchor}`
}

/**
 * PR「Files changed」里的行锚 URL。
 *
 * 形状：`<root>/pull/<n>/files#diff-<sha256(path)>R<line>`；`line` **优先取 line_end**
 * （GitHub 在区间上停在结束行，这点与 blob 锚的 `#L<start>-L<end>` 不同）。
 * 任一入参不可信（不是 PR 链接 / pr_number 非正整数 / 路径为空 / 哈希不是 sha256 /
 * 行号非正）都返回 null —— 宁可不给，也不给错链接。
 */
export function diffUrl(
  prUrl: string | undefined,
  prNumber: number | undefined,
  pathHash: string | null | undefined,
  file: string,
  lineStart: number,
  lineEnd: number,
): string | null {
  const root = repoRoot(prUrl)
  if (!root) return null
  if (typeof prNumber !== 'number' || !Number.isInteger(prNumber) || prNumber <= 0) return null
  if (!file.trim()) return null
  const hash = (pathHash ?? '').toLowerCase()
  if (!PATH_HASH_RE.test(hash)) return null
  const line = Number.isInteger(lineEnd) && lineEnd > lineStart ? lineEnd : lineStart
  if (!Number.isInteger(line) || line <= 0) return null
  return `${root}/pull/${prNumber}/files#diff-${hash}R${line}`
}

/**
 * 路径的 sha256（小写十六进制）。
 *
 * 环境没有 SubtleCrypto（非安全上下文的老浏览器）或计算失败 → null，
 * 调用方据此**不渲染** diff 动作，而不是拼一条猜出来的链接。
 */
export async function sha256Hex(text: string): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) return null
  try {
    const digest = await subtle.digest('SHA-256', new TextEncoder().encode(text))
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('')
  } catch {
    return null
  }
}

/**
 * 按文件路径记忆哈希：一屏几十条发现常常落在同几个文件上，不该重复算。
 *
 * 失败结果**不进缓存**（一次偶发失败不该被钉死一整场会话），下次调用会重算。
 * `hash` 可注入，供 Node 自测断言"同一个路径只算一次"。
 */
export function createPathHasher(
  hash: (text: string) => Promise<string | null> = sha256Hex,
): (file: string) => Promise<string | null> {
  const cache = new Map<string, Promise<string | null>>()
  return (file) => {
    const cached = cache.get(file)
    if (cached) return cached
    const pending = hash(file)
    cache.set(file, pending)
    void pending.then((hex) => {
      if (hex === null) cache.delete(file)
    })
    return pending
  }
}

/** 组件共用的默认哈希器：整个页面一份缓存。 */
const hashPath = createPathHasher()

/**
 * 一步到位：算路径哈希 → 拼 diff 行锚；算不出哈希就返回 null。
 *
 * `hash` 可注入（自测用）；默认走模块级缓存，所以同一文件的第二条 finding 不会重算。
 */
export async function diffAnchorUrl(
  prUrl: string | undefined,
  prNumber: number | undefined,
  file: string,
  lineStart: number,
  lineEnd: number,
  hash: (file: string) => Promise<string | null> = hashPath,
): Promise<string | null> {
  if (!file.trim()) return null
  const pathHash = await hash(file)
  return diffUrl(prUrl, prNumber, pathHash, file, lineStart, lineEnd)
}
