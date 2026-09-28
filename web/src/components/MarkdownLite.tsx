import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
// `.js` 后缀是**必须的**：本目录里 `markdownLite.ts` 与 `MarkdownLite.tsx` 只差大小写，
// 在大小写不敏感的文件系统（Windows / 默认 macOS）上写 `./markdownLite` 会被解析到
// 它自己（MarkdownLite.tsx）形成自引用，esbuild 直接报 “No matching export”。
// 显式带 `.js` 后缀让解析器锁定 `markdownLite.ts`，大小写敏感/不敏感都稳。
import { inlineSegments, parseMarkdownLite } from './markdownLite.js'
import type { MdBlock, MdInline } from './markdownLite.js'
import { cx } from './ui'
import { useT } from '../i18n'

/**
 * 受限 Markdown 渲染层（追问回答专用）。
 *
 * **安全不变量**：只用 React 元素输出，全程没有 `dangerouslySetInnerHTML`、没有
 * `innerHTML`、没有第三方 Markdown 依赖。模型输出里的 `<script>` /
 * `<img src=x onerror=...>` 走到这里就是文本节点，浏览器只会把它当字面量显示。
 * 任何解析/渲染异常都在下面兜住并降级成 `<pre>`，绝不白屏。
 *
 * 样式一律走内联 + 现成设计变量（`var(--ds-*)`）：本轮 write_scope 不含 CSS 文件。
 *
 * 文案走 `t()`（词条在 `web/src/i18n/components.ts` 的 `markdown.*`）：
 * 语言切换即时生效，组件里不留硬编码中文。
 */

/** 超过这么多行就默认折叠，避免长日志把面板撑爆。 */
const COLLAPSE_LINES = 15

/** 复制成功后按钮文案停留多久（ms）。 */
const COPIED_MS = 2000

/** 解析器在原文没写语言时给出的占位 lang。 */
const PLACEHOLDER_LANG = 'text'

const CONTAINER_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--ds-space-3)',
  minWidth: 0,
}

const FALLBACK_STYLE: CSSProperties = {
  margin: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontFamily: 'var(--ds-font-mono)',
  fontSize: 'var(--ds-text-2xs)',
  lineHeight: 1.7,
  color: 'var(--ds-color-text-secondary)',
}

const PARAGRAPH_STYLE: CSSProperties = {
  margin: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  lineHeight: 1.75,
  fontSize: 'var(--ds-text-body)',
  color: 'var(--ds-color-text-secondary)',
}

const HEADING_STYLE: CSSProperties = {
  margin: 0,
  fontWeight: 500,
  lineHeight: 1.35,
  wordBreak: 'break-word',
  color: 'var(--ds-color-text-primary)',
}

/** 1/2/3 级分别映射到设计系统的三级标题字号。 */
const HEADING_SIZE: Record<1 | 2 | 3, string> = {
  1: 'var(--ds-text-heading2)',
  2: 'var(--ds-text-title)',
  3: 'var(--ds-text-subtitle)',
}

const LIST_STYLE: CSSProperties = {
  margin: 0,
  paddingLeft: 'var(--ds-space-6)',
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--ds-space-1)',
  fontSize: 'var(--ds-text-body)',
  lineHeight: 1.75,
  color: 'var(--ds-color-text-secondary)',
}

const QUOTE_STYLE: CSSProperties = {
  margin: 0,
  padding: 'var(--ds-space-1) 0 var(--ds-space-1) var(--ds-space-4)',
  borderLeft: '2px solid var(--ds-color-brand-soft)',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontSize: 'var(--ds-text-body)',
  lineHeight: 1.75,
  color: 'var(--ds-color-text-description)',
}

const HR_STYLE: CSSProperties = {
  margin: 0,
  border: 0,
  borderTop: '1px solid var(--ds-color-border-divider)',
}

const INLINE_CODE_STYLE: CSSProperties = {
  padding: '1px 5px',
  borderRadius: 'var(--ds-radius-xs)',
  background: 'var(--ds-color-bg-surface-5)',
  fontFamily: 'var(--ds-font-mono)',
  fontSize: '0.92em',
  color: 'var(--ds-color-text-primary)',
}

