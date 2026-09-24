"""Tag the staged Windows OpenTUI wheel for its actual native DLL platform."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        staged = (
            Path(self.root)
            / "src"
            / "ai_pr_review"
            / "tui_static"
            / "node_modules"
            / "@opentui"
            / "core-win32-x64"
            / "opentui.dll"
        )
        bundle = Path(self.root) / "src" / "ai_pr_review" / "tui_static" / "tui.js"
        if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise RuntimeError(
                "This staged TUI contains a Windows x64 DLL; build the wheel on Windows x64 "
                "or prepare a platform-specific TUI payload before building."
            )
        if not staged.is_file() or not bundle.is_file():
            raise RuntimeError(
                "OpenTUI bundle missing. Run `cd frontend/tui && bun run stage` before building the wheel."
            )
        # Do not advertise a Windows DLL as a cross-platform py3-none-any wheel.
        prebuilt = bundle.parent / "pr-review-tui.exe"
        standalone_requested = os.getenv("AI_PR_REVIEW_STANDALONE_TUI") == "1"
        if standalone_requested and not prebuilt.is_file():
            raise RuntimeError(
                "Standalone TUI requested but pr-review-tui.exe is missing. "
                "Run `cd frontend/tui && bun run scripts/build-tui.ts --stage` first."
            )
        if standalone_requested:
            # The prebuilt exe is gitignored, so ordinary package selection
            # omits it. An explicit force-include makes this an optional
            # self-contained no-Bun release when `bun run ... --stage` was run.
            build_data["force_include"][str(prebuilt)] = "ai_pr_review/tui_static/pr-review-tui.exe"
        build_data["tag"] = "py3-none-win_amd64"
        build_data["pure_python"] = False
