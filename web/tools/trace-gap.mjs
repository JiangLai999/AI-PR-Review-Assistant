/**
 * 追踪首个内容之前的空白来源：打印祖先链的盒模型与定位方式。
 * 用法：node tools/trace-gap.mjs review 1440 900
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const [, , view = 'review', wArg = '1440', hArg = '900'] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: Number(wArg), height: Number(hArg) } })
await page.goto(`${BASE}/#/${view}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)

const out = await page.evaluate(() => {
  const lines = []
  const target = document.querySelector('.page-head') ?? document.querySelector('.main > .container')
  let el = target
  while (el) {
    const cs = getComputedStyle(el)
    const r = el.getBoundingClientRect()
    lines.push({
      tag: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className ? '.' + String(el.className).split(' ').slice(0, 2).join('.') : ''),
      position: cs.position,
      display: cs.display,
      padTop: cs.paddingTop,
      marginTop: cs.marginTop,
      top: Math.round(r.top + scrollY),
      height: Math.round(r.height),
      marginBottom: cs.marginBottom,
      paddingBottom: cs.paddingBottom,
      transform: cs.transform,
      inlineStyle: el.getAttribute('style') || '',
    })
    el = el.parentElement
  }
  // 所有能影响首屏上方空间的固定/粘性元素
  const overlays = []
  document.querySelectorAll('*').forEach((node) => {
    const cs = getComputedStyle(node)
    if ((cs.position === 'fixed' || cs.position === 'sticky') && cs.display !== 'none') {
      const r = node.getBoundingClientRect()
      if (r.height > 0) overlays.push({ sel: node.tagName.toLowerCase() + '.' + String(node.className).split(' ')[0], position: cs.position, top: Math.round(r.top), h: Math.round(r.height) })
    }
  })
  return { chain: lines, overlays, docHeight: document.documentElement.scrollHeight }
})

console.log(`view=${view} docHeight=${out.docHeight}`)
console.log('\n目标元素 → <body> 的祖先链（自下向上）:')
for (const n of out.chain) {
  console.log(
    `  ${n.tag.padEnd(30)} pos=${n.position.padEnd(8)} padTop=${n.padTop.padStart(7)} top=${String(n.top).padStart(5)} h=${String(n.height).padStart(5)}`,
  )
  if (n.transform !== 'none' || n.inlineStyle) {
    console.log(`      transform=${n.transform}  inline="${n.inlineStyle.slice(0, 120)}"`)
  }
}
console.log('\n固定/粘性元素:')
for (const o of out.overlays) console.log(`  ${o.sel.padEnd(34)} ${o.position.padEnd(7)} top=${String(o.top).padStart(5)} h=${String(o.h).padStart(4)}`)

await browser.close()
