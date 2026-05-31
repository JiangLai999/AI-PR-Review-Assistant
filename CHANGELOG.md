# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Added

- CLI history and stats commands backed by SQLite result storage.
- GitHub comment rendering and publish flow for PR reviews.
- API documentation for the CLI surface in `docs/API.md`.
- Contribution guide, release guide, CI workflows, and community templates.
- Website documentation hub with GSAP animations (`website/`).
- Chat workspace with ASCII-art UI, welcome message, and timestamp support.
- Slash command auto-completion and `/restore` command for session recovery.
- Prompt-toolkit integration for enhanced input experience.

### Changed

- README now reflects the repository's current executable scope more precisely.
- Packaging metadata and release support were expanded for PyPI publishing.
- Chat UI redesigned with ASCII box drawing for better cross-platform compatibility.
- GitHub repository URL updated to `JiangLai999/AI-PR-Review-Assistant`.

### Fixed

- Pagination index in PR file fetching (0-based vs 1-based).
- Chat test assertions updated for new UI format.
- Import ordering and black formatting for CI compliance.

## [0.1.0] - 2026-05-30

### Added

- Initial CLI review workflow for GitHub Pull Requests.
- PR fetching, filtering, context building, prompt assembly, AI review, and report rendering.
- Test coverage for core services and CLI behavior.
