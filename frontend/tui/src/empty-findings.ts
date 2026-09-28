/**
 * Wording for "there is nothing to show" in the findings surfaces.
 *
 * Ctrl+O / Ctrl+F / F used to print the same advice — "run /review first" —
 * even right after a review finished with zero findings, which reads like the
 * review never ran. The message is now derived from the session state:
 *
 *   - a review is still running     -> say so;
 *   - a review finished with 0 hits -> say that, name the PR/run, and (when the
 *     run recorded it) explain that candidates were filtered by the confidence
 *     threshold;
 *   - no review in this session     -> keep the original "run /review" advice.
 */

export type FindingsEntryPoint = "list" | "filter" | "feedback"

export type FindingsContext = {
  /** A review is currently in flight. */
  running?: boolean
  /** A completed review exists in this session (report/run known). */
  hasReport?: boolean
  repository?: string
  prNumber?: number
  runId?: string
  /** Confidence threshold the run recorded, when available. */
  threshold?: number | null
  /** Candidates dropped by that threshold, when available. */
  belowThreshold?: number | null
  /** The last review attempt failed (or was cancelled). */
  failed?: boolean
  language?: string
}

const isEnglish = (language?: string): boolean =>
  String(language ?? "zh-CN").toLowerCase().startsWith("en")

const describeTarget = (context: FindingsContext): string => {
  if (typeof context.prNumber === "number" && context.prNumber > 0) {
    return context.repository ? `${context.repository}#${context.prNumber}` : `PR #${context.prNumber}`
  }
  const runId = String(context.runId ?? "").trim()
  return runId ? `run ${runId.slice(0, 8)}` : ""
}

const filteredHint = (context: FindingsContext, en: boolean): string => {
  const dropped = context.belowThreshold
  const threshold = context.threshold
  if (typeof dropped !== "number" || dropped <= 0) return ""
  if (typeof threshold !== "number") {
    return en ? ` ${dropped} candidate(s) were filtered out.` : `已过滤 ${dropped} 条候选。`
  }
  return en
    ? ` ${dropped} candidate finding(s) were below the confidence threshold ${threshold.toFixed(2)} and were filtered out.`
    : `模型给出 ${dropped} 条候选，但都低于置信度门槛 ${threshold.toFixed(2)}，已过滤。`
}

export function emptyFindingsMessage(
  entry: FindingsEntryPoint,
  context: FindingsContext = {},
): string {
  const en = isEnglish(context.language)

  if (context.running) {
    return en
      ? "The review is still running; Ctrl+O will list findings when it finishes."
      : "审查仍在进行中；完成后按 Ctrl+O 查看问题。"
  }

  if (context.failed && !context.hasReport) {
    return en
      ? "The last review did not finish, so there are no findings yet. Ctrl+R retries it."
      : "上次审查没有完成，暂时没有 Findings。可用 Ctrl+R 重试，或按 Ctrl+L 查看历史报告。"
  }

  if (context.hasReport) {
    const target = describeTarget(context)
    const head = en
      ? `This review found no problems${target ? ` (${target})` : ""}, so there are no findings to show.`
      : `本次审查未发现问题${target ? `（${target}）` : ""}，因此没有 Findings 可查看。`
    const tail =
      entry === "filter"
        ? en
          ? " Nothing to filter."
          : " 没有需要筛选的问题。"
        : entry === "feedback"
          ? en
            ? " Nothing to give feedback on."
            : " 没有需要反馈的问题。"
          : en
            ? " Use /report for the full report."
            : " 可用 /report 查看完整报告。"
    return head + filteredHint(context, en) + tail
  }

  if (entry === "filter") {
    return en
      ? "No findings to filter yet. Run /review <PR_URL> or open a stored run with /history <run_id>."
      : "当前没有可筛选的 Findings。先执行 /review <PR_URL> 或 /history <run_id>。"
  }
  if (entry === "feedback") {
    return en
      ? "No finding to give feedback on yet. Run /review <PR_URL> first."
      : "当前没有可反馈的 Finding。请先运行 /review <PR_URL>。"
  }
  return en
    ? "No findings yet. Run /review <PR_URL>, or open a stored report with /history <run_id>."
    : "当前没有 Findings。请先执行 /review <PR_URL>，或用 /history <run_id> 打开历史报告。"
}
