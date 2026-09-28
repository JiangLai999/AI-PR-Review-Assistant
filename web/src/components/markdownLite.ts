/**
 * 受限 Markdown 解析器（追问回答专用）。
 *
 * **安全边界（本文件的全部意义所在）**：这里只产出「数据」，不产出 HTML，也没有任何
 * `innerHTML` 通路。模型输出里的 `<img src=x onerror=alert(1)>`、`<script>` 只会作为
 * 普通 `text` 段出现在结构里，交给 React 当文本渲染 —— 所以它们绝无执行的可能。
 * 因此这里**刻意不支持**链接、图片、原始 HTML：这三类语法一旦支持，就等于把
 * 「能不能执行」的决定权交给模型输出。
 *
 * 语法子集（超出子集的部分一律按普通文本处理，不报错、不丢内容）：
 * - 标题 `#` / `##` / `###`（`####` 及更多按 3 级处理）
 * - 列表 `- ` / `* ` / `+ ` 与 `1. `
 * - 围栏代码块 ```（块内原样保留，不解析任何 Markdown）
 * - 表格（必须带 `|---|` 分隔行才算表格）
 * - 引用 `> `
 * - 分隔线 `---` / `***` / `___`（连续 3 个及以上）
 * - 段落（连续非空行合并）
 * - 行内：`**粗体**`、`` `行内码` ``
 *
 * 这个文件**不能有 JSX**，也不使用 enum / namespace / 装饰器等需要编译转换的语法，
 * 这样 Node 24 才能靠类型剥离直接 `import` 它跑自测（见 tools/markdown-lite-check.mjs）。
 */

/** 行内片段。只有三种 —— 没有链接/图片/HTML，这是安全边界而不是偷懒。 */
export type MdInline =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'code'; text: string }

/** 块级结构。`kind` 的取值就是渲染层能遇到的全部可能。 */
export type MdBlock =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string }
  | { kind: 'paragraph'; text: string; inline: MdInline[] }
  | { kind: 'list'; ordered: boolean; items: { text: string; inline: MdInline[] }[] }
  | { kind: 'code'; lang: string; code: string }
  | { kind: 'quote'; text: string }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'hr' }

/** 围栏代码块 lang 缺失时的占位值。 */
const DEFAULT_CODE_LANG = 'text'

/** 标题最高渲染到 3 级：`####` 及更多都压成 3 级。 */
const MAX_HEADING_LEVEL = 3

/** `#` 后面必须至少一个空格，否则 `#tag` 只是普通文本。 */
const HEADING_RE = /^(#{1,6})[ \t]+(.+?)[ \t]*$/

/** `---` / `***` / `___`，3 个及以上，前后允许 0~3 个空格。 */
const HR_RE = /^ {0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$/

/** 无序列表项：`- ` / `* ` / `+ `（后面必须至少一个空格，避免和 hr、`**` 混淆）。 */
const BULLET_RE = /^ {0,3}([-*+])[ \t]+(.*)$/

/** 有序列表项：只认 `1. `（不认 `1)`，保持子集最小化）。 */
const ORDERED_RE = /^ {0,3}(\d{1,9})\.[ \t]+(.*)$/

/** 围栏开/闭行：3 个及以上反引号，闭行后面可以跟零散字符。 */
const FENCE_RE = /^ {0,3}(`{3,})(.*)$/

/** 表格分隔行里的单元格：`|---|`、`|:---:|` 都算。 */
const DELIMITER_CELL_RE = /^:?-+:?$/

/**
 * 解析行内语法。
 *
 * 只认两种标记：`**…**` 与 `` `…` ``。相邻的纯文本会合并成一个 `text` 段，
 * 免得渲染层拿到一串碎片。**未闭合的标记按普通文本**（例如 `a ** b` 就是三个字符），
 * 这比「吃掉后面所有内容直到行尾」安全得多，也不会凭空丢字。
 *
 * 粗体/行内码的内部**不再递归解析**：`MdInline.text` 是纯字符串，渲染层直接当文本
 * 贴进 `<strong>` / `<code>`，所以 `**a `b`**` 里的反引号会原样显示。
 *
 * 入参是**整段文本**（段内换行是 `\n`），所以同一段里的 `**` 可以跨行配对；
 * 跨空行则配不上 —— 空行已经把文本切成两个块了。
 */
export function inlineSegments(text: string): MdInline[] {
  const out: MdInline[] = []
  let plain = ''
  const flush = (): void => {
    if (plain) {
      out.push({ kind: 'text', text: plain })
      plain = ''
    }
  }

  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === '`') {
      // 空 code span（``）不算标记，继续当普通字符走。
      const end = text.indexOf('`', i + 1)
      if (end > i + 1) {
        flush()
        out.push({ kind: 'code', text: text.slice(i + 1, end) })
        i = end + 1
        continue
      }
    } else if (ch === '*' && text[i + 1] === '*') {
      // 内容为空（`****`）或没有闭合，都退回普通文本。
      const end = text.indexOf('**', i + 2)
      if (end > i + 2) {
        flush()
        out.push({ kind: 'bold', text: text.slice(i + 2, end) })
        i = end + 2
        continue
      }
    }
    plain += ch
    i += 1
  }
  flush()
  return out
}

/** `| a | b |` → `['a', 'b']`。首尾竖线可有可无，单元格两侧空白一律去掉。 */
function splitRow(line: string): string[] {
  let body = line.trim()
  if (body.startsWith('|')) body = body.slice(1)
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1)
  if (!body) return []
  return body.split('|').map((cell) => cell.trim())
}

