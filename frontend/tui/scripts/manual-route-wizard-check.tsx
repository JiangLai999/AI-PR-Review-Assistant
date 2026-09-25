/**
 * 路由细化页的文本证据脚本（任务 claude-tui-route，方案 §4）。
 *
 * 用 fixture 渲染**真实**的 `SetupWizardDialog`（不 spawn Python、不读用户配置、
 * 不联网），把键盘矩阵走一遍，断言三件事：
 *
 *   A. 第 1 屏预设来自后端 `runtime_profiles`（含 custom「自定义」），选它进入细化页；
 *   B. 细化页两屏的两个方框显示 `config.options` 里的模型名，↑↓ 只改焦点方框、
 *      Tab/←→ 换方框、Enter 前进、Esc 返回；
 *   C. 提交载荷：custom 带 `chat_slot`/`review_slot` 且不带 provider/local 字段；
 *      其它预设不带这两个键（旧载荷兼容）。
 *
 * 运行（在 frontend/tui 下）：
 *
 *   bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx
 *
 * 120x30 的整帧会打印出来，同时存到 TEMP 下的 ai-pr-review-route-check/。
 */
import { testRender } from "@opentui/solid"
import { mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { RuntimeStatusLine, SetupWizardDialog } from "../src/app"
import type { BackendClient } from "../src/backend"

const outDir = join(tmpdir(), "ai-pr-review-route-check")
mkdirSync(outDir, { recursive: true })

const failures: string[] = []

function check(condition: boolean, label: string, detail = "") {
  if (condition) {
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` :: ${detail}` : ""}`)
  }
}

function dumpFrame(frame: string, label: string) {
  const safe = label.replace(/[^A-Za-z0-9]+/g, "-")
  const path = join(outDir, `frame-${safe}.txt`)
  writeFileSync(path, frame, "utf8")
  return path
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 细化页五个选项行的文本（对话 2 行 + 审查 3 行，按渲染顺序），
 * 选中行保留 `▸` 前缀。命中 `[▸ ] 云端/本地/混合 + 空白 + 模型名/说明` 的行。
 */
function choiceRows(frame: string): string[] {
  return frame
    .split("\n")
    .map((line) => line.replace(/[│┌┐└┘─]/g, "").trim())
    .filter((line) => /^(▸\s+)?(云端|本地|混合)\s+\S/.test(line))
}

async function settle(view: { renderOnce: () => Promise<void> }, times = 8) {
  for (let i = 0; i < times; i += 1) {
    await sleep(60)
    await view.renderOnce()
  }
}

/**
 * `config.options` 的形状照抄后端 `_setup_options()`（只看协议，不 import Python）。
 */
function setupOptions(language: string) {
  const localModels = ["qwen3.5:4b", "llama3.1:8b"]
  return {
    providers: [
      {
        name: "deepseek",
        display_name: "DeepSeek",
        base_url: "https://api.deepseek.com/v1",
        api_format: "openai",
        env_var: "DEEPSEEK_API_KEY",
        default_model: "deepseek-flash",
        models: ["deepseek-flash", "deepseek-reasoner"],
      },
    ],
    runtime_profiles: [
      { value: "cloud", label: "云端" },
      { value: "local", label: "本地" },
      { value: "hybrid", label: "混合" },
      { value: "custom", label: "自定义" },
    ],
    api_formats: [
      { value: "openai", label: "OpenAI 兼容" },
      { value: "anthropic", label: "Anthropic" },
    ],
    ui_languages: [
      { value: "zh-CN", label: "中文 / Chinese" },
      { value: "en-US", label: "English" },
    ],
    output_formats: [
      { value: "terminal", label: "Terminal" },
      { value: "markdown", label: "Markdown" },
    ],
    chat_layouts: [{ value: "compact", label: "紧凑 / Compact" }],
    workbench_modes: [{ value: "auto", label: "自动 / Auto" }],
    local: {
      provider: "ollama",
      display_name: "Ollama",
      base_url: "http://127.0.0.1:11434/v1",
      api_format: "openai",
      default_model: "qwen3.5:4b",
      models: localModels,
    },
    current: {
      runtime_profile: "cloud",
      strategy: "remote_only",
      provider: "deepseek",
      provider_display: "DeepSeek",
      model: "deepseek-flash",
      remote_provider: "deepseek",
      remote_model: "deepseek-flash",
      remote_base_url: "https://api.deepseek.com/v1",
      remote_api_format: "openai",
      remote_api_key_configured: true,
      local_provider: "ollama",
      local_model: "qwen3.5:4b",
      local_models: localModels,
      ui_language: language,
      response_language: "zh-CN",
      output_format: "terminal",
      auto_publish_comment: false,
      chat_layout: "compact",
      workbench_mode: "auto",
      github_token_configured: true,
    },
    routing: {
      profile: "cloud",
      chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
      review: { slot: "remote", label: "云端", model: "deepseek-flash" },
    },
  }
}

const snapshot = {
  runtime_profile: "cloud",
  strategy: "remote_only",
  provider: "deepseek",
  provider_display: "DeepSeek",
  model: "deepseek-flash",
  ui_language: "zh-CN",
  routing: {
    profile: "cloud",
    chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
    review: { slot: "remote", label: "云端", model: "deepseek-flash" },
  },
}

/** 记录 config.setup 载荷的假后端：不 spawn 进程、不碰磁盘。 */
function stubBackend(language: string) {
  const state = { setupPayload: undefined as Record<string, unknown> | undefined }
  const client = {
    request: async (method: string, params: Record<string, unknown> = {}) => {
      if (method === "config.setup") {
        state.setupPayload = params
        return { ok: true, result: snapshot }
      }
      return { ok: true, result: setupOptions(language) }
    },
  }
  return { client: client as unknown as BackendClient, state }
}

async function openWizard(language: string) {
  const backend = stubBackend(language)
  const view = await testRender(
    () => (
      <box width="100%" height="100%">
        <SetupWizardDialog
          backend={backend.client}
          runtime={{ runtime_profile: "cloud", ui_language: language }}
          onClose={() => {}}
          onApplied={() => {}}
        />
      </box>
    ),
    { width: 120, height: 30, kittyKeyboard: true },
  )
  await settle(view)
  return { view, state: backend.state }
}

/**
 * 按 Enter 直到画面匹配 `pattern`（输入屏的焦点是 50ms 后设置的，第一次 Enter
 * 可能落在还没拿到焦点的输入框上）。
 */
async function advance(
  view: { mockInput: { pressEnter: () => void }; renderOnce: () => Promise<void>; captureCharFrame: () => string },
  pattern: RegExp,
  tries = 3,
): Promise<string> {
  for (let i = 0; i < tries; i += 1) {
    view.mockInput.pressEnter()
    await settle(view)
    const frame = view.captureCharFrame()
    if (pattern.test(frame)) return frame
  }
  return view.captureCharFrame()
}

async function customRouteFlow() {
  console.log("\n[A] custom 预设 → 路由细化页 → 提交载荷（120x30, zh-CN）")
  const { view, state } = await openWizard("zh-CN")
  try {
    const runtimeFrame = view.captureCharFrame()
    check(/自定义/.test(runtimeFrame), "第 1 屏列出后端的 自定义 预设")
    check(/Custom/.test(runtimeFrame) === false, "zh-CN 下预设名不带英文后缀")
    check(/对话与审查都使用云端模型/.test(runtimeFrame), "预设带后端说明文案")
    if (failures.length > 0) console.log(`  帧: ${dumpFrame(runtimeFrame, "runtime-zh")}`)

    // ↓↓↓ → 自定义，Enter 进入细化页第一屏。
    for (let i = 0; i < 3; i += 1) view.mockInput.pressArrow("down")
    const chatFrame = await advance(view, /对话模型/)
    console.log(dumpFrame(chatFrame, "route-chat-zh"))
    check(/路由细化 · 对话模型/.test(chatFrame), "Enter 从预设页进入 route_chat")
    check(/对话模型 · 聊天区使用/.test(chatFrame), "对话模型方框标题")
    check(/云端\s+deepseek-flash/.test(chatFrame), "对话方框显示云端模型名（来自 config.options）")
    check(/本地\s+qwen3\.5:4b/.test(chatFrame), "对话方框显示本地模型名")
    check(/审查模型 · \/review 使用/.test(chatFrame), "同一屏也能看到审查方框")
    check(/混合\s+按文件复杂度自动分流/.test(chatFrame), "审查方框的混合项带分流说明")
    check(/Tab\/←→ 切换方框/.test(chatFrame), "页脚写明 Tab/←→ 换方框")
    check(/Enter 下一步/.test(chatFrame) && /Esc 返回/.test(chatFrame), "页脚写明 Enter/Esc")

    // 焦点在对话方框：↓ 把对话从 云端 移到 本地，审查方框不动。
    view.mockInput.pressArrow("down")
    await settle(view)
    console.log(dumpFrame(view.captureCharFrame(), "route-chat-down"))
    let rows = choiceRows(view.captureCharFrame())
    check(rows[1]?.startsWith("▸") === true, "↓ 改的是对话方框", rows.join(" | "))
    // 审查方框默认也停在第 0 项（云端），所以这里断言"它没被 ↓ 带走"，而不是"没有 ▸"。
    check(/^▸ 云端\s+deepseek-flash/.test(rows[2] ?? ""), "↓ 没有动审查方框", rows.join(" | "))

    // Tab 换到审查方框：↓ 现在改审查（云端 → 本地），对话的选中项保持 本地。
    view.mockInput.pressTab()
    await settle(view)
    view.mockInput.pressArrow("down")
    await settle(view)
    console.log(dumpFrame(view.captureCharFrame(), "route-chat-tab"))
    rows = choiceRows(view.captureCharFrame())
    check(/^▸ 本地\s+qwen3\.5:4b/.test(rows[1] ?? ""), "Tab 后对话方框保持 本地", rows.join(" | "))
    check(/^▸ 本地\s+qwen3\.5:4b/.test(rows[3] ?? ""), "Tab 后 ↓ 改的是审查方框", rows.join(" | "))

    // ← 把焦点交回对话方框：↑ 让对话回绕到 云端，审查仍停在 本地。
    view.mockInput.pressArrow("left")
    await settle(view)
    view.mockInput.pressArrow("up")
    await settle(view)
    console.log(dumpFrame(view.captureCharFrame(), "route-chat-left"))
    rows = choiceRows(view.captureCharFrame())
    check(/^▸ 云端\s+deepseek-flash/.test(rows[0] ?? ""), "← 后 ↑ 改的是对话方框（回绕到 云端）", rows.join(" | "))
    check(/^▸ 本地\s+qwen3\.5:4b/.test(rows[3] ?? ""), "← 不影响审查方框的选择", rows.join(" | "))
    // 再按 ↓ 把对话定回 本地，方便后面断言载荷。
    view.mockInput.pressArrow("down")
    await settle(view)

    // Enter → route_review 第二屏；↓ 在审查方框里选到 混合。
    const reviewFrame = await advance(view, /路由细化 · 审查模型/)
    console.log(dumpFrame(reviewFrame, "route-review-zh"))
    check(/路由细化 · 审查模型/.test(reviewFrame), "Enter 从 route_chat 进入 route_review")
    view.mockInput.pressArrow("down")
    await settle(view)
    console.log(dumpFrame(view.captureCharFrame(), "route-review-down"))
    rows = choiceRows(view.captureCharFrame())
    check(/^▸ 混合\s+按文件复杂度自动分流/.test(rows[4] ?? ""), "审查方框可以选到 混合", rows.join(" | "))
    check(/^▸ 本地\s+qwen3\.5:4b/.test(rows[1] ?? ""), "route_review 上对话方框的选择保持", rows.join(" | "))

    // Esc 返回上一屏（自定义流程里 route_review 的上一屏是 route_chat）。
    view.mockInput.pressEscape()
    await settle(view, 4)
    check(/路由细化 · 对话模型/.test(view.captureCharFrame()), "Esc 从 route_review 退回 route_chat")

    // Enter 前进到 GitHub Token（custom 顺序里细化的下一屏），再一路 Enter 到确认页。
    const githubFrame = await advance(view, /GitHub Token/)
    check(/GitHub Token/.test(githubFrame), "细化页之后进入 GitHub Token（custom 顺序不含 Provider/Key 屏）")
    check(!/API Base URL/.test(githubFrame), "custom 顺序没有 Provider 屏")
    await advance(view, /界面语言/)
    await advance(view, /回复语言/)
    await advance(view, /输出格式|Terminal/)
    await advance(view, /自动发布|GitHub/)
    await advance(view, /Chat 布局|紧凑/)
    const summaryFrame = await advance(view, /确认并保存/)
    console.log(dumpFrame(summaryFrame, "summary-zh"))
    check(/运行模式\s+自定义/.test(summaryFrame), "确认页显示运行模式 = 自定义")
    check(/对话模型\s+本地 qwen3\.5:4b/.test(summaryFrame), "确认页显示对话模型行")
    check(/审查模型\s+混合 \(local↔remote\)/.test(summaryFrame), "确认页显示审查模型行（混合带标记）")
    check(!/本地引擎/.test(summaryFrame), "custom 的确认页不显示会被忽略的本地引擎行")

    const chatLines2 = summaryFrame.split("\n").filter((line) => /运行模式|对话模型|审查模型/.test(line))
    for (const line of chatLines2) console.log(`  | ${line.trim()}`)

    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.runtime_profile === "custom", "载荷 runtime_profile=custom")
    check(payload.chat_slot === "local" && payload.review_slot === "hybrid", "载荷带两个槽位（细化页的选择）")
    check(payload.provider_name === undefined, "custom 载荷不带 provider_name")
    check(payload.local_model === undefined, "custom 载荷不带 local_model")
  } finally {
    view.renderer.destroy()
  }
}

async function presetFlow() {
  console.log("\n[B] 非 custom 预设 → 载荷保持旧形状（120x30, zh-CN）")
  const { view, state } = await openWizard("zh-CN")
  try {
    // 默认选中 云端：Enter 进入 Provider 屏，说明预设分支没有细化页。
    const providerFrame = await advance(view, /选择模型供应商/)
    check(/选择模型供应商/.test(providerFrame), "预设 云端 从预设页直接进入 Provider 屏")
    check(!/对话模型 · 聊天区使用/.test(providerFrame), "预设分支不经过细化页")

    await advance(view, /API Base URL/)
    await advance(view, /选择 API 协议格式|OpenAI 兼容/)
    await advance(view, /API Key/)
    await advance(view, /选择模型/)
    await advance(view, /GitHub Token/)
    await advance(view, /界面语言/)
    await advance(view, /回复语言/)
    await advance(view, /输出格式|Terminal/)
    await advance(view, /自动发布|GitHub/)
    await advance(view, /Chat 布局|紧凑/)
    const summaryFrame = await advance(view, /确认并保存/)
    console.log(dumpFrame(summaryFrame, "summary-preset-zh"))
    check(/运行模式\s+云端/.test(summaryFrame), "预设确认页仍显示 运行模式 云端")
    check(/对话模型\s+云端 deepseek-flash/.test(summaryFrame), "预设确认页预览对话模型")
    check(/审查模型\s+云端 deepseek-flash/.test(summaryFrame), "预设确认页预览审查模型")

    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.runtime_profile === "cloud", "载荷 runtime_profile=cloud")
    check(!("chat_slot" in payload), "非 custom 载荷不含 chat_slot")
    check(!("review_slot" in payload), "非 custom 载荷不含 review_slot")
    check(payload.provider_name === "deepseek", "预设载荷仍带 provider_name")
  } finally {
    view.renderer.destroy()
  }
}

async function englishCopy() {
  console.log("\n[C] en-US 文案（120x30）")
  const { view } = await openWizard("en-US")
  try {
    const runtimeFrame = view.captureCharFrame()
    check(/Custom/.test(runtimeFrame), "en-US 下预设显示 Custom")
    for (let i = 0; i < 3; i += 1) view.mockInput.pressArrow("down")
    const chatFrame = await advance(view, /Chat model/)
    console.log(dumpFrame(chatFrame, "route-chat-en"))
    check(/Route detail · chat model/.test(chatFrame), "en-US 屏标题")
    check(/Chat model · used by the chat pane/.test(chatFrame), "en-US 对话方框标题")
    check(/Review model · used by \/review/.test(chatFrame), "en-US 审查方框标题")
    check(/Hybrid\s+auto-route by complexity/.test(chatFrame), "en-US 混合项说明")
    check(/↑↓ select · Tab\/←→ switch box · Enter next · Esc back/.test(chatFrame), "en-US 页脚键盘说明")
  } finally {
    view.renderer.destroy()
  }
}

/** 本地预设分支回归：细化页/确认页改造不能动到既有的本地流程。 */
async function localPresetFlow() {
  console.log("\n[E] 本地预设分支（回归，120x30, zh-CN）")
  const { view, state } = await openWizard("zh-CN")
  try {
    view.mockInput.pressArrow("down") // 云端 → 本地
    await settle(view)
    const endpointFrame = await advance(view, /本地 Ollama Endpoint/)
    console.log(dumpFrame(endpointFrame, "local-endpoint-zh"))
    check(/本地 Ollama Endpoint/.test(endpointFrame), "本地预设进入本地端点屏")
    check(!/选择模型供应商/.test(endpointFrame), "本地预设不经过 Provider 屏")
    check(!/对话模型 · 聊天区使用/.test(endpointFrame), "本地预设不经过细化页")

    await advance(view, /选择本地模型/)
    await advance(view, /GitHub Token/)
    await advance(view, /界面语言/)
    await advance(view, /回复语言/)
    await advance(view, /输出格式|Terminal/)
    await advance(view, /自动发布/)
    await advance(view, /Chat 布局|紧凑/)
    const summaryFrame = await advance(view, /确认并保存/)
    console.log(dumpFrame(summaryFrame, "summary-local-zh"))
    check(/运行模式\s+本地/.test(summaryFrame), "本地确认页 运行模式 本地")
    check(/对话模型\s+本地 qwen3\.5:4b/.test(summaryFrame), "本地确认页 对话模型行")
    check(/审查模型\s+本地 qwen3\.5:4b/.test(summaryFrame), "本地确认页 审查模型行")
    check(/本地引擎\s+Ollama/.test(summaryFrame), "本地确认页仍显示本地引擎明细")

    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.runtime_profile === "local", "载荷 runtime_profile=local")
    check(payload.local_provider === "ollama", "载荷仍带 local_provider")
    check(!("chat_slot" in payload) && !("review_slot" in payload), "本地载荷不含槽位字段")
  } finally {
    view.renderer.destroy()
  }
}

/** 状态栏（方案 §4.4）：App 的真状态栏连的是真后端，这里用 fixture 渲染同一组件。 */
async function statusLineCases() {
  console.log("\n[D] 状态栏 CHAT/REVIEW（120x2）")
  const cases = [
    {
      label: "custom：chat 云端 + review 本地",
      runtime: {
        runtime_profile: "custom",
        model: "deepseek-flash",
        ui_language: "zh-CN",
        routing: {
          profile: "custom",
          chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
          review: { slot: "local", label: "本地", model: "qwen3.5:4b" },
        },
      },
      expect: /CHAT deepseek-flash · REVIEW qwen3\.5:4b/,
      forbid: /hybrid/,
    },
    {
      label: "hybrid 审查带 local↔remote 标记（zh）",
      runtime: {
        runtime_profile: "hybrid",
        model: "deepseek-flash",
        ui_language: "zh-CN",
        routing: {
          profile: "hybrid",
          chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
          review: { slot: "hybrid", label: "混合", model: "deepseek-flash" },
        },
      },
      expect: /REVIEW 混合 \(local↔remote\)/,
      forbid: /REVIEW deepseek-flash/,
    },
    {
      label: "hybrid 审查（en）",
      runtime: {
        runtime_profile: "hybrid",
        ui_language: "en-US",
        routing: {
          profile: "hybrid",
          chat: { slot: "local", label: "本地", model: "qwen3.5:4b" },
          review: { slot: "hybrid", label: "混合", model: "deepseek-flash" },
        },
      },
      expect: /CHAT qwen3\.5:4b · REVIEW Hybrid \(local↔remote\)/,
      forbid: /REVIEW deepseek-flash/,
    },
    {
      label: "旧后端没有 routing：回落到单模型文案",
      runtime: { runtime_profile: "cloud", model: "deepseek-flash", ui_language: "zh-CN" },
      expect: /就绪 · deepseek-flash/,
      forbid: /CHAT/,
    },
  ] as const

  for (const item of cases) {
    const view = await testRender(
      () => (
        <box width="100%" height="2">
          <RuntimeStatusLine runtime={item.runtime} status="READY" width={120} height={30} />
        </box>
      ),
      { width: 120, height: 2 },
    )
    try {
      await view.renderOnce()
      const frame = view.captureCharFrame()
      console.log(dumpFrame(frame, `status-${item.label}`))
      check(item.expect.test(frame), `状态栏：${item.label}`, frame.trim())
      check(!item.forbid.test(frame), `状态栏不含不该出现的内容：${item.label}`, frame.trim())
      console.log(`  | ${frame.trim()}`)
    } finally {
      view.renderer.destroy()
    }
  }
}

async function main() {
  await customRouteFlow()
  await presetFlow()
  await localPresetFlow()
  await englishCopy()
  await statusLineCases()
  console.log(`\n${failures.length === 0 ? "ALL PASS" : `${failures.length} FAIL`} · frames: ${outDir}`)
  if (failures.length > 0) {
    for (const failure of failures) console.log(`  - ${failure}`)
    process.exitCode = 1
  }
}

await main()
