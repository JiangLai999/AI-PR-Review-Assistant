/**
 * 学习 awwwards 获奖站的设计手法。
 *
 * 流程：列表页 → 各站详情页 → 拿到真实外链 → 打开获奖站并测量
 * 排版刻度、圆角、阴影、动效时长、层级与留白。
 *
 * 用法：node tools/study-awwwards.mjs [站点数]
 * 输出：.shots/awwwards.txt
 */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../.shots')
const limit = Number(process.argv[2] ?? 6)
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36'

await mkdir(outDir, { recursive: true })
const browser = await chromium.launch()
const lines = []
const log = (s = '') => {
  console.log(s)
  lines.push(s)
}

const listing = await browser.newPage({ viewport: { width: 1440, height: 1000 }, userAgent: UA })
await listing.goto('https://www.awwwards.com/websites/sites_of_the_day/', {
  waitUntil: 'domcontentloaded',
  timeout: 60000,
})
await listing.waitForTimeout(5000)

const slugs = await listing.evaluate(() =>
  [...new Set([...document.querySelectorAll('a[href*="/sites/"]')].map((a) => a.getAttribute('href')))]
    .filter((h) => h && h.startsWith('/sites/'))
    .slice(0, 40),
)
log(`=== awwwards 今日站点候选 ${slugs.length} 个 ===`)

// 逐个详情页找真实外链
const targets = []
for (const slug of slugs) {
  if (targets.length >= limit) break
  try {
    await listing.goto('https://www.awwwards.com' + slug, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await listing.waitForTimeout(2000)
    const info = await listing.evaluate(() => {
      const visit = [...document.querySelectorAll('a')].find((a) => {
        const t = (a.textContent || '').toLowerCase()
        const h = a.getAttribute('href') || ''
        return /^https?:\/\//.test(h) && !h.includes('awwwards.com') && /visit|website|live/i.test(t)
      })
      const external = [...document.querySelectorAll('a[href^="http"]')]
        .map((a) => a.getAttribute('href'))
        .filter((h) => h && !h.includes('awwwards.com') && !h.includes('facebook') && !h.includes('twitter') && !h.includes('instagram'))
      return {
        title: document.title.replace(/\s*-\s*Awwwards.*$/, '').slice(0, 70),
        url: visit ? visit.getAttribute('href') : external[0] || null,
      }
    })
    if (info.url) {
      targets.push(info)
      log(`  ✓ ${info.title}  ->  ${info.url}`)
    }
  } catch {
    /* 单个失败不影响整体 */
  }
}

log('')
log('=== 获奖站实测 ===')

/** 从单个获奖站提取可迁移的设计手法。 */
async function measure(url, title) {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1000 }, userAgent: UA })
  try {
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await p.waitForTimeout(3500)
    const d = await p.evaluate(() => {
      const px = (v) => parseFloat(v) || 0
      const body = getComputedStyle(document.body)
      const h1 = document.querySelector('h1')
      const h1s = h1 ? getComputedStyle(h1) : null
      // 字号谱系
      const sizes = {}
      document.querySelectorAll('h1,h2,h3,p,a,button,span').forEach((el) => {
        const s = px(getComputedStyle(el).fontSize)
        if (s >= 8 && s <= 200) sizes[s] = (sizes[s] || 0) + 1
      })
      const topSizes = Object.entries(sizes)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([k]) => Number(k))
        .sort((a, b) => a - b)
      // 圆角谱系
      const radii = {}
      document.querySelectorAll('*').forEach((el) => {
        const r = getComputedStyle(el).borderRadius
        if (r && r !== '0px' && !r.includes('%')) radii[r] = (radii[r] || 0) + 1
      })
      // 过渡时长
      const dur = {}
      document.querySelectorAll('*').forEach((el) => {
        const t = getComputedStyle(el).transitionDuration
        if (t && t !== '0s') dur[t] = (dur[t] || 0) + 1
      })
      // 留白：容器左右内边距
      const containers = [...document.querySelectorAll('main, section, header, .container, [class*="container"]')]
        .slice(0, 6)
        .map((el) => {
          const s = getComputedStyle(el)
          return { pl: s.paddingLeft, pr: s.paddingRight, ml: s.marginLeft, mw: s.maxWidth }
        })
      // 是否使用大面积深沉色作为主背景
      return {
        bodyFont: body.fontFamily.split(',')[0].replace(/"/g, ''),
        bodySize: body.fontSize,
        bg: body.backgroundColor,
        fg: body.color,
        h1: h1s ? { size: h1s.fontSize, weight: h1s.fontWeight, ls: h1s.letterSpacing, lh: h1s.lineHeight } : null,
        topSizes,
        radii: Object.entries(radii).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `${k}(${v})`),
        durations: Object.entries(dur).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k]) => k),
        containers,
        docHeight: document.documentElement.scrollHeight,
        headingsCount: document.querySelectorAll('h1,h2,h3').length,
        imgCount: document.querySelectorAll('img, video, canvas, svg').length,
        textLen: document.body.innerText.length,
      }
    })
    log(`\n--- ${title}`)
    log(`    字体 ${d.bodyFont} ${d.bodySize}   bg=${d.bg}`)
    if (d.h1) log(`    H1   ${d.h1.size} / w${d.h1.weight} / ls${d.h1.ls} / lh${d.h1.lh}`)
    log(`    字号谱系 ${d.topSizes.join(', ')}`)
    log(`    圆角 ${d.radii.join(' , ') || '(无)'}`)
    log(`    过渡 ${d.durations.join(' , ') || '(无)'}`)
    const c = d.containers[0]
    if (c) log(`    容器 padding ${c.pl}/${c.pr}  maxWidth ${c.mw}`)
    log(`    信息量 文本${d.textLen}字 标题${d.headingsCount}个 媒体${d.imgCount}个 页面高${d.docHeight}px`)
    return d
  } catch (e) {
    log(`\n--- ${title}\n    !! 测量失败 ${String(e).slice(0, 80)}`)
    return null
  } finally {
    await p.close()
  }
}

for (const t of targets) {
  await measure(t.url, t.title)
}

await writeFile(resolve(outDir, 'awwwards.txt'), lines.join('\n'), 'utf8')
console.log(`\n-> ${resolve(outDir, 'awwwards.txt')}`)
await browser.close()
