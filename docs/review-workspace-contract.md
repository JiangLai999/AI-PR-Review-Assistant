# Review Workspace Collaboration Contract (v1)

## 1. Objective

Upgrade the Chat review experience from inline text blocks to a dedicated
workspace with:

1. a review progress timeline (stage status, duration, current file);
2. a review summary (severity distribution, evidence health, metrics);
3. a findings workspace (ranked list, confidence, evidence state, actions).

This contract covers **Phase 1 + Phase 2**. Phase 3 (Finding detail actions and
feedback) will extend the same types later.

## 2. Ownership

| Owner | Write scope | Deliverable |
|---|---|---|
| Codex | `frontend/tui/src/app.tsx`, `frontend/tui/src/protocol.ts`, `frontend/tui/src/review-report.ts`, `docs/review-workspace-contract.md`, final build/tests | Integration, state mapping, final acceptance, `tui_static` rebuild |
| Claude Code | `src/ai_pr_review/backend/jsonl_server.py`, `tests/test_jsonl_backend.py`, `docs/claude-review-events.md` | Richer review event payloads + tests |
| MiMo Code | `frontend/tui/src/review-ui/**`, `frontend/tui/scripts/manual-review-workspace-check.tsx` | Presentational components, formatting helpers, component tests, manual visual check |

Write scopes are disjoint. No agent may edit another owner's files.

## 3. Event Contract

Existing events must remain valid. New fields are additive and optional for
consumers. The TUI must tolerate missing fields.

### 3.1 `review.started`

```json
{
  "event": "review.started",
  "session_id": "…",
  "url": "https://github.com/owner/repo/pull/31",
  "started_at": "2026-09-25T10:00:00+00:00"
}
```

### 3.2 `review.stage`

Emitted when a stage starts.

```json
{
  "event": "review.stage",
  "session_id": "…",
  "stage_id": "review",
  "stage": "执行 AI 审查",
  "status": "started",
  "detail": "src/auth_service.py",
  "progress": 70,
  "started_at": "2026-09-25T10:00:03+00:00"
}
```

### 3.3 `review.stage_done`

Emitted when a stage finishes. `duration_ms` is measured by the backend.

```json
{
  "event": "review.stage_done",
  "session_id": "…",
  "stage_id": "review",
  "stage": "执行 AI 审查",
  "status": "completed",
  "progress": 80,
  "duration_ms": 25800
}
```

Failure uses `status: "failed"` and adds `message` and `recovery`.

### 3.4 `review.file_started`

```json
{
  "event": "review.file_started",
  "session_id": "…",
  "filename": "src/auth_service.py",
  "index": 7,
  "total": 18,
  "started_at": "2026-09-25T10:00:03+00:00"
}
```

### 3.5 `review.file_done`

`findings_count` may be `null` when the orchestrator does not expose per-file
counts. No fake values.

```json
{
  "event": "review.file_done",
  "session_id": "…",
  "filename": "src/auth_service.py",
  "index": 7,
  "total": 18,
  "status": "reviewed",
  "findings_count": 2,
  "duration_ms": 4200
}
```

Skipped or failed files may be emitted as:

```json
{
  "event": "review.file_done",
  "session_id": "…",
  "filename": "docs/readme.md",
  "status": "skipped",
  "reason": "filtered_by_policy"
}
```

If the current orchestrator cannot provide skipped/failed file events, Claude
Code must document the limitation in `docs/claude-review-events.md` and leave a
clear extension point; do not invent data.

### 3.6 `review.model_routing`

At most one event per review, emitted once routing is known.

```json
{
  "event": "review.model_routing",
  "session_id": "…",
  "runtime_profile": "hybrid",
  "router_model": "ollama/qwen3.5:4b",
  "deep_model": "deepseek/deepseek-flash",
  "reason": "light tasks local, deep review remote"
}
```

### 3.7 `review.completed`

Extend the existing event with summary fields:

```json
{
  "event": "review.completed",
  "session_id": "…",
  "run_id": "…",
  "finding_count": 15,
  "files_reviewed": 18,
  "files_skipped": 4,
  "severity": {"critical": 2, "high": 9, "medium": 3, "low": 1},
  "evidence": {"valid": 11, "needs_review": 3, "invalid": 1, "unverified": 0},
  "cost": 0.0124,
  "duration_seconds": 42.3
}
```

### 3.8 Failure and cancellation

`review.failed` and `review.cancelled` keep their current fields and add
`stage_id` when known.

## 4. Component Contract

MiMo Code implements presentational components. Codex maps TUI state into these
props. Components must not call the backend directly.

### 4.1 Shared types

```ts
export type ReviewStageState = {
  id: string
  label: string
  status: "pending" | "active" | "done" | "failed" | "skipped"
  durationMs?: number
  detail?: string
}

export type ReviewFileState = {
  filename: string
  status: "pending" | "reviewed" | "skipped" | "failed"
  findingsCount?: number | null
  durationMs?: number
  reason?: string
  error?: string
}

export type ReviewModelRouting = {
  runtimeProfile?: string
  routerModel?: string
  deepModel?: string
  reason?: string
}

export type SeverityCounts = {
  critical: number
  high: number
  medium: number
  low: number
  info?: number
}

export type EvidenceCounts = {
  valid: number
  needsReview: number
  invalid: number
  unverified: number
}
```

