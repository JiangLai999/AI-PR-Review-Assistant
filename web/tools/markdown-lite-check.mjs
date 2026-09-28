/**
 * markdownLite 受限 Markdown 渲染器自测（Node 24 靠类型剥离直接跑 .ts，不需要测试框架）。
 *
 * 跑法：`node tools/markdown-lite-check.mjs`（在 web/ 下）。
 * 两个阶段：
 * 1) **解析器**（markdownLite.ts）：标题 / 列表 / 行内 / 围栏代码块 / 表格 / 引用 / hr /
 *    段落合并，以及两条安全断言：HTML 注入必须只当纯文本、未闭合标记必须退回普通文本；
 * 2) **渲染层**（MarkdownLite.tsx）：借 vite 的 SSR 管线把组件渲染成 HTML 字符串，证明
 *    「模型输出不可执行」和「代码块折叠 / lang 标签 / 表格横向滚动」这些只有渲染层才有的
 *    行为是真的（纯解析器测试证不了「不会白屏、不会执行 HTML」）。
 */
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { inlineSegments, parseMarkdownLite } from '../src/components/markdownLite.ts'

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

const kinds = (blocks) => blocks.map((block) => block.kind)
const only = (blocks, kind) => blocks.filter((block) => block.kind === kind)
const one = (blocks, kind) => {
  const matched = only(blocks, kind)
  return matched.length === 1 ? matched[0] : null
}

// ---------------------------------------------------------------- 标题
{
  const blocks = parseMarkdownLite('# 一级\n## 二级\n### 三级\n#### 四级\n##### 五级')
  check(
    '标题：`#`~`#####` 全部识别，`####` 及更多压成 3 级',
    blocks.length === 5 &&
      blocks.every((b) => b.kind === 'heading') &&
      blocks.map((b) => b.level).join(',') === '1,2,3,3,3' &&
      blocks.map((b) => b.text).join(',') === '一级,二级,三级,四级,五级',
    JSON.stringify(blocks.map((b) => [b.level, b.text])),
  )
}
{
  // 行首 `#` 后必须至少一个空格，否则是普通文本（#issue、#1 这类不能被吃掉）。
  const blocks = parseMarkdownLite('#nospace\n#  有空格')
  check(
    '标题：`#` 后必须有空格才算标题',
    kinds(blocks).join(',') === 'paragraph,heading' && blocks[0].text === '#nospace',
    JSON.stringify(blocks),
  )
}

// ---------------------------------------------------------------- 列表
{
  const blocks = parseMarkdownLite('- 第一项\n* 第二项\n+ 第三项')
  const list = one(blocks, 'list')
  check(
    '无序列表：`-`/`*`/`+` 连续行合并成一个 list 块',
    !!list && list.ordered === false && list.items.map((item) => item.text).join('|') === '第一项|第二项|第三项',
    JSON.stringify(list),
  )
}
{
  const blocks = parseMarkdownLite('1. 第一步\n2. 第二步\n3. 第三步')
  const list = one(blocks, 'list')
  check(
    '有序列表：`1.` 连续行合并成一个 ordered 块',
    !!list && list.ordered === true && list.items.length === 3 && list.items[2].text === '第三步',
    JSON.stringify(list),
  )
}
{
  const blocks = parseMarkdownLite('- 无序\n1. 有序')
  check(
    '列表：有序/无序切换会分成两个 list 块',
    kinds(blocks).join(',') === 'list,list' && blocks[0].ordered === false && blocks[1].ordered === true,
    JSON.stringify(blocks.map((b) => [b.kind, b.ordered])),
  )
}
{
  const blocks = parseMarkdownLite('- 带 **粗体** 和 `代码`')
  const list = one(blocks, 'list')
  check(
    '列表项复用行内解析：粗体 + 行内码',
    !!list &&
      list.items[0].inline.map((n) => n.kind).join(',') === 'text,bold,text,code' &&
      list.items[0].inline[1].text === '粗体' &&
      list.items[0].inline[3].text === '代码',
    JSON.stringify(list && list.items[0].inline),
  )
}

