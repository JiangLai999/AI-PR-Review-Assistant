export type ChatCommand = {
  name: string
  description: string
  argument?: string
}

// Only advertise commands that the current TUI and Python backend implement.
export const chatCommands: readonly ChatCommand[] = [
  { name: "/help", description: "查看可用命令" },
  { name: "/status", description: "查看运行状态" },
  { name: "/model", description: "查看或切换当前模型", argument: "<模型或 local/cloud/hybrid>" },
  { name: "/model status", description: "检查模型连通性" },
  { name: "/setup", description: "打开配置助手" },
  { name: "/review", description: "开始 PR 审查", argument: "<GitHub PR URL>" },
  { name: "/cancel", description: "取消当前审查" },
  { name: "/retry", description: "重试上一次审查" },
  { name: "/report", description: "查看当前报告" },
  { name: "/export", description: "导出当前报告", argument: "<json|markdown> [路径]" },
  { name: "/history", description: "查看历史记录", argument: "[数量或 Run ID]" },
  { name: "/new", description: "开始新会话" },
]

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
