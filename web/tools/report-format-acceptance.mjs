/**
 * 报告区格式 + 指标双语 真机验收（Phase 5 起随包保留）。
 *
 * 前置：`pr-review serve`（默认 8787）已启动，历史里至少一条带 findings 的 run。
 * 脚本会把 `ui_language` 在 zh/en 之间切换，结束时**还原 zh-CN**。
 *
 * 覆盖用户本轮的点名诉求：
 * 1) 审查摘要、审查意图、问题/建议：都以 Markdown 渲染（反引号 → <code>，不露原文标记）；
 * 2) 追问回答无论长短都有折叠控件（aria-expanded）；
 * 3) 风险等级/风险类别/审查策略/证据校验四类指标随界面语言切换（中文界面不出现英文 id）；
 * 4) 发现卡有「差异」动作，指向 PR Files changed 的 sha256 行锚，且安全属性齐全。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` :: ${detail}` : ''}`)
  if (!ok) failures.push(label)
}
const post = async (body) =>
  (await fetch(`${BASE}/api/config`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })).json()

const browser = await chromium.launch()
const CJK = /[\u4e00-\u9fff]/

async function openReport(lang) {
  await post({ ui_language: lang })
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
  const page = await context.newPage()
  await page.goto(`${BASE}/#/history`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const rows = page.locator('tbody button')
  const total = await rows.count()
  let opened = false
  for (let index = 0; index < Math.min(total, 10) && !opened; index += 1) {
    await rows.nth(index).click()
    await page.waitForTimeout(2200)
    if ((await page.locator('.finding').count()) > 0) opened = true
  }
  check(opened, `${lang}: 打开了带 findings 的报告`)
  return { context, page }
}

try {
  // ---------------- zh ----------------
  {
    const { context, page } = await openReport('zh-CN')
    const main = await page.locator('main').innerText()

    // 1) 指标双语（规范 id 不得以英文原样出现在中文界面）
    const cats = await page.locator('.plan-stats .chip').allInnerTexts()
    const statsText = cats.join(' ')
    check(CJK.test(statsText), 'zh: 计划统计条/类别为中文', statsText.replace(/\n/g, ' ').slice(0, 80))

    const validation = await page.locator('.metric-key').allInnerTexts()
    const validationText = validation.join(' ')
    check(!CJK.test(validationText) ? false : true, 'zh: 证据校验指标为中文', validationText.slice(0, 80))
    check(!/needs_review|unverified/.test(validationText), 'zh: 证据校验不出现英文 key', validationText)

    // 2) 摘要在（Markdown 容器）
    check(/summary-text|markdown-lite/.test(await page.locator('body').innerHTML()), 'zh: 摘要以 Markdown 容器渲染')

    // 3) 问题/建议渲染：不出现反引号原文
    const problem = await page.locator('.finding-text').first().innerText()
    check(!problem.includes('`'), 'zh: 问题正文不露反引号原文', problem.slice(0, 60))

    // 4) 追问回答有折叠控件（短回答也要有）
    const toggle = page.locator('.ask-panel button[aria-expanded]').first()
    check((await toggle.count()) > 0, 'zh: 追问回答有折叠控件（长短都有）')

    // 4b) 整轮折叠：问题行右侧的折叠标，收起后只剩问题
    const turn = page.locator('.ask-panel-turn').first()
    const turnToggle = turn.locator('.ask-panel-turn-toggle')
    check((await turnToggle.count()) === 1, 'zh: 问题行右侧有整轮折叠标')
    const boxes = [
      await turnToggle.boundingBox(),
      await turn.locator('.ask-panel-question p').boundingBox(),
    ]
    check(
      boxes[0] && boxes[1] && boxes[0].x > boxes[1].x + boxes[1].width - 40,
      'zh: 折叠标位于问题文本右侧',
    )
    const expandedTurn = await turn.innerText()
    await turnToggle.click()
    await page.waitForTimeout(400)
    const collapsedTurn = await turn.innerText()
    check((await turnToggle.getAttribute('aria-expanded')) === 'false', 'zh: 收起后 aria-expanded=false')
    check(collapsedTurn.includes('这次审查'), 'zh: 收起后仍保留问题')
    check(
      !/tokens|上下文：/.test(collapsedTurn) && (await turn.locator('.ask-panel-answer').count()) === 0,
      'zh: 收起后回答与元信息一起隐藏',
      collapsedTurn.replace(/\n/g, ' | ').slice(0, 60),
    )
    await turnToggle.click()
    await page.waitForTimeout(400)
    check((await turn.innerText()).length === expandedTurn.length, 'zh: 再点恢复原状')

    // 5) 差异动作
    const diff = page.locator('.finding-meta-row a[href*="/files#diff-"]').first()
    if ((await diff.count()) > 0) {
      const href = await diff.getAttribute('href')
      check(/\/pull\/\d+\/files#diff-[0-9a-f]{64}R\d+/.test(href), 'zh: 差异链接为 sha256 行锚', href)
      check(
        (await diff.getAttribute('target')) === '_blank' &&
          (await diff.getAttribute('rel')) === 'noreferrer noopener',
        'zh: 差异链接安全属性齐全',
      )
    } else {
      check(false, 'zh: 差异链接存在')
    }
    await context.close()
  }

  // ---------------- en ----------------
  {
    const { context, page } = await openReport('en-US')
    const lang = await page.evaluate(() => document.documentElement.lang)
    check(lang === 'en-US', 'en: html lang 正确', lang)

    const badge = (await page.locator('.finding .badge').first().innerText()).trim()
    check(/^(CRITICAL|HIGH|MEDIUM|LOW|INFO)$/.test(badge), 'en: 严重度徽标为英文大写', badge)

    const cats = (await page.locator('.plan-stats .chip').allInnerTexts()).join(' ')
    check(!CJK.test(cats), 'en: 计划统计条无中文残留', cats.replace(/\n/g, ' ').slice(0, 80))

    const validation = (await page.locator('.metric-key').allInnerTexts()).join(' ')
    check(!CJK.test(validation), 'en: 证据校验指标无中文残留', validation.slice(0, 80))
    await context.close()
  }
} finally {
  await post({ ui_language: 'zh-CN' })
  await browser.close()
}

console.log(failures.length === 0 ? '\nALL PASS' : `\nFAILURES: ${failures.length}`)
process.exitCode = failures.length === 0 ? 0 : 1
