/**
 * 追问历史真机验收（Phase 5 起随包保留）：对着**真实运行**的工作台跑。
 *
 * 前置：
 * 1) `pr-review serve`（默认 8787）已启动；用 `BASE=...` 可换地址；
 * 2) 历史里**至少有一次带追问记录**的 run（先在报告页追问一轮即可）。
 *    找不到带追问的 run 时脚本会打印 SKIP 并以 0 退出——数据相关的前置条件
 *    不该把回归脚本变成"看运气红"的东西。
 *
 * 覆盖（全部在真实浏览器里断言，不是读代码）：
 * 1) 打开报告 → 追问面板从 `GET /api/chat/history` 回填历史；
 * 2) 头部按**轮**计数并标注已保存；
 * 3) 回答走 MarkdownLite：不再出现反引号原文，行内码渲染成 <code>；
 * 4) 元信息含模型 / 耗时 / token / 时间 / 上下文分层；
 * 5) 「清空记录」有二次确认，取消后记录仍在（不破坏演示数据）。
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

  const rows = page.getByRole('button', { name: /查看报告|Open report/i })
  const total = await rows.count()
  let opened = false
  for (let index = 0; index < Math.min(total, 10) && !opened; index += 1) {
    await rows.nth(index).click()
    await page.waitForTimeout(2000)
    const panel = page.locator('.ask-panel').first()
    const status = await panel.locator('.ask-panel-status').innerText().catch(() => '')
    // "N 轮" 才说明这条 run 真有追问记录
    if (/\d+\s*轮|\d+\s*follow-up/i.test(status)) {
      opened = true
      const text = await panel.innerText()
      check(/已保存|saved/i.test(status), '头部标注已保存', status)
      check(/`/.test(text) === false, '回答不再出现反引号原文（Markdown 已渲染）')
      check((await panel.locator('code').count()) > 0, '行内码渲染成 <code> 元素')
      check(/deepseek|qwen|gpt|claude|glm|mimo/i.test(text), '元信息含模型名')
      check(/\d+\.\d+s/.test(text), '元信息含耗时')
      check(/\d+\s*tokens/i.test(text), '元信息含 token 数')
      check(/上下文：|Context:/i.test(text), '显示注入的上下文分层')
      const clearBtn = panel.getByRole('button', { name: /清空记录|Clear history/i })
      check((await clearBtn.count()) === 1, '有「清空记录」按钮')
      page.once('dialog', (dialog) => void dialog.dismiss())
      await clearBtn.click()
      await page.waitForTimeout(800)
      check(
        /\d+\s*轮|\d+\s*follow-up/i.test(await panel.innerText()),
        '取消清空后记录仍在（未破坏数据）',
      )
    }
  }
  if (!opened) {
    check(true, 'SKIP：前 10 条 run 都没有追问记录（先追问一轮再跑）')
  }
} finally {
  await browser.close()
}

console.log(failures.length === 0 ? '\nALL PASS' : `\nFAILURES: ${failures.length}`)
process.exitCode = failures.length === 0 ? 0 : 1