const CODE_WRAP_STYLE: CSSProperties = {
  position: 'relative',
  minWidth: 0,
  border: '1px solid var(--ds-color-border-default)',
  borderRadius: 'var(--ds-radius-code)',
  background: 'var(--ds-color-bg-code)',
}

const CODE_PRE_STYLE: CSSProperties = {
  margin: 0,
  // 顶部多留一截：右上角的 lang/复制条是绝对定位，不能压在第一行代码上。
  padding: 'calc(var(--ds-space-3) + 18px) var(--ds-space-4) var(--ds-space-3)',
  borderRadius: 'var(--ds-radius-code)',
  overflow: 'auto',
  whiteSpace: 'pre',
  fontFamily: 'var(--ds-font-mono)',
  fontSize: 'var(--ds-text-2xs)',
  lineHeight: 1.7,
  color: 'var(--ds-color-text-secondary)',
}

const CODE_BAR_STYLE: CSSProperties = {
  position: 'absolute',
  top: 'var(--ds-space-2)',
  right: 'var(--ds-space-2)',
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--ds-space-2)',
  zIndex: 1,
}

const LANG_STYLE: CSSProperties = {
  fontFamily: 'var(--ds-font-mono)',
  fontSize: 'var(--ds-text-3xs)',
  letterSpacing: '0.04em',
  color: 'var(--ds-color-text-placeholder)',
}

const CHIP_BUTTON_STYLE: CSSProperties = {
  border: '1px solid var(--ds-color-border-subtle)',
  borderRadius: 'var(--ds-radius-pill)',
  background: 'var(--ds-color-bg-surface-5)',
  padding: '2px var(--ds-space-3)',
  fontFamily: 'var(--ds-font-sans)',
  fontSize: 'var(--ds-text-3xs)',
  color: 'var(--ds-color-text-secondary)',
  cursor: 'pointer',
}

const CODE_FOOT_STYLE: CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  padding: '0 var(--ds-space-3) var(--ds-space-2)',
}

const TH_STYLE: CSSProperties = {
  textAlign: 'left',
  whiteSpace: 'nowrap',
  padding: 'var(--ds-space-2) var(--ds-space-3)',
  fontSize: 'var(--ds-text-2xs)',
  fontWeight: 400,
  color: 'var(--ds-color-text-description)',
  borderBottom: '1px solid var(--ds-color-border-default)',
}

const TD_STYLE: CSSProperties = {
  padding: 'var(--ds-space-2) var(--ds-space-3)',
  fontSize: 'var(--ds-text-xs)',
  verticalAlign: 'top',
  color: 'var(--ds-color-text-secondary)',
  borderBottom: '1px solid var(--ds-color-border-subtle)',
}

/**
 * 行内片段 → React 节点。
 *
 * `text` 一律作为**文本节点**输出（不套 dangerouslySetInnerHTML、不建可执行元素）：
 * 这是「模型输出不可执行」的最后一道关卡，即使解析器漏了什么 React 也会转义它。
 */
function renderInline(nodes: MdInline[]): ReactNode[] {
  return nodes.map((node, index) => {
    if (node.kind === 'bold') return <strong key={index}>{node.text}</strong>
    if (node.kind === 'code') return <code key={index} style={INLINE_CODE_STYLE}>{node.text}</code>
    return <span key={index}>{node.text}</span>
  })
}

/** 复制：只用 Clipboard API；失败（含非安全上下文）时**静默不改状态**，绝不谎报「已复制」。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    return false
  }
  return false
}

/** 围栏代码块：右上角 lang 标签 + 复制按钮；超过 15 行默认折叠。 */
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const t = useT()
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  const lines = code.split('\n')
  const collapsible = lines.length > COLLAPSE_LINES
  const hidden = collapsible ? lines.length - COLLAPSE_LINES : 0
  const visible = collapsible && !expanded ? lines.slice(0, COLLAPSE_LINES) : lines

  async function copy() {
    const ok = await copyText(code)
    if (!ok) return
    setCopied(true)
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), COPIED_MS)
  }

  return (
    <div style={CODE_WRAP_STYLE}>
      <div style={CODE_BAR_STYLE}>
        {/* lang 是解析器的占位值（原文本没写语言）时不显示标签，免得看着像某种语言。 */}
        {lang !== PLACEHOLDER_LANG && <span style={LANG_STYLE}>{lang}</span>}
        <button type="button" className="btn btn-ghost btn-sm" style={CHIP_BUTTON_STYLE} onClick={() => void copy()}>
          {copied ? t('markdown.copied') : t('markdown.copy')}
        </button>
      </div>
      <pre style={CODE_PRE_STYLE}>
        <code>{visible.join('\n')}</code>
      </pre>
      {collapsible && (
        <div style={CODE_FOOT_STYLE}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={CHIP_BUTTON_STYLE}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? t('markdown.collapse') : t('markdown.expand', { count: hidden })}
          </button>
        </div>
      )}
    </div>
  )
}

