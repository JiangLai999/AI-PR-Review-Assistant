/**
 * 配置助手「仓库上下文」屏的文本证据脚本（任务 claude-tui-repo-context，方案 §4.6）。
 *
 * 用 fixture 渲染**真实**的 `SetupWizardDialog`（不 spawn Python、不读用户配置、不联网），
 * 把这一屏的键盘与载荷走一遍，断言四件事：
 *
 *   A. 选项清单来自后端 `config.options.repo_context.options`（与 `REPO_CONTEXT_MODES` 同序），
 *      预选值 = 后端落盘的当前值（fixture 给 off，就高亮 off，不是推荐档）；
 *   B. ↑↓ 在三个档位之间移动高亮，← 返回上一屏（workbench），与其它单选屏一致；
 *      Esc 是"取消助手"（普通屏语义，不是路由细化页的"返回"）；
 *   C. 确认页多出「仓库上下文 <label>」一行，且确认页加高到 28 后不再截断（首行与页脚都在）；
 *   D. 提交载荷 `config.setup` 带 `repo_context`：选到 tests+imports 就发它；不动的助手发
 *      后端当前值（en-US 场景里 = 推荐档 tests+imports）；旧后端（无 options 块）用兜底表。
 *
 * 运行（在 frontend/tui 下）：
 *
 *   bun --preload @opentui/solid/preload scripts/manual-repo-context-wizard-check.tsx
 *
 * 120x30 的整帧会打印出来，同时存到 TEMP 下的 ai-pr-review-repo-context-check/。
 */
