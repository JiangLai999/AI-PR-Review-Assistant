/**
 * 精确测量首屏上方每一段的来源。
 * 用法：node tools/measure-top.mjs review 1440 900
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const view = process.argv[2] ?? 'review'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto(`${BASE}/#/${view}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)

const data = await page.evaluate(() => {
  const box = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const cs = getComputedStyle(el)
    const r = el.getBoundingClientRect()
    return {
      sel,
      top: Math.round(r.top + scrollY),
      bottom: Math.round(r.bottom + scrollY),
      h: Math.round(r.height),
      position: cs.position,
      paddingTop: cs.paddingTop,
      paddingBottom: cs.paddingBottom,
      marginTop: cs.marginTop,
      marginBottom: cs.marginBottom,
      alignSelf: cs.alignSelf,
    }
  }
  const shell = document.querySelector('.workspace-shell')
  const shellAlign = shell ? getComputedStyle(shell).alignItems : null
  const content = document.querySelector('.workspace-content')
  const contentChildren = content
    ? [...content.children].map((c) => {
        const r = c.getBoundingClientRect()
        return { tag: c.tagName.toLowerCase() + '.' + String(c.className).split(' ')[0], top: Math.round(r.top + scrollY), h: Math.round(r.height) }
      })
    : []
  return {
    shellAlign,
    boxes: ['.workspace-content', '.workspace-statusbar', 'main.main', '.main > .container', '.page-head'].map(box),
    contentChildren,
  }
})

console.log(`view=${view}  .workspace-shell align-items = ${data.shellAlign}`)
console.log('')
for (const b of data.boxes) {
  if (!b) { console.log('  (missing)'); continue }
  console.log(
    `  ${b.sel.padEnd(24)} top=${String(b.top).padStart(5)} bottom=${String(b.bottom).padStart(5)} h=${String(b.h).padStart(5)} pos=${b.position.padEnd(8)} padTop=${b.paddingTop.padStart(7)} alignSelf=${b.alignSelf}`,
  )
}
console.log('\n.workspace-content 的子元素:')
for (const c of data.contentChildren) console.log(`  ${c.tag.padEnd(26)} top=${String(c.top).padStart(5)} h=${String(c.h).padStart(5)}`)

await browser.close()
