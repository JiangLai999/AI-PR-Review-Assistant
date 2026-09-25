# Claude Review Events — Backend Event Contract (Phase 1+2)

Owner: Claude Code. Implementation: `src/ai_pr_review/backend/jsonl_server.py`.
Spec: [`docs/review-workspace-contract.md`](review-workspace-contract.md) §3.

This document describes exactly what the backend emits, what it can measure, and
what it deliberately does **not** report. The guiding rule is the contract's:
never invent data — `null` (or an omitted field) is always preferred over a fake
value.

## 1. Where the code lives

| Symbol | Purpose |
|---|---|
| `REVIEW_STAGE_LABELS` | stage id → display label (matches `cli.stage_labels`) |
| `REVIEW_STAGE_PROGRESS` | stage id → `(start progress, done progress)` |
| `REVIEW_FILE_TOTAL_PATTERN` | extracts the reviewable-file count from stage details |
| `_ReviewEventStream` | per-run state machine that publishes every `review.*` event |
| `_review_completed_fields()` | derives the `review.completed` summary from the report payload |
| `JsonlBackend._review_routing()` | derives `review.model_routing` from the configured slots |

`JsonlBackend._run_review()` drives the stream from the orchestrator callbacks;
`JsonlBackend.handle()` publishes the terminal events (`review.completed`,
`review.failed`, `review.cancelled`) and appends `stage_id` when a stage was
running.

## 2. Event reference

Timestamps (`started_at`) are UTC ISO-8601 seconds (`2026-09-25T10:00:03+00:00`).
`duration_ms` values are integers measured with `time.perf_counter()` **in the
backend** — the orchestrator has no stage-done hook (see §4.1).

### 2.1 `review.started`

```json
{
  "event": "review.started",
  "session_id": "…",
  "url": "https://github.com/owner/repo/pull/31",
  "started_at": "2026-09-25T10:00:00+00:00"
}
```

`started_at` is new (additive); `session_id` and `url` are unchanged.

### 2.2 `review.stage` — emitted when a stage starts

```json
{
  "event": "review.stage",
  "session_id": "…",
  "stage_id": "reviewing",
  "stage": "执行 AI 审查",
  "status": "started",
  "detail": "开始逐文件审查（并发 2）",
  "progress": 70,
  "started_at": "2026-09-25T10:00:03+00:00"
}
```

| Field | Meaning |
|---|---|
| `stage_id` | stable machine key, the orchestrator's own stage name |
| `stage` | display label (see §3) |
| `status` | always `"started"` for this event |
| `detail` | raw orchestrator detail string (unchanged from before) |
| `progress` | integer 0–100, monotonically non-decreasing |
| `started_at` | when the backend observed the stage start |

### 2.3 `review.stage_done` — emitted when a stage ends

```json
{
  "event": "review.stage_done",
  "session_id": "…",
  "stage_id": "reviewing",
  "stage": "执行 AI 审查",
  "status": "completed",
  "progress": 90,
  "duration_ms": 25800
}
```

Statuses:

| Status | When |
|---|---|
| `completed` | the next stage started, or the run finished successfully |
| `failed` | the pipeline raised; adds `message` and `recovery` |
| `skipped` | the run was cancelled (`review.cancelled` follows) |

A stage is closed exactly once, and never after the run has ended. On failure
`progress` stays at the value the stage started with (the stage did not reach
its completion mark).

### 2.4 `review.file_started`

```json
{
  "event": "review.file_started",
  "session_id": "…",
  "filename": "src/auth_service.py",
  "model": "远程/deepseek-chat",
  "index": 7,
  "total": 18,
  "started_at": "2026-09-25T10:00:03+00:00"
}
```

`index` is 1-based and counts files in the order the backend saw them start
(the orchestrator fires the callback once per file, after it acquires the
concurrency slot). `model` is the pre-existing per-file label — in hybrid mode
it is `本地/<model>` or `远程/<model>`, which is the only per-file routing signal
the orchestrator currently exposes.

### 2.5 `review.file_done`

```json
{
  "event": "review.file_done",
  "session_id": "…",
  "filename": "src/auth_service.py",
  "index": 7,
  "total": 18,
  "status": "reviewed",
  "findings_count": null,
  "duration_ms": 4200
}
```

