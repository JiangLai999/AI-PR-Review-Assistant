# Claude Review Actions — per-file callbacks + explain/feedback (Phase 3/4)

Owner: Claude Code. Spec: [`docs/review-workspace-contract.md`](review-workspace-contract.md)
§10.2 (callback contract), §10.3 (backend actions), §10.6 (acceptance).

This document records what the orchestrators now report per file, what the JSONL
backend does with it, and which values stay `null` because nobody can know them.
The rule from the contract is unchanged: **never invent data**.

## 1. Where the code lives

| Symbol | File | Purpose |
|---|---|---|
| `file_result_payload()` | `src/ai_pr_review/services/review_orchestrator.py` | builds one payload with all five keys |
| `emit_file_result()` | same | calls the callback when it is set, otherwise does nothing |
| `emit_skipped_file_results()` | same | reports every file the filter pipeline removed |
| `ReviewOrchestrator._review_file_contexts()` | same | per-file timing + `reviewed` / `failed` |
| `HybridReviewOrchestrator.review()` | `src/ai_pr_review/services/hybrid_orchestrator.py` | same payloads for the hybrid path |
| `cli.run_review(file_result_callback=…)` | `src/ai_pr_review/cli.py` | forwards the callback verbatim |
| `_ReviewEventStream.file_result()` | `src/ai_pr_review/backend/jsonl_server.py` | turns payloads into `review.file_done` |
| `JsonlBackend._explain_run()` / `_record_feedback()` | same | `command.execute` `explain` / `feedback` |
| `FEEDBACK_STATUSES` | same | the one allowed status list for the backend |

## 2. `file_result_callback(payload)`

```python
file_result_callback(payload: dict) -> None
```

```json
{
  "filename": "src/auth_service.py",
  "status": "reviewed | skipped | failed",
  "findings_count": 2,
  "duration_ms": 4200,
  "error": null
}
```

* **Optional.** Old callers that do not pass it behave exactly as before.
* `progress_callback(filename, model)` and `file_done_callback(filename)` keep
  their previous semantics and firing points; `file_done_callback` still fires on
  the failure path (`finally` in the standard orchestrator).
* Ordering per file (the backend relies on it): `progress_callback` →
  `file_result_callback` → `file_done_callback`.
* `status`:
  * `reviewed` — the per-file model call returned;
  * `failed` — the per-file model call raised. The standard orchestrator then
    re-raises (the run aborts, as before); the hybrid orchestrator keeps its old
    behaviour of swallowing the exception and reviewing the next file;
  * `skipped` — the filter pipeline removed the file before review. These files
    never fire `progress_callback` / `file_done_callback`, so `skipped` is only
    ever reported through `file_result_callback`.
* `findings_count` counts the findings **returned by that file's model call**
  (`len(result.findings)`). It is `null` when the call failed or when the result
  object exposes no findings list. Deterministic rule / AST findings are merged at
  run level (`review.completed.finding_count`) and are **not** attributed to a
  file, so a file's `findings_count` can be lower than the number of findings in
  the final report.
* `duration_ms` is measured around the model call with `time.perf_counter()`.
  Filtered files report a real `0` (no review time was spent on them).
* `error` is `str(exc)` (falling back to the exception class name) for `failed`,
  and `null` for `reviewed` / `skipped`.

## 3. `review.file_done` now carries real values

`_ReviewEventStream` stores each payload and pairs it with the matching
`file_done_callback` call, so the event uses the orchestrator's real values:

```json
{
  "event": "review.file_done",
  "session_id": "…",
  "filename": "src/auth_service.py",
  "index": 1,
  "total": 18,
  "status": "reviewed",
  "findings_count": 2,
  "duration_ms": 4200
}
```

