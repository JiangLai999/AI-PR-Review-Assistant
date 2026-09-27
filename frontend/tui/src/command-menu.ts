export type ChatCommand = {
  name: string
  description: string
  argument?: string
}

/**
 * 命令描述默认中文；英文文案走 `commandDescription(command, language)`，
 * 与 app.tsx 的 `isEn` 语言机制对齐。新增命令中英都必须给。
 */
export type ChatCommandI18n = ChatCommand & {
  description_en?: string
  argument_en?: string
}

// Only advertise commands that the current TUI and Python backend implement.
export const chatCommands: readonly ChatCommandI18n[] = [
  { name: "/help", description: "查看可用命令", description_en: "List available commands" },
  { name: "/status", description: "查看运行状态", description_en: "Show runtime status" },
  {
    name: "/model",
    description: "查看或切换当前模型",
    description_en: "Show or switch the current model",
    argument: "<模型或 local/cloud/hybrid>",
    argument_en: "<model or local/cloud/hybrid>",
  },
  { name: "/model status", description: "检查模型连通性", description_en: "Check model connectivity" },
  { name: "/setup", description: "打开配置助手", description_en: "Open the setup wizard" },
  {
    name: "/review",
    description: "开始 PR 审查",
    description_en: "Start a PR review",
    argument: "<GitHub PR URL>",
  },
  { name: "/cancel", description: "取消当前审查", description_en: "Cancel the running review" },
  { name: "/retry", description: "重试上一次审查", description_en: "Retry the last review" },
  { name: "/report", description: "查看当前报告", description_en: "Show the current report" },
  {
    name: "/export",
    description: "导出当前报告",
    description_en: "Export the current report",
    argument: "<json|markdown> [路径]",
    argument_en: "<json|markdown> [path]",
  },
  {
    name: "/history",
    description: "查看对话消息列表",
    description_en: "Show the conversation message list",
    argument: "[--runs|数量或 Run ID]",
    argument_en: "[--runs|count or Run ID]",
  },
  {
    name: "/explain",
    description: "解释当前 Run 的问题与证据",
    description_en: "Explain findings and evidence for the current run",
    argument: "<run_id>",
  },
  {
    name: "/feedback",
    description: "记录问题反馈",
    description_en: "Record finding feedback",
    argument: "<run_id> <finding_id> <status>",
  },
  {
    name: "/publish",
    description: "预览并发布审查评论到 GitHub",
    description_en: "Preview and publish review comments to GitHub",
    argument: "[run_id] [--confirm]",
  },
  {
    name: "/demo",
    description: "运行离线演示用例",
    description_en: "Run an offline demo case",
    argument: "[case_key|list]",
  },
  { name: "/showcase", description: "查看参赛演示路径", description_en: "Show the contest demo path" },
  { name: "/workbench", description: "展开 / 收起审查工作台", description_en: "Expand or collapse the review workbench" },
  {
    name: "/think",
    description: "调整思考深度档位",
    description_en: "Set the reasoning effort level",
    argument: "<off|low|high|max|auto>",
    argument_en: "<off|low|high|max|auto>",
  },
  {
    name: "/compact",
    description: "压缩上下文",
    description_en: "Compress conversation context",
    argument: "[指令]",
    argument_en: "[instruction]",
  },
  {
    name: "/sessions",
    description: "打开会话列表（切换/重命名/删除）",
    description_en: "Open the session list (switch / rename / delete)",
  },
  { name: "/new", description: "开始新会话", description_en: "Start a new session" },
]

/** 按界面语言取描述/参数提示；缺英文时回落中文。 */
export function commandDescription(command: ChatCommandI18n, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return (en ? command.description_en : command.description) ?? command.description
}

export function commandArgumentLabel(command: ChatCommandI18n, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return (en ? command.argument_en : command.argument) ?? command.argument ?? ""
}

export function commandMatches(draft: string, commands: readonly ChatCommand[] = chatCommands): ChatCommand[] {
  if (!draft.startsWith("/") || draft.includes("\n")) return []
  const query = draft.toLowerCase()
  if (query.includes(" ")) {
    return commands.filter((command) => query === command.name || query === `${command.name} `)
  }
  return commands.filter((command) => command.name.startsWith(query))
}

export function commandCompletion(command: ChatCommand): string {
  return command.argument ? `${command.name} ` : command.name
}

export type CommandEnterAction = { kind: "run" } | { kind: "complete"; draft: string }

/**
 * Decide what Enter does for the highlighted slash-menu entry.
 *
 * Enter must never run a command the user did not actually pick:
 * ambiguous prefixes (`/h` matching `/help` and `/history`) only complete, and
 * commands that need an argument only complete on the first Enter.
 */
export function commandEnterAction(
  draft: string,
  option: ChatCommand,
  matchCount: number,
): CommandEnterAction {
  const exact = draft.trim().toLowerCase() === option.name.toLowerCase()
  const needsArgument = Boolean(option.argument)
  const hasTrailingSpace = draft !== draft.trimEnd()
  if (exact && (!needsArgument || hasTrailingSpace)) return { kind: "run" }
  if (exact && needsArgument) return { kind: "complete", draft: commandCompletion(option) }
  if (matchCount === 1) {
    return needsArgument
      ? { kind: "complete", draft: commandCompletion(option) }
      : { kind: "run" }
  }
  return { kind: "complete", draft: commandCompletion(option) }
}