### 4.2 `ReviewProgressPanel`

```ts
type ReviewProgressPanelProps = {
  url: string
  stageId: string
  stageLabel: string
  progress: number
  stages: ReviewStageState[]
  filesDone: number
  filesTotal?: number
  currentFile?: string
  fileStates?: ReviewFileState[]
  routing?: ReviewModelRouting
  elapsedMs?: number
  cost?: number
  language?: string
  onCancel?: () => void
}
```

Required semantics:

- stage list shows pending / active / done / failed / skipped;
- progress bar is derived from `progress`, not from string length;
- current file and `filesDone / filesTotal` render when available;
- routing renders only when provided;
- no crash on empty arrays or undefined fields.

### 4.3 `ReviewSummaryPanel`

```ts
type ReviewSummaryPanelProps = {
  repository?: string
  prNumber?: number
  title?: string
  severity: SeverityCounts
  evidence: EvidenceCounts
  filesReviewed: number
  filesSkipped: number
  findings: ReviewFinding[]
  durationSeconds?: number
  cost?: number
  runId?: string
  model?: string
  language?: string
  onOpenFindings?: () => void
}
```

Required semantics:

- severity distribution bar derived from counts;
- evidence health labels use text + color, never color alone;
- top findings are ranked critical/high/medium/low/info;
- confidence is shown as a percentage when present;
- `onOpenFindings` is optional and render-only.

### 4.4 Formatting helpers

MiMo Code must export and test:

```ts
severityColor(severity: string): string
evidenceBadge(status: string, language?: string): string
formatDuration(ms?: number, language?: string): string
severityBar(counts: SeverityCounts, width?: number): string
severityPercent(counts: SeverityCounts): number
rankFindings(findings: ReviewFinding[]): ReviewFinding[]
```

## 5. Acceptance Criteria

### Claude Code

- `review.stage` includes `stage_id`, `status`, `progress`, `started_at`;
- `review.stage_done` is emitted with measured `duration_ms`;
- `review.file_started` and `review.file_done` include `index` and `total`;
- `review.model_routing` is emitted when routing is known;
- `review.completed` includes severity, evidence, files, cost, duration;
- all existing backend tests pass, plus new event-shape tests;
- unsupported skipped/failed file events are documented, not invented.

### MiMo Code

- new components live only under `frontend/tui/src/review-ui/`;
- `bun run typecheck` passes;
- new helper tests pass under `bun test src`;
- `manual-review-workspace-check.tsx` renders both components with fixture data
  in 80x24 and 120x30;
- no edits to `app.tsx`, backend, or `tui_static`.

### Codex integration

- maps real TUI state/events into the new components;
- preserves existing review behavior and Ctrl+O/FindingsDialog;
- full Python suite, TUI tests, typecheck pass;
- PTY visual check on a real historical report;
- rebuilds and stages `tui_static/tui.js`.

## 6. Handoff Protocol

1. Agent claims its task:

   ```powershell
   python scripts/agent_bridge.py claim --agent <claude|mimo> <task-id>
   ```

2. Agent works only inside `write_scope`.
3. Agent reports with exact files, commands, results, and uncertainty:

   ```powershell
   python scripts/agent_bridge.py report --agent <claude|mimo> --task-id <task-id> --status <completed|blocked|needs-review> --summary "..." --evidence "..." --blockers "..."
   ```

4. Codex reviews the report, runs independent verification, integrates, and
   closes the task.

## 7. Task IDs

| Task ID | Agent | Purpose |
|---|---|---|
| `claude-review-events` | Claude Code | Backend review event payloads + tests |
| `mimo-review-workspace` | MiMo Code | Review progress/summary components + tests |
| `codex-review-integration` | Codex | Contract, integration, PTY acceptance, build |

## 8. Non-Goals for This Phase

- Finding feedback / false-positive workflow (Phase 3);
- GitHub comment publishing UI (Phase 3);
- Web UI changes;
- replacing the existing Ctrl+O FindingsDialog;
- changing review scoring or orchestration semantics.

## 9. Execution Status (2026-09-25)

| Stream | Status | Evidence |
|---|---|---|
| `claude-review-events` | completed | 48 targeted backend tests passed; full Python suite 453 passed / 1 skipped; event reference in `docs/claude-review-events.md` |
| `mimo-review-workspace` | completed | `bun run typecheck` passed; `bun test src` 51 passed / 0 failed; manual progress/summary/stacked/empty render passed at 80x24 and 120x30 |
| `codex-review-integration` | completed | components wired into `app.tsx`; full Python suite 453 passed / 1 skipped; TUI tests 51 passed; real historical report rendered the new summary; live review emitted and rendered `review.model_routing` before the sandbox blocked GitHub fetch |

Known follow-ups:

1. Per-file `findings_count` remains `null`, and skipped/failed file events are
   not distinguishable until the orchestrator callbacks expose status.
2. The responsive two-column Review Workspace (Phase 4) is not part of this
   round; the current integration uses the existing single-column Chat layout.
3. Finding feedback, false-positive marking, export and publish actions remain
   Phase 3 work.
