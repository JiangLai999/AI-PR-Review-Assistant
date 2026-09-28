/**
 * 设置页真机验收（Phase 2 起随包保留）：对着**真实运行**的本地工作台跑。
 *
 * 前置：`pr-review serve`（默认 8787）已启动；用 `BASE=...` 可换地址。
 * 副作用（会被还原）：把 `preferences.ui_language` 临时改成另一种语言，验证落盘后再改回原值；
 * 失败时 `finally` 里同样会还原，净零变更。
 *
 * 1) `GET /api/config` 必须带 preferences/options/runtime_profile；
 * 2) 设置页渲染 6 个新控件且初值来自 preferences；
 * 3) 改一项 → 点保存 → 回读确认落盘；
 * 4) **把改动还原**（净零变更）。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` :: ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

const getConfig = async () => {
  const response = await fetch(`${BASE}/api/config`)
  return response.json()
}
const saveConfig = async (payload) => {
  const response = await fetch(`${BASE}/api/config`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return { status: response.status, body: await response.json() }
}

const before = await getConfig()
check(Boolean(before.preferences), 'GET /api/config 带 preferences')
check(Boolean(before.options), 'GET /api/config 带 options')
check(Boolean(before.runtime_profile), 'GET /api/config 带 runtime_profile')
for (const key of [
  'ui_languages',
  'output_formats',
  'chat_layouts',
  'workbench_modes',
  'repo_contexts',
  'review_efforts',
]) {
  const items = before.options?.[key]
  check(Array.isArray(items) && items.length > 0 && 'value' in (items[0] ?? {}), `options.${key} 是 {value,label} 列表`)
}

const originalLang = before.preferences?.ui_language ?? 'zh-CN'
const otherLang = originalLang.toLowerCase().startsWith('en') ? 'zh-CN' : 'en-US'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
try {
  await page.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)

  const prefIds = [
    'pref-ui_language',
    'pref-output_format',
    'pref-chat_layout',
    'pref-workbench_mode',
    'pref-repo_context',
    'pref-review_reasoning_effort',
  ]
  let found = 0
  for (const id of prefIds) {
    const select = page.locator(`#${id}`)
    if ((await select.count()) > 0 && !(await select.isDisabled())) found += 1
  }
  check(found === 6, '6 个偏好下拉全部渲染且可用', `实际 ${found}/6`)

  const groupVisible = await page.getByText('界面与输出', { exact: false }).count()
  check(groupVisible > 0, '出现「界面与输出」分组')

  // 改界面语言
  const langSelect = page.locator('#pref-ui_language')
  check(
    (await langSelect.inputValue()) === originalLang,
    '下拉初值来自 preferences',
    `期望 ${originalLang}，实际 ${await langSelect.inputValue()}`,
  )
  await langSelect.selectOption(otherLang)
  // 「直接保存」= save(false)：不触发凭证网络探测（探查走 save(true) 的「校验后保存」）
  await page.getByRole('button', { name: '直接保存' }).first().click()
  await page.waitForTimeout(2500)

  const after = await getConfig()
  check(
    after.preferences?.ui_language === otherLang,
    '保存后落盘生效',
    `期望 ${otherLang}，实际 ${after.preferences?.ui_language}`,
  )
  const notice = await page.getByText(/保存|已更新/, { exact: false }).count()
  check(notice > 0, '页面出现保存结果提示')
} finally {
  // 还原（净零变更）
  const restored = await saveConfig({ ui_language: originalLang })
  const final = await getConfig()
  check(
    restored.status === 200 && final.preferences?.ui_language === originalLang,
    '还原原始界面语言',
    `status=${restored.status} value=${final.preferences?.ui_language}`,
  )
  await browser.close()
}

console.log(failures.length === 0 ? '\nALL PASS' : `\nFAILURES: ${failures.length}`)
process.exitCode = failures.length === 0 ? 0 : 1