* `failed` events also carry `error` (the message from the payload).
* `skipped` files are published straight from the payload — they have no
  `review.file_started`, so `index` is `null` and `reason` is
  `"filtered_by_policy"` (the contract's §3.5 example).
* **Fallback:** when an orchestrator (or a test double) never calls
  `file_result_callback`, the backend keeps the previous behaviour —
  `status="reviewed"`, `findings_count=null`, and `duration_ms` measured by the
  backend itself. Values are never estimated.

This supersedes the old limitation in
[`docs/claude-review-events.md`](claude-review-events.md) §4.2 ("no skipped /
failed file events"). That file is owned by another workstream and still
describes the pre-Phase-3 behaviour; the event-shape changes above are the
authoritative description until it is refreshed.

## 4. Backend actions (`command.execute`)

Both reuse `ResultStore` and never call a model.

| Command | Arguments | Result |
|---|---|---|
| `explain` | `run_id` | `{text, run_id, summary, findings[], metadata}` — deterministic findings/evidence rendering (severity, location, sources, `evidence_status`, `evidence_issues`, problem, suggestion) plus the run's language metadata |
| `feedback` | `run_id`, `finding_id`, `status`, optional `note` | `{text, run_id, finding_id, status, note}` after `ResultStore.save_feedback` |

Errors are actionable and carry a stable code:

| Situation | `error.code` | Message |
|---|---|---|
| `explain` without a run id | `invalid_request` | `请提供 Run ID：/explain <run_id>` |
| unknown run (both commands) | `not_found` | `未找到审查记录：<run_id>` |
| `feedback` missing arguments | `invalid_request` | `用法：/feedback <run_id> <finding_id> <status> [note]` |
| status outside `FEEDBACK_STATUSES` | `invalid_request` | lists the allowed values |
| finding id not in that run | `not_found` | `Run <run_id> 中未找到 Finding：<finding_id>` |

`status` is matched case-insensitively (`FIXED` → `fixed`). `FEEDBACK_STATUSES`
must stay equal to `ResultStore.save_feedback`'s allowed set and to the CLI's
`feedback --status` choice; `test_feedback_statuses_match_cli_choice_and_result_store`
fails if they drift.

## 5. Tests

| Test | Covers |
|---|---|
| `test_file_result_payload_keeps_unknown_values_null` | payload shape, unknown → `null` |
| `test_file_result_callback_reports_reviewed_files_with_real_values` | `reviewed` + counts/duration, callback order, old `file_done_callback` |
| `test_file_result_callback_reports_failed_files_before_reraising` | `failed` + `findings_count=null` + re-raise |
| `test_file_result_callback_reports_filtered_files_as_skipped` | `skipped`, no `file_done_callback` |
| `test_hybrid_file_result_callback_reports_reviewed_and_failed` | hybrid path, failure swallowed as before |
| `test_cli_run_review_forwards_file_result_callback` | `cli.run_review` forwards the callback, old kwargs intact |
| `test_hybrid_file_result_callback_reports_filtered_files_as_skipped` | hybrid `skipped` |
| `test_review_file_done_uses_real_status_findings_count_and_duration` | real values in the event stream |
| `test_review_file_done_falls_back_to_measured_duration_when_payload_omits_it` | partial payloads |
| `test_command_explain_*`, `test_command_feedback_*` | §10.3 commands and their errors |
| `test_feedback_statuses_match_cli_choice_and_result_store` | no status drift |

Commands used for verification (run from the repository root):

```bash
python -m pytest tests/test_review_orchestrator.py tests/test_jsonl_backend.py -q --no-cov
python -m pytest -q --no-cov
```

## 6. Known limits (not hidden)

* `findings_count` counts model findings only (see §2) — deterministic rule
  findings stay run-level.
* The hybrid orchestrator reports `failed` for a file whose model call raised,
  but keeps reviewing the remaining files; the run's summary still says
  `审查失败: …` for that file.
* The standard orchestrator aborts the whole run on a per-file failure, so the
  `review.file_done` for that file is emitted just before `review.failed`.
* `feedback` requires the run to actually contain a finding with that
  `finding_id` (the CLI's `feedback` only checks that the run exists). Findings
  that were never id-stamped — the hybrid orchestrator saves AI findings without
  running `FindingValidator` — therefore cannot be referenced by id.
* Stage durations and `review.file_*.total` are unchanged and still documented as
  approximations in `docs/claude-review-events.md` §4.1 / §4.3.
* One `review.file_done` is published per skipped file, so a PR with more
  excluded files than `JsonlBackend.max_events_per_session` (2048) can consume
  the session budget and start dropping repetitive progress frames — the
  pre-existing limit documented in `docs/claude-review-events.md` §4.5. The
  skipped-file list is always complete in the report payload
  (`payload["filter"]["results"]`).
