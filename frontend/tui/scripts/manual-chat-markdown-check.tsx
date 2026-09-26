/**
 * Chat Markdown 渲染的文本证据脚本。
 *
 * 背景（用户实测反馈）：TUI 之前把 assistant 回复当**纯文本**渲染，于是
 * `##`、`**`、`| 表格 |` 全部原样显示，很影响观感。现在改用 OpenTUI 自带的
 * `<markdown>`（mimo-code 用的也是它），本脚本渲染一段真实形态的回复，断言：
 *
 *   A. `**粗体**` 与 `` `代码` `` 的标记符被隐藏（conceal 生效）；
 *   B. `## 标题` 不再出现裸 `##`；
 *   C. Markdown 表格被渲染成表格（出现边框字符），且不出现裸管道分隔行
 *      `|---|---|`；
 *   D. 渲染宽度受限于给定 width（120x30 下不溢出）。
 *
 * 运行（在 frontend/tui 下）：
 *
 *   bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx
 */
import { testRender } from "@opentui/solid"
import { mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { chatMarkdownStyle } from "../src/app"

const outDir = join(tmpdir(), "ai-pr-review-chat-markdown")
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

const SAMPLE = [
  "## 审查结果概览",
  "",
  "本次共 **4 条** findings，其中 `website/index.html` 有 2 条 critical。",
  "",
  "| # | 位置 | 严重度 |",
  "|---|---|---|",
  "| 1 | website/index.html:237 | critical |",
  "| 2 | website/js/main.js:86 | high |",
  "",
  "建议这样改：",
  "",
  "```js",
  "docsPanelBody.textContent = tab.html;",
  "```",
  "",
  "- 建议先修 `innerHTML` 那两处",
  "- 再核对占位符",
  "",
  "> 证据校验：valid 9 · needs_review 1",
].join("\n")

const WIDTH = 78

const view = await testRender(
  () => (
    <box width={WIDTH} flexDirection="column">
      {/* 用户输入：底色 + 橙色左框线（与 assistant 的纯文本回复区分） */}
      <box
        flexDirection="row"
        marginBottom={1}
        paddingLeft={1}
        paddingRight={1}
        backgroundColor="#1a1a1a"
        border={["left"]}
        borderColor="#fb8147"
      >
        <text width={WIDTH - 10} fg="#eeeeee">
          对应仓库代码
        </text>
      </box>
      <markdown
        width={WIDTH}
        content={SAMPLE}
        syntaxStyle={chatMarkdownStyle()}
        fg="#808080"
        conceal={true}
        renderNode={(token, ctx) => {
          if (token.type !== "code") return undefined
          const code = ctx.defaultRender()
          if (code) {
            const styled = code as { bg?: string; paddingLeft?: number; marginBottom?: number }
            styled.bg = "#141414"
            styled.paddingLeft = 1
            styled.marginBottom = 1
          }
          return code
        }}
        tableOptions={{ widthMode: "full", wrapMode: "word", borders: true, cellPadding: 1 }}
      />
    </box>
  ),
  { width: WIDTH, height: 30 },
)

// 布局需要多帧才能稳定（表格与后面的块会分批落地）——沿用其它 manual 脚本的
// settle 模式：单次 renderOnce 只能拿到第一帧。
for (let i = 0; i < 10; i += 1) {
  await view.renderOnce()
  await new Promise((resolve) => setTimeout(resolve, 10))
}
const frame = view.captureCharFrame()
writeFileSync(join(outDir, "frame-chat-markdown.txt"), frame, "utf8")

console.log("---- rendered frame ----")
console.log(frame)
console.log("------------------------")

// captureCharFrame 会带一个尾随换行，别把它算成一行。
const lines = frame.replace(/\n+$/, "").split("\n")

check(!frame.includes("**"), "粗体标记 `**` 被隐藏")
check(!frame.includes("`"), "行内代码反引号被隐藏")
check(!/\|\s*-{3,}/.test(frame), "表格分隔行 `|---|` 不再原样显示")
check(!/^##\s/m.test(frame), "标题不再带裸 `##`")
check(frame.includes("审查结果概览"), "标题文字仍然可见")
check(frame.includes("4 条"), "粗体文字内容仍然可见")
check(frame.includes("website/index.html"), "表格单元格内容仍然可见")
check(/[│┌┐└┘├┤┬┴┼─]/.test(frame), "表格渲染出边框字符")
check(frame.includes("│") && frame.includes("对应仓库代码"), "用户输入框有左框线且内容可见")
check(frame.includes("textContent = tab.html"), "代码块内容可见")
check(!frame.includes("```"), "代码块围栏 ``` 被隐藏")
check(
  lines.length <= 30,
  `渲染行数不超过 30（实际 ${lines.length}）`,
)
const overflow = lines.filter((line) => [...line].length > WIDTH + 2)
check(overflow.length === 0, `无行宽溢出（宽度 ${WIDTH}）`, overflow[0]?.slice(0, 60) ?? "")

console.log(failures.length === 0 ? `\nALL PASS · frames: ${outDir}` : `\nFAILURES: ${failures.length}`)
process.exit(failures.length === 0 ? 0 : 1)
