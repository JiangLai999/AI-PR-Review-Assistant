/**
 * 分段截图：整页太高时会超出图像尺寸上限，这里按屏切片输出。
 *
 * 用法：
 *   node tools/shoot-slices.mjs overview 1440 1000
 *   node tools/shoot-slices.mjs report 1440 1100 3     # 指定切几屏
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../.shots')
const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'

const [, , view = 'overview', wArg = '1440', hArg = '1000', nArg = '4'] = process.argv
const width = Number(wArg)
const height = Number(hArg)

await mkdir(outDir, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 })

const problems = []
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') problems.push(`console: ${m.text()}`)
})
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()}`))

await page.goto(`${BASE}/#/${view}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

// 历史页可以先打开一份报告
if (view === 'report') {
  const btn = page.locator('button:has-text("查看报告")').first()
  if (await btn.count()) {
    await btn.click()
    await page.waitForTimeout(1600)
    const head = page.locator('.finding-head').first()
    if (await head.count()) {
      await head.click()
      await page.waitForTimeout(500)
    }
  }
}

const total = await page.evaluate(() => document.documentElement.scrollHeight)
const shots = Math.min(Number(nArg), Math.max(1, Math.ceil(total / height)))
console.log(`page height: ${total}px -> ${shots} slice(s) at ${width}x${height}`)

for (let i = 0; i < shots; i += 1) {
  const y = i * height
  await page.evaluate((top) => window.scrollTo(0, top), y)
  await page.waitForTimeout(500)
  const file = resolve(outDir, `slice-${view}-${width}-${i + 1}.png`)
  await page.screenshot({ path: file })
  console.log(`  slice ${i + 1} @ y=${y} -> ${file}`)
}

if (problems.length) {
  console.log('运行时问题:')
  for (const p of [...new Set(problems)]) console.log('  ' + p)
} else {
  console.log('无控制台错误、无失败请求。')
}
await browser.close()