// ---------------------------------------------------------------- 行内
{
  const nodes = inlineSegments('前面 **重点** 后面 `code` 尾巴')
  check(
    '行内：`**x**` → bold、`` `x` `` → code、其余合并为 text',
    nodes.length === 5 &&
      nodes[0].text === '前面 ' &&
      nodes[1].kind === 'bold' &&
      nodes[1].text === '重点' &&
      nodes[2].text === ' 后面 ' &&
      nodes[3].kind === 'code' &&
      nodes[3].text === 'code' &&
      nodes[4].text === ' 尾巴',
    JSON.stringify(nodes),
  )
}
{
  const nodes = inlineSegments('**没有闭合的粗体 还有后面')
  check(
    '行内：未闭合的 `**` 退回普通文本，不吞后文',
    nodes.length === 1 && nodes[0].kind === 'text' && nodes[0].text === '**没有闭合的粗体 还有后面',
    JSON.stringify(nodes),
  )
}
{
  const nodes = inlineSegments('`未闭合的行内码 还有 **闭合的**')
  check(
    '行内：未闭合的反引号退回普通文本，后面的粗体仍能解析',
    nodes.map((n) => n.kind).join(',') === 'text,bold' &&
      nodes[0].text === '`未闭合的行内码 还有 ' &&
      nodes[1].text === '闭合的',
    JSON.stringify(nodes),
  )
}
{
  // 安全边界：链接/图片一律当纯文本，绝不生成可执行或可导航的结构。
  const nodes = inlineSegments('看 [文档](https://example.com) 和 ![图](x.png)')
  check(
    '行内：不解析链接/图片，全部当纯文本',
    nodes.length === 1 && nodes[0].kind === 'text' && nodes[0].text.includes('[文档](https://example.com)') &&
      nodes[0].text.includes('![图](x.png)'),
    JSON.stringify(nodes),
  )
}

// ---------------------------------------------------------------- 围栏代码块
{
  const blocks = parseMarkdownLite('```python\nprint(1)\n```')
  const code = one(blocks, 'code')
  check(
    '围栏代码块：取首个 token 当 lang，围栏行不进内容',
    !!code && code.lang === 'python' && code.code === 'print(1)',
    JSON.stringify(code),
  )
}
{
  const blocks = parseMarkdownLite('```\nplain\n```')
  const code = one(blocks, 'code')
  check('围栏代码块：空 lang 回落成 `text`', !!code && code.lang === 'text' && code.code === 'plain', JSON.stringify(code))
}
{
  // 块内不解析任何 Markdown：标题/粗体/表格/围栏都按原样留着。
  const source = ['```md', '# 不是标题', '- **不是粗体**', '| a | b |', '| - | - |', '', '  缩进保留', '```'].join('\n')
  const code = one(parseMarkdownLite(source), 'code')
  check(
    '围栏代码块：块内不解析任何 Markdown，空行/缩进原样保留',
    !!code &&
      code.lang === 'md' &&
      code.code === '# 不是标题\n- **不是粗体**\n| a | b |\n| - | - |\n\n  缩进保留' &&
      code.code.includes('\n\n'),
    JSON.stringify(code && code.code),
  )
}

// ---------------------------------------------------------------- 表格
{
  const blocks = parseMarkdownLite('| 文件 | 行数 |\n| --- | ---: |\n| a.ts | 12 |\n| b.ts | 3 |')
  const table = one(blocks, 'table')
  check(
    '表格：`|` 行 + 分隔行 → header + rows，列以 header 为准',
    !!table && table.header.join(',') === '文件,行数' && table.rows.length === 2 && table.rows[1].join(',') === 'b.ts,3',
    JSON.stringify(table),
  )
}
{
  const blocks = parseMarkdownLite('| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 | 4 |')
  const table = one(blocks, 'table')
  check(
    '表格：缺列补空串、多余列截断',
    !!table &&
      table.rows[0].join(',') === '1,,' &&
      table.rows[0].length === 3 &&
      table.rows[1].join(',') === '1,2,3' &&
      table.rows[1].length === 3,
    JSON.stringify(table && table.rows),
  )
}
{
  // 没有分隔行就不是表格：整段退回普通段落（而不是半吊子表格）。
  const blocks = parseMarkdownLite('| a | b |\n| 1 | 2 |')
  check(
    '表格：缺分隔行时不解析成表格（整块是段落）',
    kinds(blocks).join(',') === 'paragraph' && blocks[0].text === '| a | b |\n| 1 | 2 |',
    JSON.stringify(blocks),
  )
}
{
  // 表格头不能被吸进上一段。
  const blocks = parseMarkdownLite('说明文字\n| a | b |\n| --- | --- |\n| 1 | 2 |')
  check(
    '表格：表格头会把上一段断开',
    kinds(blocks).join(',') === 'paragraph,table' && blocks[0].text === '说明文字',
    JSON.stringify(kinds(blocks)),
  )
}
{
  const table = one(parseMarkdownLite('| h |\n| --- |\n| **不解析** |'), 'table')
  check(
    '表格：单元格内不解析行内语法（保持纯字符串）',
    !!table && table.rows[0][0] === '**不解析**',
    JSON.stringify(table && table.rows),
  )
}