* `findings_count` is **always `null`** today: the orchestrator merges per-file
  `ReviewResult`s internally and never exposes a per-file count. Reporting `0`
  would be a fabricated number.
* `duration_ms` is measured between `file_started` and `file_done` for that
  filename (`null` if no matching start was seen).
* `status` is always `"reviewed"`; see §4.2 for why `skipped` / `failed` are not
  available.

### 2.6 `review.model_routing` — at most once per review

```json
{
  "event": "review.model_routing",
  "session_id": "…",
  "runtime_profile": "hybrid",
  "router_model": "qwen3.5:4b",
  "deep_model": "deepseek-chat",
  "reason": "混合策略：低风险文件走本地模型，高风险或复杂文件走远程模型"
}
```

Emitted once, right after `review.started` and before the first `review.stage`,
so the TUI can show the policy while the review runs. `reason` follows
`preferences.ui_language` (`zh-CN` / `en-US`).

This event describes the **configured policy** that `ModelSelector` will apply
(main provider is Ollama/Local → that slot, otherwise the persisted
`local_provider`; the remote model comes from the main provider). It is not a
per-file decision log — the orchestrator chooses a model per file and never
reports the choice back. `router_model` is `null` when all files go to one
model (local-only / remote-only). If no model can be named at all, the event is
not emitted rather than sent with guessed values.

### 2.7 `review.completed`

```json
{
  "event": "review.completed",
  "session_id": "…",
  "run_id": "…",
  "finding_count": 15,
  "files_reviewed": 18,
  "files_skipped": 4,
  "severity": {"critical": 2, "high": 9, "medium": 3, "low": 1, "info": 0},
  "evidence": {"valid": 11, "needs_review": 3, "invalid": 1, "unverified": 0},
  "cost": 0.0124,
  "duration_seconds": 42.3
}
```

* `files_reviewed` / `files_skipped` come from the filter result
  (`included_count` / `excluded_count`) — these are the same numbers the report
  and `ResultStore` use.
* `severity` counts every finding by severity and always contains all five keys
  (`info` included, even when `0`).
* `evidence` reads each finding's `evidence_status` (stamped by
  `FindingValidator.annotate`, default `unverified` for findings that never
  reached the validator). All four buckets are always present.
* `cost` is `total_run_cost` rounded to 6 decimals; `duration_seconds` is the
  orchestrator's measured duration rounded to 3 decimals.
* `run_id` and `finding_count` are unchanged (backward compatible).

### 2.8 `review.failed` / `review.cancelled`

Existing fields are unchanged. Both now add `stage_id` when a stage was running
(e.g. `"stage_id": "reviewing"`), plus a preceding `review.stage_done` with
`status: "failed"` (and `message`/`recovery`) or `"skipped"` for cancellation.

## 3. Stage ids, labels and progress

| `stage_id` | `stage` label | start → done progress |
|---|---|---|
| `fetching` | 获取 PR 数据 | 5 → 10 |
| `filtering` | 过滤变更文件 | 10 → 20 |
| `context` | 构建代码上下文 | 20 → 30 |
| `static_rules` | 运行静态规则 | 30 → 50 |
| `reviewing` | 执行 AI 审查 | 70 → 90 |
| `cross_file` | 分析跨文件影响 | 90 → 98 |
| `persisting` | 保存审查记录 | 98 → 100 |

The standard orchestrator emits `fetching, filtering, context, reviewing,
cross_file, persisting`; the hybrid orchestrator emits `fetching, filtering,
context, static_rules, reviewing, persisting`. Both orders are covered by the
table above.

* `progress` is derived from this table only — never from string length or a
  guessed elapsed-time ratio. An unknown `stage_id` keeps the previous value
  (the bar never moves backwards) and is passed through with `stage_id` ==
  `stage`.
* `detail` is passed through unchanged, so existing consumers of that field are
  unaffected.

### 3.1 Deliberate value change: `stage` is now the display label

