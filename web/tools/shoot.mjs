/**
 * 本地工作台截图工具。
 *
 * 用途：让开发者（含 AI 代理）能在没有图形界面的环境里看到真实渲染结果，
 * 而不是凭 CSS 数值推断界面长什么样。
 *
 * 用法：
 *   node tools/shoot.mjs                  # 截全站五个视图
 *   node tools/shoot.mjs review 1440x2200 # 指定视图与视口
 *   BASE=http://127.0.0.1:8787 node tools/shoot.mjs
 *
 * 输出：.shots/<view>-<width>.png，并打印每个页面的控制台错误。
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../.shots')
const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'

const VIEWS = [
  ['overview', '#/overview'],
  ['review', '#/review'],
  ['history', '#/history'],
  ['benchmark', '#/benchmark'],
  ['api', '#/api'],
  ['settings', '#/settings'],
]

const [, , onlyView, sizeArg] = process.argv
const [width, height] = (sizeArg ?? '1440x1200').split('x').map(Number)
// 移动端整页截图会超出图像尺寸上限，用 FULL=0 只截首屏。
const FULL_PAGE = process.env.FULL !== '0'

async function main() {
  await mkdir(outDir, { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 2,
    locale: 'zh-CN',
  })
  const page = await context.newPage()

  const problems = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console.error: ${msg.text()}`)
  })
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`))
  page.on('requestfailed', (req) =>
    problems.push(`requestfailed: ${req.url()} (${req.failure()?.errorText})`),
  )

  const targets = onlyView ? VIEWS.filter(([name]) => name === onlyView) : VIEWS
  if (targets.length === 0) {
    console.error(`unknown view: ${onlyView}. available: ${VIEWS.map((v) => v[0]).join(', ')}`)
    process.exitCode = 1
    await browser.close()
    return
  }

  for (const [name, hash] of targets) {
    await page.goto(`${BASE}/${hash}`, { waitUntil: 'networkidle' })
    // 等入场动画与数据请求落定
    await page.waitForTimeout(900)
    const suffix = FULL_PAGE ? '' : '-vp'
    const file = resolve(outDir, `${name}-${width}${suffix}.png`)
    await page.screenshot({ path: file, fullPage: FULL_PAGE })

    const title = await page.title()
    const bodyText = await page.evaluate(() => document.body.innerText.length)
    console.log(`${name.padEnd(10)} -> ${file}  (title="${title}", ${bodyText} chars of text)`)
  }

  if (problems.length) {
    console.log('\n运行时问题:')
    for (const problem of [...new Set(problems)]) console.log('  ' + problem)
    await writeFile(resolve(outDir, 'problems.txt'), [...new Set(problems)].join('\n'), 'utf8')
  } else {
    console.log('\n无控制台错误、无失败请求。')
  }

  await browser.close()
}

await main()