// ---------------------------------------------------------------- 引用 / hr
{
  const blocks = parseMarkdownLite('> 第一行\n> 第二行\n>> 嵌套引用')
  const quote = one(blocks, 'quote')
  check(
    '引用：`>` 与 `>>` 连续行合并，行内保留 `\\n`',
    !!quote && quote.text === '第一行\n第二行\n嵌套引用',
    JSON.stringify(quote),
  )
}
{
  const blocks = parseMarkdownLite('a\n\n---\n\n***\n\n___\n\nb')
  check(
    'hr：`---` / `***` / `___` 都识别为分隔线',
    kinds(blocks).join(',') === 'paragraph,hr,hr,hr,paragraph',
    JSON.stringify(kinds(blocks)),
  )
}

// ---------------------------------------------------------------- 段落
{
  const blocks = parseMarkdownLite('第一行\n第二行\n\n另一段')
  check(
    '段落：连续非空行合并，段内用 `\\n` 连接（已锁死），空行分段',
    kinds(blocks).join(',') === 'paragraph,paragraph' &&
      blocks[0].text === '第一行\n第二行' &&
      blocks[0].inline.length === 1 &&
      blocks[1].text === '另一段',
    JSON.stringify(blocks),
  )
}
{
  // 行内解析以**整段文本**为单位：`same 段内**可以跨行配对，但空行已经分段，跨不过去。
  const joined = parseMarkdownLite('**跨行\n配对**')
  check(
    '段落：同段内 `**` 可跨行配对',
    joined.length === 1 && joined[0].inline[0].kind === 'bold' && joined[0].inline[0].text === '跨行\n配对',
    JSON.stringify(joined[0].inline),
  )
  const split = parseMarkdownLite('**未闭合\n\n配对**')
  check(
    '段落：跨空行不配对（两段各自退回纯文本）',
    kinds(split).join(',') === 'paragraph,paragraph' &&
      split.every((b) => b.inline.every((n) => n.kind === 'text')),
    JSON.stringify(split),
  )
}
check('空输入产出空数组', parseMarkdownLite('').length === 0)
{
  const blocks = parseMarkdownLite('带 CRLF\r\n的第二行\r\n\r\n新段')
  check(
    '段落：CRLF 归一化成 `\\n`，空行仍能分段',
    kinds(blocks).join(',') === 'paragraph,paragraph' && blocks[0].text === '带 CRLF\n的第二行',
    JSON.stringify(blocks),
  )
}

// ---------------------------------------------------------------- 安全边界
{
  const payloads = [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<iframe src="javascript:alert(1)"></iframe>',
  ]
  for (const payload of payloads) {
    const blocks = parseMarkdownLite(`前面 ${payload} 后面`)
    const paragraph = one(blocks, 'paragraph')
    const raw = JSON.stringify(blocks)
    check(
      `安全：\`${payload}\` 只作为纯文本出现`,
      kinds(blocks).join(',') === 'paragraph' &&
        !!paragraph &&
        paragraph.text.includes(payload) &&
        paragraph.inline.every((node) => node.kind === 'text') &&
        !raw.includes('"html"'),
      raw,
    )
  }
}
{
  // 代码块 / 引用 / 列表项里的标签同样只能是文本。
  const blocks = parseMarkdownLite('```html\n<img src=x onerror=alert(1)>\n```\n\n> <script>alert(2)</script>\n\n- <b>hi</b>')
  check(
    '安全：代码块/引用/列表里的标签也都是文本',
    kinds(blocks).join(',') === 'code,quote,list' &&
      one(blocks, 'code').code === '<img src=x onerror=alert(1)>' &&
      one(blocks, 'quote').text === '<script>alert(2)</script>' &&
      one(blocks, 'list').items[0].inline[0].kind === 'text',
    JSON.stringify(blocks),
  )
}

