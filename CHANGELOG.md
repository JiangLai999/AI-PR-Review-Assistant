# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Added

- Review planner producing a transparent `ReviewPlan` (risk level, categories,
  priority files, strategies, cross-file requirement).
- Evidence validation for every finding (file, line range, changed-line check,
  code-snippet match) with `valid` / `needs_review` / `invalid` status.
- Python AST analyzer with syntax-level rules: mutable default arguments, bare
  `except`, `is` comparison against literals, unclosed resources, unsafe
  deserialization, `subprocess` with `shell=True`, disabled TLS verification,
  weak hash algorithms, and exceptions re-raised without `from`.
- Additional line-level rules: unsafe `yaml.load`, `verify=False`, hard-coded
  credential constants, and debug mode enabled in source.
- Cross-file symbol index and interface-impact analysis: signature comparison
  against the PR base revision plus external caller resolution.
- Real tree-sitter integration for Python, JavaScript and TypeScript behind the
  optional `ast` extra, with automatic regex fallback when unavailable.
- Benchmark subsystem (`pr-review benchmark`) with a curated known-defect case
  library and precision / recall / F1 / false-positive-rate / line-accuracy
  metrics.
- Productised local web workbench with risk overview, progress indicator,
  filterable findings list, evidence badges, human feedback buttons, review
  history, and report loading.
- New HTTP endpoints: `/api/history`, `/api/report`, `/api/feedback`.
- Finding feedback persistence (accepted / rejected / fixed / needs_review).
- Concurrent-safe AI budget reservation.

### Changed

- Finding merge deduplicates results that line-level and AST rules both report.
- CLI history and stats commands backed by SQLite result storage.
- GitHub comment rendering and publish flow for PR reviews.
- Website documentation hub with GSAP animations (`website/`).
- Chat workspace with ASCII-art UI, welcome message, and timestamp support.

### Fixed

- `ResultStore.save_result` failed on every call: the `metadata_json` column was
  missing from the schema and the INSERT placeholder count did not match the
  value tuple. Existing databases are migrated in place.
- CLI test doubles now use the real `FilterPipelineResult` type, which restored
  the full test suite.
- Pagination index in PR file fetching (0-based vs 1-based).
- Import ordering and black formatting for CI compliance.

## [0.1.0] - 2026-05-30

### Added

- Initial CLI review workflow for GitHub Pull Requests.
- PR fetching, filtering, context building, prompt assembly, AI review, and report rendering.
- Test coverage for core services and CLI behavior.
