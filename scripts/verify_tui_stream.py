"""Smoke-test live JSONL Chat streaming against a locally running Ollama.

Manual-only: no secrets, no remote API calls, and no persistent config changes.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ai_pr_review.config import AppConfig, ModelProviderConfig, ProviderConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tui-stream-") as workdir:
        config_path = Path(workdir) / "config.json"
        config = AppConfig.from_env()
        config.provider = ProviderConfig.from_model_provider(
            ModelProviderConfig.from_name("ollama", model_name=args.model)
        )
        config.ai_client.api_key = ""
        config.github_token = ""
        config.pr_fetcher.github_token = ""
        config.ai_client.max_tokens = 4096
        config._sync_runtime_sections()
        config.save(config_path, save_key=False)

        env = os.environ.copy()
        env["AI_PR_REVIEW_CONFIG"] = str(config_path)
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [sys.executable, "-m", "ai_pr_review.backend.jsonl_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        lines: queue.Queue[dict] = queue.Queue()

        def read_frames() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(json.loads(line))

        threading.Thread(target=read_frames, daemon=True).start()

        def send(request: dict) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()

        try:
            send({"id": "session", "method": "session.create"})
            session = lines.get(timeout=args.timeout)["result"]["session_id"]
            start = time.monotonic()
            send(
                {
                    "id": "turn",
                    "method": "chat.send",
                    "params": {
                        "session_id": session,
                        "text": "List ten one-word colors, numbered, one per line. No explanation.",
                    },
                }
            )
            first_delta: float | None = None
            chunks: list[str] = []
            while True:
                frame = lines.get(timeout=args.timeout)
                if frame.get("event") == "assistant.delta":
                    if first_delta is None:
                        first_delta = time.monotonic() - start
                    chunks.append(frame["text"])
                if frame.get("id") != "turn":
                    continue
                if not frame.get("ok"):
                    print("Chat failed:", frame.get("error", {}).get("message", "unknown"))
                    return 1
                completed = time.monotonic() - start
                matched = "".join(chunks) == frame["result"]["text"]
                streamed = first_delta is not None and first_delta < completed
                print(
                    {
                        "delta_count": len(chunks),
                        "first_delta_seconds": round(first_delta or 0, 2),
                        "completed_seconds": round(completed, 2),
                        "joined_matches_final": matched,
                        "streamed_before_response": streamed,
                    }
                )
                return 0 if matched and streamed and len(chunks) > 1 else 1
        finally:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
