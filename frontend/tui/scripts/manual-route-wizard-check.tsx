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
 * `extra` 用来叠加 B2/B3 的新块（`model` / `custom_endpoint` / `routing`）。
 */
function setupOptions(language: string, extra: Record<string, unknown> = {}) {
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
    // B2/B3 的扩展块（§2.2/§2.6）：旧后端没有这两块，所以默认不塞；
    // [F]/[G] 两节按需注入 fixture，既有的 [A]/[B]/[C]/[E] 仍走"旧后端"形状。
    ...extra,
  }
}

/** custom 预设的 routing 快照：`presetIndexOf` 优先读 `routing.profile`（方案 §4.2）。 */
const customRouting = {
  profile: "custom",
  chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
  review: { slot: "remote", label: "云端", model: "deepseek-flash" },
}

/**
 * `config.options.model` 的完整形状（方案 §2.2）：顶层描述**活跃槽**，
 * `slots.remote` / `slots.local` 给每槽明细（驱动规格屏的 4 行 + 边界提示）。
 */
function modelSpecFixture(overrides: Record<string, unknown> = {}) {
  return {
    provider: "deepseek",
    model: "deepseek-flash",
    source: "models.dev",
    context_window: 128000,
    max_output: 8192,
    reasoning: "档位 low/high/max · 开关",
    needs_verification: true,
    endpoint_matches_preset: true,
    catalog: { context_window: 1000000, max_output: 393216, source: "models.dev" },
    bounds: { context_window: [1024, 10000000], max_output: [1, 10000000] },
    catalog_state: { enabled: true, source: "models.dev" },
    slots: {
      remote: {
        provider: "deepseek",
        model: "deepseek-flash",
        context_window: 128000,
        max_output: 8192,
        bounds: { context_window: [1024, 10000000] },
      },
      local: { provider: "ollama", model: "qwen3.5:4b", context_window: 32768, max_output: 4096 },
    },
    ...overrides,
  }
}

/**
 * 远端槽改了规格的 fixture（R 重新获取用）：顶层与 `slots.remote` 必须一起改——
 * 编辑框的初值读的是 `slots.remote`（`primeSpecFields`），顶层只喂头行与徽标。
 */
function modelSpecFixtureWithRemote(contextWindow: number, source: string) {
  const base = modelSpecFixture()
  return modelSpecFixture({
    context_window: contextWindow,
    source,
    slots: { ...base.slots, remote: { ...base.slots.remote, context_window: contextWindow } },
  })
}