Before this change the backend sent the raw stage id in `stage` (e.g.
`"reviewing"`), which the TUI could not map to its progress table. Per contract
§3.2, `stage` now carries the display label and `stage_id` carries the machine
key. **No information is lost** — the machine key is `stage_id`. A consumer that
still compares `stage` against ids must switch to `stage_id`; the mapping lives
in exactly one place (`REVIEW_STAGE_LABELS`).

## 4. Limitations (not invented, documented)

### 4.1 Stage durations are measured by the backend

`stage_callback(stage, detail)` in both orchestrators fires **only when a stage
starts**; there is no stage-done callback and no per-stage timer to read. The
backend therefore closes stage *N* when stage *N+1* starts (or when the run
finishes). `duration_ms` therefore includes the small scheduling gap between
stages. Nobody else measures these durations, so this is the honest value.

**Extension point:** add a `stage_done_callback(stage)` (or return per-stage
timings) to `ReviewOrchestrator.review` / `HybridOrchestrator.review`; the
backend only needs to call `stream`'s close path from it instead of from the
next stage start.

### 4.2 No `skipped` / `failed` file events

The orchestrator exposes exactly two file callbacks: `progress_callback(filename,
model)` when a file actually starts, and `file_done_callback(filename)`. That
means:

* files removed by the filter pipeline are **never** reported per file — only
  their total (`review.completed.files_skipped`) is known. Their names and
  reasons live in the persisted filter result
  (`payload["filter"]["results"]`), not in the event stream;
* a file whose model call raises is still reported as `reviewed`, because the
  standard orchestrator calls `file_done_callback` from a `finally` block and the
  hybrid orchestrator swallows the per-file exception. The backend cannot
  distinguish success from failure there.

**Extension point:** widen the callbacks, e.g.
`progress_callback(filename, model, index, total)` and
`file_done_callback(filename, status, findings_count)`, with `status` in
`reviewed|failed|skipped` and per-file finding counts from the file's own
`ReviewResult`. Until then, `review.file_done.status` stays `"reviewed"`,
`findings_count` stays `null`, and the TUI must render `ReviewFileState.status`
from what it actually receives.

### 4.3 File totals come from the stage detail text

`review.file_*.total` is parsed from the orchestrator's stage detail
(`REVIEW_FILE_TOTAL_PATTERN`, e.g. `正在为 4 个文件构建上下文`). This is real data
but it is a **text compatibility shim**, not a contract: a reworded detail (or a
third orchestrator) makes `total` `null`. The pattern deliberately does not match
the filtering detail (`共 120 个变更文件`), which counts changed files rather
than files that will be reviewed. A `null` total is truthful; the TUI already
tolerates it (`filesTotal?: number`).

**Extension point:** pass `total` explicitly to `progress_callback`.

### 4.4 `review.model_routing` is policy, not per-file truth

See §2.6. Per-file model choices are not exposed by either orchestrator.

### 4.5 Dropped frames

`review.stage`, `review.file_started` and `review.file_done` are dropped once a
session exceeds `max_events_per_session` (2048) repetitive progress frames.
`review.stage_done`, `review.model_routing`, `review.completed`, `review.failed`
and `review.cancelled` are never dropped.

## 5. Verification

```powershell
python -m pytest tests/test_jsonl_backend.py -q --no-cov
```

New coverage (see `tests/test_jsonl_backend.py`):

* stage ids/labels/status/progress/timestamps, event ordering, monotonic
  progress, backend-measured `duration_ms`, `stage_done` progress `100`;
* file `index`/`total`/`started_at`/`duration_ms`, `findings_count is None`,
  per-file `model` label preserved, `total is None` when the orchestrator never
  reports it, and the total-parsing formats of both orchestrators;
* `review.completed` severity/evidence/files/cost/duration plus the unchanged
  `run_id`/`finding_count`, and the `unverified` fallback for findings without
  `evidence_status`;
* routing policy for hybrid / remote-only / local-only slots and the
  `ui_language` reason, emitted exactly once before the first stage;
* failed stage → `review.stage_done(status="failed", message, recovery)` and
  `review.failed.stage_id`; cancelled stage → `status="skipped"` and
  `review.cancelled.stage_id`;
* late events after `complete()`/`abort()` are dropped, and unknown stage ids
  keep the previous progress.
