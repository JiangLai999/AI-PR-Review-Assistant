/**
 * 逐页检查主内容是否真的可见（visibility / opacity / 位置）。
 * 用法：node tools/audit-pages.mjs
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const VIEWS = ['overview', 'review', 'history', 'benchmark', 'api', 'settings']

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const problems = []

for (const view of VIEWS) {
  await page.goto(`${BASE}/#/${view}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2200)

  const info = await page.evaluate(() => {
    const collected = []
    document.querySelectorAll('h1, h2, .lead, .card, .finding, .metric').forEach((el) => {
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      if (r.height === 0) return
      collected.push({
        tag: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : ''),
        top: Math.round(r.top + scrollY),
        h: Math.round(r.height),
        vis: cs.visibility,
        op: Number(cs.opacity),
      })
    })
    return {
      docHeight: document.documentElement.scrollHeight,
      firstContentTop: collected.length ? Math.min(...collected.map((c) => c.top)) : null,
      hidden: collected.filter((c) => c.vis === 'hidden' || c.op < 0.99),
      total: collected.length,
    }
  })

  const bad = info.hidden.length
  const status = bad ? `隐藏元素 ${bad}/${info.total}` : '全部可见'
  console.log(
    `${view.padEnd(10)} docHeight=${String(info.docHeight).padStart(5)}  首个内容 top=${String(info.firstContentTop).padStart(4)}  ${status}`,
  )
  if (bad) {
    problems.push(view)
    for (const h of info.hidden.slice(0, 4)) {
      console.log(`             ↳ ${h.tag.padEnd(22)} top=${String(h.top).padStart(4)} h=${String(h.h).padStart(4)} vis=${h.vis} op=${h.op}`)
    }
  }
}

console.log('')
console.log(problems.length ? `受影响页面: ${problems.join(', ')}` : '所有页面内容均可见。')
await browser.close()
