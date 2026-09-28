/**
 * p2-ux 断言：U3 窄屏无横向溢出 + U1 键盘焦点可见。
 *
 * 用法（需本地服务已在 127.0.0.1:8787）：
 *   node tools/focus-mobile-check.mjs
 * 失败时 process.exitCode = 1；每条断言打印 PASS/FAIL。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const results = []
let failed = false

function record(name, ok, detail) {
  results.push({ name, ok, detail })
  if (!ok) failed = true
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

const browser = await chromium.launch()
try {
  // ---- 断言 1：390×844 无横向溢出 ----
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 })
    await page.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(800)
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const limit = 390 + 1
    record(
      'A1 390x844 no-horizontal-overflow',
      scrollWidth <= limit,
      `document.documentElement.scrollWidth=${scrollWidth} (limit ${limit})`,
    )
    await page.close()
  }

  // ---- 断言 2：1440×900 Tab 前 6 个可聚焦元素均有 :focus-visible 且 outline-width >= 2px ----
  {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
    await page.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(800)

    const samples = []
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press('Tab')
      // 等一帧让 :focus-visible / outline 生效
      await page.waitForTimeout(80)
      const info = await page.evaluate(() => {
        const el = document.activeElement
        if (!el || el === document.body) {
          return { tag: '(none)', focusVisible: false, outlineWidth: '0px', outlineStyle: '' }
        }
        const cs = getComputedStyle(el)
        return {
          tag: el.tagName.toLowerCase() + (el.className ? `.${String(el.className).split(/\s+/)[0]}` : ''),
          focusVisible: el.matches(':focus-visible'),
          outlineWidth: cs.outlineWidth,
          outlineStyle: cs.outlineStyle,
        }
      })
      samples.push(info)
    }

    const bad = samples.filter((s) => {
      const w = parseFloat(s.outlineWidth) || 0
      return !s.focusVisible || w < 2
    })
    const detail = samples
      .map((s, i) => `#${i + 1} ${s.tag} focus-visible=${s.focusVisible} outline-width=${s.outlineWidth}`)
      .join(' | ')
    record('A2 1440x900 focus-visible on first 6 tabbables', bad.length === 0, detail)
    await page.close()
  }
} catch (err) {
  record('runner', false, String(err && err.message ? err.message : err))
} finally {
  await browser.close()
}

console.log('')
console.log(`summary: ${results.filter((r) => r.ok).length}/${results.length} PASS`)
if (failed) process.exitCode = 1