import { testRender } from "@opentui/solid"
import { mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { SetupWizardDialog } from "../src/app"
import type { BackendClient } from "../src/backend"

const outDir = join(tmpdir(), "ai-pr-review-repo-context-check")
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

async function settle(view: { renderOnce: () => Promise<void> }, times = 8) {
  for (let i = 0; i < times; i += 1) {
    await sleep(60)
    await view.renderOnce()
  }
}

const snapshot = {
  runtime_profile: "cloud",
  strategy: "remote_only",
  provider: "deepseek",
  provider_display: "DeepSeek",
  model: "deepseek-flash",
  ui_language: "zh-CN",
  repo_context: "tests+imports",
}

/**
 * `config.options` 的形状照抄后端 `_setup_options()`（只看协议，不 import Python）。
 *
 * `repoContext` 为 `null` 时**不带**该键，模拟旧后端（前端应回落到 setup-repo-context.ts
 * 的兜底表）。
 */
function setupOptions(language: string, repoContext: { value: string } | null) {
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
    ...(repoContext
      ? {
          repo_context: {
            value: repoContext.value,
            // 逐字来自 jsonl_server.REPO_CONTEXT_LABELS / config.REPO_CONTEXT_MODES。
            options: [
              { value: "off", label: "关闭 / Off" },
              { value: "tests", label: "仅测试文件 / Tests only" },
              { value: "tests+imports", label: "测试与依赖 / Tests + imports" },
            ],
          },
        }
      : {}),
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

/** 记录 config.setup 载荷与 onClose 的假后端：不 spawn 进程、不碰磁盘。 */
function stubBackend(
  language: string,
  repoContext: { value: string } | null,
  failOptions = false,
) {
  const state = {
    setupPayload: undefined as Record<string, unknown> | undefined,
    closed: 0,
  }
  const client = {
    request: async (method: string, params: Record<string, unknown> = {}) => {
      if (method === "config.setup") {
        state.setupPayload = params
        return { ok: true, result: snapshot }
      }
      if (failOptions) return { ok: false, error: { message: "读取配置选项超时" } }
      return { ok: true, result: setupOptions(language, repoContext) }
    },
  }
  return { client: client as unknown as BackendClient, state }
}

async function openWizard(
  language: string,
  repoContext: { value: string } | null,
  extra: { failOptions?: boolean; runtime?: Record<string, unknown> } = {},
) {
  const backend = stubBackend(language, repoContext, extra.failOptions === true)
  const view = await testRender(
    () => (
      <box width="100%" height="100%">
        <SetupWizardDialog
          backend={backend.client}
          runtime={{ runtime_profile: "cloud", ui_language: language, ...(extra.runtime ?? {}) }}
          onClose={() => {
            backend.state.closed += 1
          }}
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
  tries = 4,
): Promise<string> {
  for (let i = 0; i < tries; i += 1) {
    view.mockInput.pressEnter()
    await settle(view)
    const frame = view.captureCharFrame()
    if (pattern.test(frame)) return frame
  }
  return view.captureCharFrame()
}

/** 云端预设第 5 阶段前的 13 屏都要按 Enter 才走到「仓库上下文」。 */
async function advanceToRepoContext(view: Parameters<typeof advance>[0]): Promise<string> {
  return advance(view, /仓库上下文 · 审查预取|Repository context · review prefetch/, 20)
}

/** 选项行（select 选中项带 `▶ ` 前缀；描述行缩进 3 列）。 */
function optionRows(frame: string): string[] {
  return frame
    .split("\n")
    .map((line) => line.replace(/[│┌┐└┘─]/g, "").trimEnd())
    .filter((line) => /^\s*[▶ ]\s*(关闭|仅测试文件|测试与依赖|Off|Tests only|Tests \+ imports)\s*$/.test(line))
}

async function zhFlow() {
  console.log("\n[A] zh-CN · 后端当前值 off → 三选一 → 确认页 → 载荷（120x30）")
  const { view, state } = await openWizard("zh-CN", { value: "off" })
  try {
    const frame = await advanceToRepoContext(view)
    console.log(dumpFrame(frame, "repo-context-zh"))
    check(/仓库上下文 · 审查预取/.test(frame), "屏标题随 ui_language 出中文")
    check(/5\/6 · 界面与输出/.test(frame), "这一屏属于第 5 阶段")
    check(/关闭/.test(frame) && /仅测试文件/.test(frame) && /测试与依赖/.test(frame), "三个档位都渲染")
    check(/▶\s*关闭/.test(frame), "预选 = 后端落盘值 off（不是推荐档）")
    check(/off\s*·\s*不读取任何仓库文件/.test(frame), "off 的描述说明零额外请求")
    check(/tests\+imports\s*·\s*测试文件 \+ 它们导入的模块（推荐）/.test(frame), "推荐档带（推荐）标记")
    check(/审查时按此范围预取仓库文件/.test(frame), "屏内提示语（中文，单行不换行）")
    check(/↑↓ 选择 · Enter 下一步 · ← 返回 · Esc 取消/.test(frame), "页脚 = 普通单选屏的键盘说明")
    check(optionRows(frame).length === 3, "选项恰好 3 行", optionRows(frame).join(" | "))

    // ↓↓ 从 off 走到 tests+imports，高亮跟着走。
    view.mockInput.pressArrow("down")
    await settle(view)
    check(/▶\s*仅测试文件/.test(view.captureCharFrame()), "↓ 选中 仅测试文件")
    view.mockInput.pressArrow("down")
    await settle(view)
    const recommended = view.captureCharFrame()
    console.log(dumpFrame(recommended, "repo-context-zh-tests-imports"))
    check(/▶\s*测试与依赖/.test(recommended), "↓↓ 选中 测试与依赖")
    // 再按 ↓ 不越界（select 默认不回绕），仍停在最后一项。
    view.mockInput.pressArrow("down")
    await settle(view)
    check(/▶\s*测试与依赖/.test(view.captureCharFrame()), "最后一项再按 ↓ 不越界")

    // ← 返回上一屏（workbench），再 Enter 回来（选项保持）。
    view.mockInput.pressArrow("left")
    await settle(view)
    const back = view.captureCharFrame()
    check(/选择审查工作台模式/.test(back), "← 返回 workbench 屏")
    const again = await advanceToRepoContext(view)
    check(/▶\s*测试与依赖/.test(again), "返回后选项仍是 测试与依赖")
    check(state.closed === 0, "这一屏的 ← 不会走 Esc 的取消路径")

    const summaryFrame = await advance(view, /确认并保存/)
    console.log(dumpFrame(summaryFrame, "summary-zh"))
    check(/仓库上下文\s+测试与依赖/.test(summaryFrame), "确认页显示「仓库上下文 测试与依赖」")
    check(/运行模式/.test(summaryFrame), "确认页首行还在（28 行高度没截断）")
    check(/Chat 布局/.test(summaryFrame), "确认页最后一条偏好行还在")
    check(/Enter 保存到私有配置/.test(summaryFrame), "确认页提示行没被挤掉")
    check(/Enter 保存 · ← 返回修改 · Esc 取消/.test(summaryFrame), "确认页页脚还在")

    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.repo_context === "tests+imports", "载荷 repo_context=所选项")
    check(payload.runtime_profile === "cloud", "载荷其余字段不受影响")
    check(payload.provider_name === "deepseek", "预设分支仍带 provider_name")
  } finally {
    view.renderer.destroy()
  }
}

async function enFlow() {
  console.log("\n[B] en-US · 后端当前值 tests+imports（不动的助手）→ 英文标签与载荷（120x30）")
  const { view, state } = await openWizard("en-US", { value: "tests+imports" })
  try {
    const frame = await advanceToRepoContext(view)
    console.log(dumpFrame(frame, "repo-context-en"))
    check(/Repository context · review prefetch/.test(frame), "en-US 屏标题")
    check(/▶\s*Tests \+ imports/.test(frame), "预选 = 后端值 tests+imports")
    check(/Tests only/.test(frame) && /\bOff\b/.test(frame), "英文档位名（后端双语 label 取英文侧）")
    check(/关闭|仅测试文件|测试与依赖/.test(frame) === false, "英文屏不混中文选项名")
    check(/tests\+imports\s*·\s*test files \+ their imports \(recommended\)/.test(frame), "英文推荐说明")
    check(/What \/review prefetches from the repo as extra model context\./.test(frame), "屏内提示语（英文，单行不换行）")
    check(/↑↓ 选择 · Enter 下一步 · ← 返回 · Esc 取消/.test(frame), "页脚文案仍与其它屏一致（既有行为，未顺手翻译）")

    // 不动这一屏：直接 Enter 到确认页，载荷应等于后端当前值 = 推荐档。
    const summaryFrame = await advance(view, /确认并保存/)
    check(/Repo ctx\s+Tests \+ imports/.test(summaryFrame), "确认页英文行标签")
    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.repo_context === "tests+imports", "未改动时载荷 = 后端当前值 tests+imports")

    // Esc 在普通屏是"取消助手"（与 ui_language 等屏一致），不是路由细化页的"返回"。
    const { view: view2, state: state2 } = await openWizard("zh-CN", { value: "tests" })
    try {
      const frame2 = await advanceToRepoContext(view2)
      check(/▶\s*仅测试文件/.test(frame2), "新助手把后端值 tests 预选上")
      view2.mockInput.pressEscape()
      await settle(view2, 4)
      check(state2.closed === 1, "Esc 触发 onClose（取消助手），与其它单选屏一致")
    } finally {
      view2.renderer.destroy()
    }
  } finally {
    view.renderer.destroy()
  }
}

async function fallbackFlow() {
  console.log("\n[C] 旧后端（options 无 repo_context 块）→ 兜底表 + 推荐档（120x30）")
  const { view, state } = await openWizard("zh-CN", null)
  try {
    const frame = await advanceToRepoContext(view)
    console.log(dumpFrame(frame, "repo-context-fallback-zh"))
    check(/关闭/.test(frame) && /仅测试文件/.test(frame) && /测试与依赖/.test(frame), "兜底表仍有三个档位")
    check(/▶\s*测试与依赖/.test(frame), "没有当前值时预选推荐档 tests+imports")
    const summaryFrame = await advance(view, /确认并保存/)
    check(/仓库上下文\s+测试与依赖/.test(summaryFrame), "确认页显示兜底 label")
    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.repo_context === "tests+imports", "载荷与后端默认档一致")
  } finally {
    view.renderer.destroy()
  }
}

/**
 * 另外两条预设分支也要能走到这一屏（三个顺序数组都插了新屏）。
 *
 * 本地预设：第 1 屏 ↓ 到「本地」；custom：↓↓↓ 到「自定义」后进细化页——两条路的第 5 阶段
 * 顺序都必须穿过 repo_context，否则这屏对这两类用户就是不可达的。
 */
async function otherPresetsFlow() {
  console.log("\n[D] 本地 / custom 分支也要经过这一屏（回归，120x30, zh-CN）")
  const local = await openWizard("zh-CN", { value: "tests" })
  try {
    local.view.mockInput.pressArrow("down")
    await settle(local.view)
    const frame = await advanceToRepoContext(local.view)
    check(/仓库上下文 · 审查预取/.test(frame), "本地预设顺序里也有这一屏")
    check(/▶\s*仅测试文件/.test(frame), "本地分支同样按后端值预选")
    const summaryFrame = await advance(local.view, /确认并保存/)
    check(/仓库上下文\s+仅测试文件/.test(summaryFrame), "本地预设确认页带这一行")
    local.view.mockInput.pressEnter()
    await settle(local.view)
    check(local.state.setupPayload?.repo_context === "tests", "本地预设载荷带 repo_context")
    check(local.state.setupPayload?.local_provider === "ollama", "本地预设载荷其它字段不变")
  } finally {
    local.view.renderer.destroy()
  }

  const custom = await openWizard("zh-CN", { value: "tests+imports" })
  try {
    for (let i = 0; i < 3; i += 1) custom.view.mockInput.pressArrow("down")
    await advance(custom.view, /路由细化 · 对话模型/)
    await advance(custom.view, /路由细化 · 审查模型/)
    const frame = await advanceToRepoContext(custom.view)
    check(/仓库上下文 · 审查预取/.test(frame), "custom 顺序里也有这一屏")
    check(/▶\s*测试与依赖/.test(frame), "custom 分支预选后端值")
    const summaryFrame = await advance(custom.view, /确认并保存/)
    check(/对话模型\s+云端 deepseek-flash/.test(summaryFrame), "custom 确认页的对话模型行仍在")
    custom.view.mockInput.pressEnter()
    await settle(custom.view)
    const payload = custom.state.setupPayload ?? {}
    check(payload.runtime_profile === "custom", "custom 载荷 runtime_profile=custom")
    check(payload.repo_context === "tests+imports", "custom 载荷带 repo_context")
    check("chat_slot" in payload && "review_slot" in payload, "custom 载荷仍带两个槽位（细化页未被破坏）")
  } finally {
    custom.view.renderer.destroy()
  }
}

/**
 * `config.options` 读取失败时的兜底（独立复核发现的缺陷，见 docs §6 第 3 项）。
 *
 * custom 分支只依赖前端固定的槽位取值，读不到 options 也能走到确认页；那时这一屏的
 * 预选必须来自 `props.runtime.repo_context`（App 把 `model.status` 并进快照后这里是
 * `{value, options}` 对象），否则序号停在初值 0，保存会把落盘的 tests 悄悄改成 off。
 */
async function optionsFailureFlow() {
  console.log("\n[E] config.options 读取失败 + custom 分支 → 预选走快照兜底（120x30, zh-CN）")
  const { view, state } = await openWizard("zh-CN", null, {
    failOptions: true,
    // 形状最坏的一种：model.status 的对象形态被并进快照。
    runtime: {
      repo_context: {
        value: "tests",
        options: [
          { value: "off", label: "关闭 / Off" },
          { value: "tests", label: "仅测试文件 / Tests only" },
          { value: "tests+imports", label: "测试与依赖 / Tests + imports" },
        ],
      },
    },
  })
  try {
    // 读取失败的提示落在**首屏**（错误行在页脚上方；`goTo()` 会清掉它，这是有意设计：
    // 提示属于"出错那一刻的屏幕"，不跨屏残留），所以这里在导航前断言。
    // 2026-09-27 复核：原断言在导航 20 步之后检查同一个字符串，等于要求错误跨屏残留，
    // 与实现相反 → 长期红着（这条"红"曾被误读成"错误提示根本不渲染"）。
    const firstFrame = view.captureCharFrame()
    console.log(dumpFrame(firstFrame, "repo-context-options-failed-first"))
    check(/读取配置选项超时/.test(firstFrame), "错误提示可见（助手没有被读取失败锁死）")
    for (let i = 0; i < 3; i += 1) view.mockInput.pressArrow("down")
    await advance(view, /路由细化 · 对话模型/)
    await advance(view, /路由细化 · 审查模型/)
    const frame = await advanceToRepoContext(view)
    console.log(dumpFrame(frame, "repo-context-options-failed"))
    check(!/读取配置选项超时/.test(frame), "换屏后错误行被清掉（不跨屏残留）")
    check(/▶\s*仅测试文件/.test(frame), "预选 = 快照里的 tests，而不是清单第一项 off")
    const summaryFrame = await advance(view, /确认并保存/)
    check(/仓库上下文\s+仅测试文件/.test(summaryFrame), "确认页也显示快照里的档位")
    view.mockInput.pressEnter()
    await settle(view)
    const payload = state.setupPayload ?? {}
    console.log(`  payload: ${JSON.stringify(payload)}`)
    check(payload.repo_context === "tests", "载荷保住用户的 tests（不被悄悄改成 off）")
    check("chat_slot" in payload, "custom 分支仍然可用（本场景能走到确认页）")
  } finally {
    view.renderer.destroy()
  }
}

async function main() {
  await zhFlow()
  await enFlow()
  await fallbackFlow()
  await otherPresetsFlow()
  await optionsFailureFlow()
  console.log(`\n${failures.length === 0 ? "ALL PASS" : `${failures.length} FAIL`} · frames: ${outDir}`)
  if (failures.length > 0) {
    for (const failure of failures) console.log(`  - ${failure}`)
    process.exitCode = 1
  }
}

await main()
