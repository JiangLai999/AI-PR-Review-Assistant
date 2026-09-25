import { For, Show } from "solid-js"
import type { EvidenceCounts, ReviewFinding } from "./types"
import { demoView, type DemoEvidence } from "./panel-model"
import { BorderedPanel } from "./BorderedPanel"

export type DemoResultPanelProps = {
  caseKey?: string
  title?: string
  description?: string
  riskLevel?: string
  priorityFiles?: number
  findings: ReviewFinding[]
  evidence?: Partial<DemoEvidence> | EvidenceCounts
  durationMs?: number
  language?: string
}

/**
 * Offline demo result: risk badge, priority-file count, evidence health and
 * the ranked findings list (reusing `rankFindings` / `evidenceBadge` /
 * `severityColor`). Empty or missing data renders a neutral line, not a crash.
 */
export function DemoResultPanel(props: DemoResultPanelProps) {
  const isEn = () => String(props.language ?? "zh-CN").toLowerCase().startsWith("en")
  const view = () =>
    demoView({
      caseKey: props.caseKey,
      title: props.title,
      description: props.description,
      riskLevel: props.riskLevel,
      priorityFiles: props.priorityFiles,
      findings: props.findings,
      evidence: props.evidence,
      durationMs: props.durationMs,
      language: props.language,
    })

  return (
    <BorderedPanel borderColor="#fb8147">
      <text height={1} fg="#fb8147">
        {view().title}
      </text>
      <Show when={view().caseKey}>
        <text height={1} fg="#808080">
          {view().caseKey}
        </text>
      </Show>
      <Show when={view().description}>
        <text height={1} fg="#eeeeee">
          {view().description}
        </text>
      </Show>

      <text height={1} marginTop={1}>
        <span style={{ fg: view().risk.color }}>{view().risk.text}</span>
        <span style={{ fg: "#808080" }}>
          {isEn() ? ` · Priority files ${view().priorityFiles}` : ` · 优先文件 ${view().priorityFiles}`}
        </span>
        <Show when={view().durationLine}>
          <span style={{ fg: "#808080" }}>{` · ${view().durationLine}`}</span>
        </Show>
      </text>
      <text height={1} fg="#808080">
        {view().evidenceLine}
      </text>

      <text height={1} fg="#f3c742" marginTop={1}>
        {isEn() ? `Findings (${view().findings.length})` : `问题列表 (${view().findings.length})`}
      </text>
      <Show
        when={!view().empty}
        fallback={
          <text height={1} fg="#808080">
            {isEn() ? "No findings in this demo case." : "该演示用例暂无问题。"}
          </text>
        }
      >
        <For each={view().findings}>
          {(finding, index) => (
            <box flexDirection="column">
              <text height={1}>
                <span style={{ fg: "#808080" }}>{`${index() + 1}. `}</span>
                <span style={{ fg: finding.severityColor }}>{`[${finding.severity}]`}</span>
                <span style={{ fg: "#eeeeee" }}>{` ${finding.title}`}</span>
              </text>
              <text height={1} fg="#808080">
                {finding.location}
                <Show when={finding.evidenceText}>
                  <span style={{ fg: finding.evidenceColor }}>{` · ${finding.evidenceText}`}</span>
                </Show>
              </text>
            </box>
          )}
        </For>
      </Show>
    </BorderedPanel>
  )
}