/** 表格：外层横向滚动，模型给的宽表不该把面板撑破。单元格是纯文本（不解析行内语法）。 */
function TableView({ header, rows }: { header: string[]; rows: string[][] }) {
  return (
    <div
      style={{
        overflowX: 'auto',
        maxWidth: '100%',
        border: '1px solid var(--ds-color-border-subtle)',
        borderRadius: 'var(--ds-radius-sm)',
      }}
    >
      <table className="table" style={{ borderCollapse: 'collapse', minWidth: '100%' }}>
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th key={index} style={TH_STYLE}>
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} style={TD_STYLE}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 降级用的「最像样的原文」：比 `String(block)` 的 `[object Object]` 有用得多。 */
function blockText(block: MdBlock): string {
  switch (block.kind) {
    case 'list':
      return block.items.map((item) => item.text).join('\n')
    case 'table':
      return [block.header.join(' | '), ...block.rows.map((row) => row.join(' | '))].join('\n')
    case 'code':
      return block.code
    case 'hr':
      return '---'
    default:
      return block.text
  }
}

/**
 * 单个块。外面包一层 try/catch：某一块构造元素时炸了只降级这一块，不牵连整段回答。
 * （渲染阶段的异常会冒到页面级的 ErrorBoundary，App.tsx 已包好，同样不会白屏。）
 */
function BlockView({ block }: { block: MdBlock }) {
  try {
    switch (block.kind) {
      case 'heading':
        return (
          <p style={{ ...HEADING_STYLE, fontSize: HEADING_SIZE[block.level] }}>
            {renderInline(inlineSegments(block.text))}
          </p>
        )
      case 'paragraph':
        return <p style={PARAGRAPH_STYLE}>{renderInline(block.inline)}</p>
      case 'list': {
        const children = block.items.map((item, index) => (
          <li key={index}>{renderInline(item.inline)}</li>
        ))
        return block.ordered ? (
          <ol style={LIST_STYLE}>{children}</ol>
        ) : (
          <ul style={LIST_STYLE}>{children}</ul>
        )
      }
      case 'code':
        return <CodeBlock lang={block.lang} code={block.code} />
      case 'quote':
        return <blockquote style={QUOTE_STYLE}>{renderInline(inlineSegments(block.text))}</blockquote>
      case 'table':
        return <TableView header={block.header} rows={block.rows} />
      case 'hr':
        return <hr style={HR_STYLE} />
      default:
        // 解析器加了新块类型但渲染层还没跟上：退回等宽原文，别静默吞掉内容。
        return <pre style={FALLBACK_STYLE}>{blockText(block)}</pre>
    }
  } catch {
    // 兜底：宁可退回等宽原文，也不要让一段回答把整页搞崩。
    return <pre style={FALLBACK_STYLE}>{blockText(block)}</pre>
  }
}

/**
 * 受限 Markdown 渲染器：把模型回答渲染成结构化元素。
 *
 * 解析抛异常时整体降级成 `<pre>{text}</pre>`（与旧行为一致）—— 排版再好也不值得
 * 为它冒白屏的风险。
 */
export function MarkdownLite({ text, className }: { text: string; className?: string }) {
  let blocks: MdBlock[] | null = null
  try {
    blocks = parseMarkdownLite(text)
  } catch {
    blocks = null
  }
  if (!blocks) {
    return (
      <pre className={cx('markdown-lite-fallback', className)} style={FALLBACK_STYLE}>
        {text}
      </pre>
    )
  }
  if (blocks.length === 0) return null

  return (
    <div className={cx('markdown-lite', className)} style={CONTAINER_STYLE}>
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </div>
  )
}
