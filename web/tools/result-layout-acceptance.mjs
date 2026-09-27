/**
 * 审查结果区排版真机验收（Phase 5 起随包保留）：对着**真实运行**的工作台跑。
 *
 * 前置：`pr-review serve`（默认 8787）已启动，历史里至少有一条**带 findings** 的 run
 * （用 `BASE=...` 可换地址）。没有可查验的 run 时优雅 SKIP 并以 0 退出。
 *
 * 覆盖：计划卡统计条与自适应栅格、发现卡 chip 化元信息、GitHub 行锚链接的
 * 「要么完整、要么降级」契约（缺 head_sha 时不得拼出半个链接）。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` :: ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
try {
  await page.goto(`${BASE}/#/history`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.getByRole('button', { name: /查看报告|Open report/i }).first().click()
  await page.waitForTimeout(2500)

  const stats = page.locator('.plan-stats').first()
  if ((await stats.count()) === 0) {
    check(true, 'SKIP：这条 run 没有审查计划（换一条带计划的 run，或用真实审查跑一次）')
  } else {
    const statsText = await stats.innerText()
    check(/(风险|Risk)/i.test(statsText), '计划卡统计条含风险等级', statsText.replace(/\n/g, ' | '))
    check(/(类风险|风险类别|categor)/i.test(statsText), '统计条含风险类别数')
    check(/(策略|strateg)/i.test(statsText), '统计条含策略数')
    check(/(文件|file)/i.test(statsText), '统计条含待审查文件数')

    const wide = await page.locator('.plan-grid-row').first()
      .evaluate((el) => getComputedStyle(el).gridTemplateColumns).catch(() => 'n/a')
    await page.setViewportSize({ width: 600, height: 900 })
    await page.waitForTimeout(400)
    const narrow = await page.locator('.plan-grid-row').first()
      .evaluate((el) => getComputedStyle(el).gridTemplateColumns).catch(() => 'n/a')
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.waitForTimeout(400)
    check(wide !== narrow && wide !== 'n/a', '计划栅格随宽度自适应（窄屏堆叠）', `${wide} → ${narrow}`)
  }

  const meta = page.locator('.finding-meta-row').first()
  if ((await meta.count()) === 0) {
    check(true, 'SKIP：这条 run 没有 findings')
  } else {
    const metaText = await meta.innerText()
    check(!/ · /.test(metaText), '发现元信息不再用硬编码 · 连接', metaText.replace(/\n/g, ' ').slice(0, 90))
    check((await meta.locator('.chip').count()) >= 4, '元信息为多个 chip')
    const link = meta.locator('a.chip-link').first()
    if ((await link.count()) > 0) {
      const href = await link.getAttribute('href')
      check(/github\.com\/.+\/blob\/[0-9a-fA-F]{7,40}\/.+#L\d+/.test(href ?? ''), 'GitHub 行锚链接格式正确', href ?? '')
      check(
        (await link.getAttribute('target')) === '_blank' &&
          (await link.getAttribute('rel')) === 'noreferrer noopener',
        '链接 target/rel 安全属性齐全',
      )
    } else {
      check(!(await page.content()).includes('/blob/'), '缺 head_sha 时退化为纯文本（不拼半个链接）')
    }
  }
} finally {
  await browser.close()
}
console.log(failures.length === 0 ? '\nALL PASS' : `\nFAILURES: ${failures.length}`)
process.exitCode = failures.length === 0 ? 0 : 1
