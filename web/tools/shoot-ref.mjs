/**
 * 参考站截图：用于把本地实现与参考版面逐屏对照。
 *
 * 用法：
 *   node tools/shoot-ref.mjs                # 默认截 deepseek harness 首页
 *   REF=https://example.com node tools/shoot-ref.mjs
 *   FULL=0 node tools/shoot-ref.mjs         # 只截首屏
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../.shots')
const REF = process.env.REF ?? 'https://www.deepseek.com/harness/'
const width = Number(process.env.W ?? 1440)
const FULL = process.env.FULL !== '0'

await mkdir(outDir, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({
  viewport: { width, height: 1000 },
  deviceScaleFactor: 2,
  locale: 'zh-CN',
})

await page.goto(REF, { waitUntil: 'networkidle', timeout: 60000 })
await page.waitForTimeout(2500)

const file = resolve(outDir, `ref-${width}${FULL ? '' : '-vp'}.png`)
await page.screenshot({ path: file, fullPage: FULL })
console.log(`ref -> ${file}`)

// 顺带把关键排版的实际计算值打出来，避免靠猜。
const computed = await page.evaluate(() => {
  const pick = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const s = getComputedStyle(el)
    return {
      selector: sel,
      fontFamily: s.fontFamily,
      fontSize: s.fontSize,
      fontWeight: s.fontWeight,
      lineHeight: s.lineHeight,
      letterSpacing: s.letterSpacing,
      color: s.color,
    }
  }
  return ['h1', 'p', '.ds-container', '.ds-btn-primary', '.ds-header-bar']
    .map(pick)
    .filter(Boolean)
})

console.log('\n参考站实际计算样式：')
for (const item of computed) console.log('  ' + JSON.stringify(item))

await browser.close()