/** 一行是不是表格分隔行（`|---|---|`）。所有单元格都得是纯横线。 */
function isDelimiterRow(line: string): boolean {
  const cells = splitRow(line)
  return cells.length > 0 && cells.every((cell) => DELIMITER_CELL_RE.test(cell))
}

/** 是不是表格候选行：必须以 `|` 开头且至少有一个单元格。 */
function isTableRow(line: string): boolean {
  return line.trim().startsWith('|') && splitRow(line).length > 0
}

/** 列数对齐：缺列补空串，多余的列截掉（列数以 header 为准）。 */
function fitRow(cells: string[], width: number): string[] {
  const row: string[] = []
  for (let i = 0; i < width; i += 1) row.push(cells[i] ?? '')
  return row
}

/** 引用行：去掉行首 0~3 个空格、任意多个 `>`，再吃掉一个可选空格。 */
function stripQuote(line: string): string {
  return line.trim().replace(/^>+/, '').replace(/^ /, '')
}

/**
 * 解析一段 Markdown，产出块序列（空输入 → 空数组）。
 *
 * 纯函数、不抛异常、不访问全局状态；渲染层再兜一层 try/catch 降级成 `<pre>`。
 * 未闭合的围栏代码块会一直吃到输入结束（而不是把围栏行当普通文本），这样半截的
 * 模型输出也不会把后面的正文渲染成一堆垃圾。
 */
export function parseMarkdownLite(text: string): MdBlock[] {
  const blocks: MdBlock[] = []
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n')
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // 空行只是块分隔符，不产出任何块。
    if (!line.trim()) {
      i += 1
      continue
    }

    // 1) 围栏代码块：块内内容原样保留（含缩进与空行），围栏行本身不进内容。
    const fence = FENCE_RE.exec(line)
    if (fence) {
      const info = fence[2].trim()
      const lang = info ? (info.split(/\s+/)[0] ?? '') : DEFAULT_CODE_LANG
      const body: string[] = []
      i += 1
      while (i < lines.length && !FENCE_RE.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      // 末尾那行闭围栏（如果有）不计入内容。
      if (i < lines.length) i += 1
      blocks.push({ kind: 'code', lang: lang || DEFAULT_CODE_LANG, code: body.join('\n') })
      continue
    }

    // 2) 标题：`#`/`##`/`###`，`####` 及更多压成 3 级。
    const heading = HEADING_RE.exec(line)
    if (heading) {
      const level = Math.min(heading[1].length, MAX_HEADING_LEVEL) as 1 | 2 | 3
      blocks.push({ kind: 'heading', level, text: heading[2].trim() })
      i += 1
      continue
    }

    // 3) 分隔线。必须在列表之前判，否则 `- - -` 之类会被当成列表项。
    if (HR_RE.test(line)) {
      blocks.push({ kind: 'hr' })
      i += 1
      continue
    }

    // 4) 表格：首行 + 紧随其后的分隔行，两者都在才算表格。
    if (isTableRow(line) && i + 1 < lines.length && isDelimiterRow(lines[i + 1])) {
      const header = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(fitRow(splitRow(lines[i]), header.length))
        i += 1
      }
      blocks.push({ kind: 'table', header, rows })
      continue
    }

    // 5) 引用：连续 `>` 行合并成一个块，行内保留 `\n`。
    if (line.trim().startsWith('>')) {
      const quoted: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoted.push(stripQuote(lines[i]))
        i += 1
      }
      blocks.push({ kind: 'quote', text: quoted.join('\n') })
      continue
    }

    // 6) 列表：连续**同类**（同为无序或同为有序）行合并成一个 list 块。
    const bullet = BULLET_RE.exec(line)
    const ordered = bullet ? null : ORDERED_RE.exec(line)
    if (bullet || ordered) {
      const isOrdered = Boolean(ordered)
      const items: { text: string; inline: MdInline[] }[] = []
      while (i < lines.length) {
        const current = lines[i]
        const nextBullet = BULLET_RE.exec(current)
        const nextOrdered = nextBullet ? null : ORDERED_RE.exec(current)
        const match = nextBullet ?? nextOrdered
        // 不是列表项，或换了有序性：收尾。两种列表各成一块。
        if (!match || Boolean(nextOrdered) !== isOrdered) break
        const body = match[2].trim()
        items.push({ text: body, inline: inlineSegments(body) })
        i += 1
      }
      blocks.push({ kind: 'list', ordered: isOrdered, items })
      continue
    }

    // 7) 段落：连续非空行合并，行与行之间保留 `\n`（渲染层用 pre-wrap 保留换行）。
    const paragraph: string[] = []
    while (i < lines.length) {
      const current = lines[i]
      if (
        !current.trim() ||
        FENCE_RE.test(current) ||
        HEADING_RE.test(current) ||
        HR_RE.test(current) ||
        BULLET_RE.test(current) ||
        ORDERED_RE.test(current) ||
        current.trim().startsWith('>') ||
        // 表格头也必须断开，否则表格会被吸进上一段。
        (isTableRow(current) && i + 1 < lines.length && isDelimiterRow(lines[i + 1]))
      ) {
        break
      }
      paragraph.push(current.trim())
      i += 1
    }
    const joined = paragraph.join('\n')
    if (joined) blocks.push({ kind: 'paragraph', text: joined, inline: inlineSegments(joined) })
  }

  return blocks
}