/** `config.options.custom_endpoint` 的完整形状（方案 §2.6）。 */
const customEndpointFixture = {
  name: "custom",
  display_name: "Custom Endpoint",
  base_url: "https://relay.example.com/v1",
  api_format: "openai",
  default_model: "relay-model",
  api_key_configured: true,
  models: ["relay-model"],
  context_window: 200000,
  max_output: 16384,
  source: "unknown",
  needs_verification: false,
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
function stubBackend(language: string, extraOptions: Record<string, unknown> = {}) {
  const state = {
    setupPayload: undefined as Record<string, unknown> | undefined,
    /**
     * B2 的 R 按钮（方案 §2.1）的假响应。undefined = 成功但没有新目录块
     * （旧后端）；{ error } = 失败，文案原样进 "目录刷新失败，已保留旧值 · …"。
     */
    catalogRefresh: undefined as { model?: unknown; error?: string } | undefined,
  }
  const client = {
    request: async (method: string, params: Record<string, unknown> = {}) => {
      if (method === "config.setup") {
        state.setupPayload = params
        return { ok: true, result: snapshot }
      }
      if (method === "config.catalog.refresh") {
        if (state.catalogRefresh?.error) {
          return { ok: false, error: { message: state.catalogRefresh.error } }
        }
        return { ok: true, result: { model: state.catalogRefresh?.model } }
      }
      return { ok: true, result: setupOptions(language, extraOptions) }
    },
  }
  return { client: client as unknown as BackendClient, state }
}

async function openWizard(
  language: string,
  extraOptions: Record<string, unknown> = {},
  size: { width: number; height: number } = { width: 120, height: 30 },
) {
  const backend = stubBackend(language, extraOptions)
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
    { width: size.width, height: size.height, kittyKeyboard: true },
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

/** 屏幕上的 `▸` 焦点行（去掉边框字符后按内容匹配）。 */
function focusRows(frame: string, pattern: RegExp): string[] {
  return frame
    .split("\n")
    .map((line) => line.replace(/[│┌┐└┘─]/g, "").trim())
    .filter((line) => pattern.test(line))
}

/** 规格屏编辑框里的文本（整行只有数字的那些行；行摘要带标签，不会误命中）。 */
function editBoxValues(frame: string): string[] {
  return frame
    .split("\n")
    .map((line) => line.replace(/[│┌┐└┘─]/g, "").trim())
    .filter((line) => /^\d+$/.test(line))
}

/**
 * 用给定 source 打开「模型规格」屏（custom 预设顺序：runtime → route_chat →
 * route_review → model_spec，3 次 Enter）并返回 120×30 帧。
 */
async function specFrameForSource(language: string, source?: string) {
  const { view } = await openWizard(language, {
    model: modelSpecFixture(source === undefined ? { source: undefined } : { source }),
    routing: customRouting,
  })
  // 屏标题跟 ui_language 走（bilingualScreenTitle）：en-US 下是 "Model spec"。
  const title = String(language).toLowerCase().startsWith("en") ? /Model spec/ : /模型规格/
  try {
    const frame = await advance(view, title, 5)
    console.log(dumpFrame(frame, `spec-source-${String(source ?? "missing")}-${language}`))
    return frame
  } finally {
    view.renderer.destroy()
  }
}

/**
 * B2 模型规格屏的帧证据（docs/mimo-config-wizard-ui.md）。
 *
 * 覆盖：120×30 与 209×51 两个尺寸、source 徽标三态 + unknown、
 * `needs_verification` 的双数字提示、`bounds` 边界提示、本地槽行。
 */
async function specScreenFrames() {
  console.log("\n[F] B2 模型规格屏：规格数据 / source 徽标 / needs_verification（zh-CN, custom 顺序）")
  const options = { model: modelSpecFixture(), routing: customRouting }

  const narrow = await openWizard("zh-CN", options)
  try {
    const frame = await advance(narrow.view, /模型规格/, 5)
    console.log(dumpFrame(frame, "spec-120x30"))
    check(/模型规格/.test(frame), "custom 顺序：route_review 之后进入模型规格屏")
    check(/deepseek · deepseek-flash/.test(frame), "规格头行 = provider · model")
    check(/models\.dev ✓/.test(frame), "source 徽标：models.dev ✓")
    check(/上下文长度\s+128000\s+范围 1024–10000000/.test(frame), "远端上下文长度 + 编辑边界提示")
    check(/最大输出\s+8192/.test(frame), "远端最大输出")
    check(/本地上下文\s+32768/.test(frame), "本地槽上下文长度（slots.local 存在才显示）")
    check(/本地最大输出\s+4096/.test(frame), "本地槽最大输出")
    check(
      /与官方数据不一致：当前 128000 \/ models\.dev 1000000/.test(frame),
      "needs_verification 摆出两个数字（当前值 / 目录值）",
    )
    check(/推理能力\s+档位 low\/high\/max · 开关/.test(frame), "reasoning 摘要行")
    check(/R 重新获取 · ↑↓ 编辑字段 · Enter 下一步 · Esc 返回/.test(frame), "页脚键盘说明")
  } finally {
    narrow.view.renderer.destroy()
  }

  const wide = await openWizard("zh-CN", options, { width: 209, height: 51 })
  try {
    const frame = await advance(wide.view, /模型规格/, 5)
    console.log(dumpFrame(frame, "spec-209x51"))
    check(/deepseek · deepseek-flash/.test(frame), "209×51 规格头行")
    check(/models\.dev ✓/.test(frame), "209×51 source 徽标")
    check(/上下文长度\s+128000/.test(frame), "209×51 远端上下文长度")
    check(
      /与官方数据不一致：当前 128000 \/ models\.dev 1000000/.test(frame),
      "209×51 needs_verification 双数字",
    )
  } finally {
    wide.view.renderer.destroy()
  }

  const cacheFrame = await specFrameForSource("zh-CN", "cache")
  check(/deepseek · deepseek-flash\s+缓存/.test(cacheFrame), "source=cache → 徽标「缓存」")
  // 反向：徽标位不能写 models.dev（needs_verification 那行的 "models.dev 1000000" 是数据来源说明，不算）。
  check(!/deepseek · deepseek-flash\s+models\.dev/.test(cacheFrame), "cache 徽标不冒充 models.dev")

  const builtinFrame = await specFrameForSource("zh-CN", "builtin")
  check(/deepseek · deepseek-flash\s+内置/.test(builtinFrame), "source=builtin → 徽标「内置」")

  const unknownFrame = await specFrameForSource("zh-CN", "unknown")
  check(/deepseek · deepseek-flash\s+未知/.test(unknownFrame), "source=unknown → 徽标「未知」")

  const missingFrame = await specFrameForSource("zh-CN")
  check(/deepseek · deepseek-flash\s+未知/.test(missingFrame), "source 缺失（旧后端）→ 徽标「未知」")

  const englishFrame = await specFrameForSource("en-US", "builtin")
  check(/Model spec/.test(englishFrame), "en-US 屏标题 Model spec")
  check(/deepseek · deepseek-flash\s+builtin/.test(englishFrame), "en-US source=builtin → 徽标 builtin")

  // R 重新获取（§2.1/§6.6）：成功 → 编辑框改用新目录值 + 一行状态；失败 → 保留旧值 + 原因。
  const refreshed = await openWizard("zh-CN", {
    model: modelSpecFixture({ context_window: 128000, source: "builtin" }),
    routing: customRouting,
  })
  try {
    await advance(refreshed.view, /模型规格/, 5)
    refreshed.state.catalogRefresh = { model: modelSpecFixtureWithRemote(1000000, "models.dev") }
    refreshed.view.mockInput.pressKey("r")
    await settle(refreshed.view)
    const frame = refreshed.view.captureCharFrame()
    console.log(dumpFrame(frame, "spec-refresh-ok-zh"))
    check(/目录已刷新 · models\.dev ✓/.test(frame), "R 重新获取成功 → 状态行带新来源")
    check(/上下文长度\s+1000000/.test(frame), "刷新成功后编辑框改用目录值")
    check(/deepseek · deepseek-flash\s+models\.dev ✓/.test(frame), "刷新成功后 source 徽标更新")
    check(editBoxValues(frame).includes("1000000"), "刷新后输入框本身也是新值（不只是行摘要）")
    // 刷新会让本屏重绘：紧接着按 ↓（= 先回写当前字段再换行）必须仍然活着，
    // 且回写的是刷新后的值（这条正是"输入框被重建后 ref 失效"的探针）。
    refreshed.view.mockInput.pressArrow("down")
    await settle(refreshed.view)
    const afterDown = refreshed.view.captureCharFrame()
    console.log(dumpFrame(afterDown, "spec-refresh-then-down-zh"))
    check(/▸ 最大输出\s+8192/.test(afterDown), "刷新后 ↓ 仍能换字段（焦点到最大输出）")
    check(/上下文长度\s+1000000/.test(afterDown), "刷新后 ↓ 回写的是新目录值")
    check(editBoxValues(afterDown).join(",") === "8192", "换字段后输入框装的是新字段的值", editBoxValues(afterDown).join(","))
  } finally {
    refreshed.view.renderer.destroy()
  }

  const refreshFailed = await openWizard("zh-CN", { model: modelSpecFixture(), routing: customRouting })
  try {
    await advance(refreshFailed.view, /模型规格/, 5)
    refreshFailed.state.catalogRefresh = { error: "models.dev 不可达" }
    refreshFailed.view.mockInput.pressKey("r")
    await settle(refreshFailed.view)
    const frame = refreshFailed.view.captureCharFrame()
    console.log(dumpFrame(frame, "spec-refresh-error-zh"))
    check(
      /目录刷新失败，已保留旧值 · Error: models\.dev 不可达/.test(frame),
      "R 重新获取失败 → 保留旧值 + 原因",
    )
    check(/上下文长度\s+128000/.test(frame), "刷新失败后编辑框仍是旧值")
  } finally {
    refreshFailed.view.renderer.destroy()
  }
}

/**
 * B3 中转站五项表单的帧证据（docs/mimo-config-wizard-ui.md）。
 *
 * 这一屏只在 cloud/local 顺序里（custom 顺序没有它）：runtime → provider → base_url →
 * api_format → api_key → model → model_spec → custom_endpoint，7 次 Enter。
 */
async function customEndpointForm() {
  console.log("\n[G] B3 中转站五项表单（fixture: custom_endpoint 满值；120×30, zh-CN）")
  const { view, state } = await openWizard("zh-CN", {
    model: modelSpecFixture(),
    custom_endpoint: customEndpointFixture,
  })
  const fieldRows = /^(▸\s+)?(Base URL|API Key|模型名|上下文长度|最大输出)\s/
  try {
    const frame = await advance(view, /中转站配置/, 10)
    console.log(dumpFrame(frame, "custom-endpoint-zh"))
    check(/中转站配置/.test(frame), "cloud 顺序：model_spec 之后进入中转站屏")
    // 进度条不能倒退：上一屏 model_spec 是 3/6，这一屏也是第 3 阶段（凭据与模型）。
    check(/3\/6 · 凭据与模型 · 中转站配置/.test(frame), "中转站屏与 model_spec 同属第 3 阶段")
    check(/Custom Endpoint/.test(frame), "端点显示名（custom_endpoint.display_name）")
    check(/Key 已配置/.test(frame), "api_key_configured=true → Key 已配置")
    let rows = focusRows(frame, fieldRows)
    check(/^▸ Base URL\s+https:\/\/relay\.example\.com\/v1/.test(rows[0] ?? ""), "五项之一 base_url 预填", rows.join(" | "))
    check(/^API Key\s+••••/.test(rows[1] ?? ""), "五项之二 api_key 行（掩码回显，不打印密钥）", rows.join(" | "))
    check(/^模型名\s+relay-model/.test(rows[2] ?? ""), "五项之三 模型名", rows.join(" | "))
    check(/^上下文长度\s+200000/.test(rows[3] ?? ""), "五项之四 上下文长度", rows.join(" | "))
    check(/^最大输出\s+16384/.test(rows[4] ?? ""), "五项之五 最大输出", rows.join(" | "))
    check(/↑↓ 切换字段 · Enter 下一步 · Esc 返回/.test(frame), "页脚键盘说明")

    // ↓ 把焦点移到下一项：焦点行跟随，行内容不变（回写的是同一份值）。
    view.mockInput.pressArrow("down")
    await settle(view)
    const downFrame = view.captureCharFrame()
    console.log(dumpFrame(downFrame, "custom-endpoint-down"))
    rows = focusRows(downFrame, fieldRows)
    check(/^▸ API Key/.test(rows[1] ?? ""), "↓ 焦点移到 API Key 行", rows.join(" | "))
    check(/^Base URL\s+https:\/\/relay\.example\.com\/v1/.test(rows[0] ?? ""), "↓ 不改动上一行的值", rows.join(" | "))

    // 继续 ↓ 到「上下文长度」：出现该槽的边界提示（来自 remoteSpec().bounds）。
    for (let i = 0; i < 2; i += 1) view.mockInput.pressArrow("down")
    await settle(view)
    const boundsFrame = view.captureCharFrame()
    console.log(dumpFrame(boundsFrame, "custom-endpoint-bounds"))
    rows = focusRows(boundsFrame, fieldRows)
    check(/^▸ 上下文长度/.test(rows[3] ?? ""), "↓↓ 焦点移到 上下文长度", rows.join(" | "))
    check(/范围 1024–10000000/.test(boundsFrame), "焦点在规格字段时显示编辑边界")

    // Esc 回上一屏：中转站屏的上一屏是模型规格屏。
    view.mockInput.pressEscape()
    await settle(view, 4)
    check(/模型规格/.test(view.captureCharFrame()), "Esc 从中转站退回模型规格屏")

    // 观测（不判定）：带 custom_endpoint 预填值时，云端流程保存的载荷长什么样。
    // 它会带上 provider_name:"custom"（把远端槽切到中转站），而确认页仍显示预设的
    // Provider——这个不对称是 docs/mimo-config-wizard-ui.md §6.1 的未决项，
    // 由实现者/用户决定收口方式，这里只留证据、不锁死语义。
    const githubFrame = await advance(view, /GitHub Token/, 4)
    check(/GitHub Token/.test(githubFrame), "中转站屏之后进入 GitHub Token 屏")
    await advance(view, /界面语言/)
    await advance(view, /回复语言/)
    await advance(view, /输出格式|Terminal/)
    await advance(view, /自动发布|GitHub/)
    await advance(view, /Chat 布局|紧凑/)
    const summaryFrame = await advance(view, /确认并保存/)
    console.log(dumpFrame(summaryFrame, "summary-custom-endpoint-zh"))
    view.mockInput.pressEnter()
    await settle(view)
    console.log(`  观测 payload（不判定）: ${JSON.stringify(state.setupPayload ?? {})}`)
    check(state.setupPayload !== undefined, "中转站流程同样能走到确认页并提交（载荷已记录）")
  } finally {
    view.renderer.destroy()
  }
}

async function main() {
  await customRouteFlow()
  await presetFlow()
  await localPresetFlow()
  await englishCopy()
  await specScreenFrames()
  await customEndpointForm()
  await statusLineCases()
  console.log(`\n${failures.length === 0 ? "ALL PASS" : `${failures.length} FAIL`} · frames: ${outDir}`)
  if (failures.length > 0) {
    for (const failure of failures) console.log(`  - ${failure}`)
    process.exitCode = 1
  }
}

await main()
