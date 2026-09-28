/**
 * 后端文案双语化真机验收（Phase 4 起随包保留）：对着**真实运行**的本地工作台跑。
 *
 * 前置：`pr-review serve`（默认 8787）已启动；用 `BASE=...` 可换地址。
 * 副作用（会被还原）：把 `preferences.ui_language` 临时改成 `en-US`，验完改回原值；
 * 失败时 `finally` 里同样还原，净零变更。
 *
 * 覆盖三件事（都是"后端生成、前端渲染"的文案）：
 * 1) `GET /api/credentials` 每项带 `label_key/detail_key`（key 能被前端词典消费）；
 * 2) `POST /api/config` 带 `message_key/message_params`；
 * 3) 英文界面下这些文案真的出英文——不含**非刻意**的中文残留。
 *
 * 刻意的中文残留：6 组偏好下拉的 `label`（如「紧凑 / Compact」）由后端
 * `PREFERENCE_OPTION_LABELS` 给出，与 TUI 文案逐字对齐（漂移用例锁死），
 * 因此这里按"接口原样发出来的 label"做白名单，而不是无脑放过所有中文。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8787'
const CJK = /[\u4e00-\u9fff]/
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` :: ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

const getConfig = async () => (await fetch(`${BASE}/api/config`)).json()
const saveConfig = async (payload) => {
  const response = await fetch(`${BASE}/api/config`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return { status: response.status, body: await response.json() }
}

/** 接口自己发出来的下拉 label —— 它们天生含中文，属于契约而非漏翻。 */
const intentionalLabels = new Set(
  Object.values((await getConfig()).options ?? {})
    .filter(Array.isArray)
    .flat()
    .map((item) => String(item?.label ?? '')),
)

// 后端契约：结构化键必须随响应一起回来
const configPayload = await getConfig()
check(Boolean(configPayload.preferences), 'GET /api/config 正常')
const creds = await (await fetch(`${BASE}/api/credentials?probe=0`)).json()
const firstItem = creds.items?.[0] ?? {}
check(Boolean(firstItem.label_key), '凭证项带 label_key', String(firstItem.label_key))
check(Boolean(firstItem.detail_key), '凭证项带 detail_key', String(firstItem.detail_key))

const missingKeys = (creds.items ?? [])
  .filter((item) => !item.label_key || !item.detail_key)
  .map((item) => item.key)
check(missingKeys.length === 0, '每一项凭证都带结构化键', missingKeys.join(','))

const original = configPayload.preferences?.ui_language ?? 'zh-CN'
const switched = await saveConfig({ ui_language: 'en-US' })
check(
  switched.status === 200 && switched.body.message_key === 'config.save.saved',
  '保存响应带 message_key + params',
  JSON.stringify(switched.body.message_params),
)
check(
  Object.keys(switched.body.message_params ?? {}).length > 0,
  'config.save.saved 带占位符参数',
)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
try {
  await page.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)

  const bodyText = await page.locator('main').innerText()
  const leftovers = bodyText
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => CJK.test(line) && !intentionalLabels.has(line))
  check(
    leftovers.length === 0,
    '英文界面无非刻意中文残留',
    leftovers.slice(0, 4).join(' | '),
  )

  // 凭证面板：本轮的目标区域，单独再卡一遍
  const credentialCard = await page
    .locator('.card')
    .filter({ hasText: /Credential/i })
    .first()
    .innerText()
    .catch(() => '')
  check(
    credentialCard.length > 0 && !CJK.test(credentialCard),
    '凭证面板全英文',
    credentialCard.replace(/\n+/g, ' | ').slice(0, 140),
  )
  check(/reachable|Connected to|Configured|not configured|working/i.test(credentialCard), '凭证状态文案为英文')

  // 直接保存（无改动）→ config.save.noop 的英文文案
  await page
    .getByRole('button', { name: /Save/ })
    .first()
    .click()
    .catch(() => {})
  await page.waitForTimeout(2500)
  const afterSave = await page.locator('main').innerText()
  check(/Nothing to save/i.test(afterSave), '无改动保存提示为英文（config.save.noop）')
} finally {
  const restored = await saveConfig({ ui_language: original })
  check(restored.status === 200, '还原原始界面语言', `value=${restored.body?.config?.preferences?.ui_language}`)
  await browser.close()
}

console.log(failures.length === 0 ? '\nALL PASS' : `\nFAILURES: ${failures.length}`)
process.exitCode = failures.length === 0 ? 0 : 1
