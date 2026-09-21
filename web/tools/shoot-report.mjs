/**
 * 截取「打开一条历史报告并展开 finding」的历史页，用于检查数据密集视图。
 *
 * 用法：node tools/shoot-report.mjs [viewportWidth] [rowIndex]
 * 需要本地服务已在 8787 运行。
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../.shots')
const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const width = Number(process.argv[2] ?? 1440)
const rowIndex = Number(process.argv[3] ?? 0)

await mkdir(outDir, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width, height: 1200 }, deviceScaleFactor: 2 })
const problems = []
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') problems.push(`console: ${m.text()}`)
})

await page.goto(`${BASE}/#/history`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

const buttons = page.locator('button:has-text("查看报告")')
const count = await buttons.count()
if (count === 0) {
  console.error('没有找到「查看报告」按钮——历史库可能为空。')
  process.exitCode = 1
} else {
  await buttons.nth(Math.min(rowIndex, count - 1)).click()
  await page.waitForTimeout(1800)

  // 展开第一条 finding，触发详情态
  const heads = page.locator('.finding-head')
  const headCount = await heads.count()
  if (headCount > 0) {
    await heads.first().click()
    await page.waitForTimeout(500)
  }

  const file = resolve(outDir, `report-${width}.png`)
  await page.screenshot({ path: file, fullPage: true })
  console.log(`report -> ${file}  (findings: ${headCount})`)
}

if (problems.length) {
  console.log('运行时问题:')
  for (const p of [...new Set(problems)]) console.log('  ' + p)
} else {
  console.log('无控制台错误。')
}
await browser.close()
