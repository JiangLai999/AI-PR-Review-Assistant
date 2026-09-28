/**
 * 读取页面关键元素的实际几何与可见性，用来定位"空白/被遮挡/不可见"这类问题。
 *
 * 用法：node tools/probe-layout.mjs review 1440 900
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const [, , view = 'review', wArg = '1440', hArg = '900'] = process.argv
const width = Number(wArg)
const height = Number(hArg)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
await page.goto(`${BASE}/#/${view}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const report = await page.evaluate(() => {
  const out = { viewport: { w: innerWidth, h: innerHeight }, doc: document.documentElement.scrollHeight, nodes: [] }
  const sels = [
    '.main', '.page-head', '.page-head h1', '.page-head .lead',
    '.review-launch-card', '.review-page', '.section', '.card',
    '.workspace-content', '.workspace-statusbar', '.workspace-sidebar',
  ]
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach((el, i) => {
      if (i > 2) return
      const r = el.getBoundingClientRect()
      const cs = getComputedStyle(el)
      out.nodes.push({
        sel: sel + (i ? `[${i}]` : ''),
        top: Math.round(r.top + scrollY),
        height: Math.round(r.height),
        left: Math.round(r.left),
        width: Math.round(r.width),
        display: cs.display,
        visibility: cs.visibility,
        opacity: cs.opacity,
        marginTop: cs.marginTop,
        paddingTop: cs.paddingTop,
        text: (el.textContent || '').trim().slice(0, 42),
      })
    })
  }
  return out
})

console.log(`view=${view}  viewport=${report.viewport.w}x${report.viewport.h}  docHeight=${report.doc}`)
console.log('')
console.log('sel'.padEnd(28) + 'top'.padStart(7) + 'h'.padStart(7) + 'left'.padStart(7) + 'w'.padStart(7) + '  display/vis/op')
for (const n of report.nodes) {
  console.log(
    n.sel.padEnd(28) +
      String(n.top).padStart(7) +
      String(n.height).padStart(7) +
      String(n.left).padStart(7) +
      String(n.width).padStart(7) +
      `  ${n.display}/${n.visibility}/${n.opacity}  ${n.text}`,
  )
}

// 找出首屏内的空白区块：可见元素覆盖不到的纵向区间
const covered = report.nodes
  .filter((n) => n.height > 0 && n.width > 0 && n.display !== 'none')
  .map((n) => [n.top, n.top + n.height])
  .sort((a, b) => a[0] - b[0])
let cursor = 0
const gaps = []
for (const [s, e] of covered) {
  if (s > cursor + 60) gaps.push([cursor, s])
  cursor = Math.max(cursor, e)
}
console.log('\n首屏内未被任何元素覆盖的纵向区间（>60px）：')
for (const [s, e] of gaps) console.log(`  ${s} → ${e}  (${e - s}px)`)

await browser.close()