// ---------------------------------------------------------------- 渲染层（SSR 冒烟）
// 走 vite 自己的解析/编译管线，所以顺带验证了大小写不敏感文件系统上的模块解析
// （markdownLite.ts 与 MarkdownLite.tsx 只差大小写，import 必须写成 './markdownLite.js'）。
console.log('\n--- 渲染层 MarkdownLite.tsx（SSR 冒烟） ---')
{
  const webRoot = fileURLToPath(new URL('..', import.meta.url))
  const server = await createServer({
    root: webRoot,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false },
  })
  try {
    const { MarkdownLite } = await server.ssrLoadModule('/src/components/MarkdownLite.tsx')
    const render = (text) => renderToStaticMarkup(createElement(MarkdownLite, { text }))
    const codeOf = (html) => [...html.matchAll(/<code>([\s\S]*?)<\/code>/g)].map((m) => m[1])
    const longCode = ['let x = 1', ...Array.from({ length: 20 }, (_, i) => `line-${i + 1}`)].join('\n')
    const source = [
      '# 结论',
      '',
      '下面是 **重点** 与 `code`。',
      '',
      '- 第一项',
      '- 第二项',
      '',
      '1. 步骤一',
      '2. 步骤二',
      '',
      '> 引用一行',
      '> 引用二行',
      '',
      '---',
      '',
      '| 文件 | 行数 |',
      '| --- | --- |',
      '| a.ts |',
      '| b.ts | 3 | 4 |',
      '',
      '```js',
      longCode,
      '```',
      '',
      '```',
      'no lang',
      '```',
      '',
      '<img src=x onerror=alert(1)>',
      '',
      '[链接](javascript:alert(1))',
    ].join('\n')
    const html = render(source)

    check('渲染：HTML 注入被转义成 &lt;img…&gt;', html.includes('&lt;img src=x onerror=alert(1)&gt;'), html.slice(0, 200))
    check('渲染：输出里没有裸 <img>', !html.includes('<img'))
    check('渲染：输出里没有 <script', !html.includes('<script'))
    check('渲染：没有其它未经转义的尖括号标签', !/<(img|script|iframe|svg|a|object|embed)\b/i.test(html))
    check('渲染：`javascript:` 伪协议仍是纯文本', html.includes('[链接](javascript:alert(1))'))
    check('渲染：粗体输出 <strong>重点</strong>', html.includes('<strong>重点</strong>'))
    check('渲染：行内码输出 <code>', html.includes('>code</code>'))
    check('渲染：标题使用设计变量字号', html.includes('var(--ds-text-heading2)'))
    check('渲染：表格 = 表头 + 2 行数据（列按 header 补齐/截断）', (html.match(/<tr>/g) || []).length === 3, html.match(/<tr>/g)?.length)
    check('渲染：表头左对齐', html.includes('text-align:left'))
    check('渲染：表格外层 overflow-x:auto', html.includes('overflow-x:auto'))
    check('渲染：无序列表 <ul>', html.includes('<ul'))
    check('渲染：有序列表 <ol>', html.includes('<ol'))
    check('渲染：引用 <blockquote>', html.includes('<blockquote'))
    check('渲染：分隔线 <hr', html.includes('<hr'))
    check('渲染：代码块右上角 lang 标签 js', html.includes('>js</span>'))
    check('渲染：空 lang 不显示标签', !html.includes('>text</span>'))
    check('渲染：复制按钮', html.includes('>复制<'))
    check(
      '渲染：21 行代码默认折叠到 15 行',
      codeOf(html)[0].split('\n').length === 15 && !codeOf(html)[0].includes('line-15'),
      `${codeOf(html)[0].split('\n').length} 行`,
    )
    check('渲染：折叠角标显示藏起来的行数「展开 6 行」', html.includes('展开 6 行'))
    check('渲染：默认折叠时不出现「收起」', !html.includes('>收起<'))
    check('渲染：15 行以内的代码块不折叠', !render(['```', 's-0', 's-1', 's-2', '```'].join('\n')).includes('展开'))
    check('渲染：空输入渲染为空而不是崩', render('') === '')
    check('渲染：纯文本仍是段落', render('就一句话').includes('就一句话'))
  } finally {
    await server.close()
  }
}

console.log(`\n${passed} passed, ${failures.length} failed`)
if (failures.length === 0) {
  console.log('ALL PASS')
} else {
  console.log(`FAILURES: ${failures.join(' | ')}`)
  process.exitCode = 1
}
