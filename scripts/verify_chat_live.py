#!/usr/bin/env python
"""真实链路验收：本机 Ollama 端到端 chat 事件序列 vs 契约 v1。

与 `tests/test_chat_contract_events.py`（stub 验收）互补：这里**不打桩**，
直接走项目自己的 `JsonlBackend` + 真实 Ollama provider，抓完整事件序列。

只连本机 Ollama（默认 127.0.0.1:11434）；不读凭据；不发任何其它网络请求。

用法::

    python scripts/verify_chat_live.py
    python scripts/verify_chat_live.py --model qwen3.5:4b --timeout 600
    python scripts/verify_chat_live.py --json

退出码：0 = 全部断言通过；1 = 有断言失败；2 = 环境不可用（Ollama 不在线/模型缺失）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_pr_review.backend.jsonl_server import JsonlBackend  # noqa: E402

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_PROMPT = "用一句话说明什么是 SQL 注入。不要写代码，不要列表。"
DEFAULT_TIMEOUT = 600.0


def log(message: str) -> None:
    print(message, flush=True)


def probe_ollama(base_url: str) -> tuple[bool, list[str]]:
    """探活 + 列出模型名（只读，不发任何写请求）。"""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 探活失败就是要如实报告
        log(f"  Ollama 探活失败：{exc}")
        return False, []
    names = [str(item.get("name", "")) for item in payload.get("models", [])]
    return resp.status == 200, names


async def run_chat(model: str, prompt: str, timeout: float) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    """跑一轮真实 chat，返回 (事件序列, chat.send 响应, 实测耗时秒)。"""
    events: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="chat-live-") as tmp:
        backend = JsonlBackend(Path(tmp) / "config.json", event_sink=events.append)
        # 本地槽 + 短提示；超时给足（4B 思考型模型单轮可能数分钟）。
        backend._apply_setup({"runtime_profile": "local", "local_model": model})
        backend.config.ai_client.timeout_seconds = timeout

        log("  [1/2] session.create ...")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = str(session["session_id"])

        log(f"  [2/2] chat.send（{model}）... 本地推理可能需要数分钟，请耐心等待")
        started = time.perf_counter()
        response = await backend.handle(
            {
                "id": "turn",
                "method": "chat.send",
                "params": {"session_id": session_id, "text": prompt},
            }
        )
        elapsed = time.perf_counter() - started
        log(f"  chat.send 返回，实测 {elapsed:.1f}s")
    return events, (response[0] if response else {}), elapsed


def analyze(events: list[dict[str, Any]], reply: dict[str, Any], elapsed: float) -> dict[str, Any]:
    """把事件序列拆成契约 v1 关心的字段。"""
    names = [str(event.get("event", "")) for event in events]
    reasoning_parts = [str(e.get("text", "")) for e in events if e.get("event") == "assistant.reasoning_delta"]
    delta_parts = [str(e.get("text", "")) for e in events if e.get("event") == "assistant.delta"]
    finished = next((e for e in events if e.get("event") == "assistant.finished"), None)
    failed = next((e for e in events if e.get("event") == "assistant.failed"), None)

    reasoning_text = "".join(reasoning_parts)
    delta_text = "".join(delta_parts)
    result = reply.get("result") if isinstance(reply, dict) else None
    answer_text = str((finished or {}).get("text") or (result or {}).get("text") or "")
    usage = (finished or {}).get("usage")
    context = (finished or {}).get("context")

    return {
        "event_counts": {name: names.count(name) for name in sorted(set(names))},
        "event_names": names,
        "order_ok": bool(
            names
            and names[0] == "assistant.started"
            and names[-1] == "assistant.finished"
            and "assistant.failed" not in names
        ),
        "reasoning_chars": len(reasoning_text),
        "reasoning_events": len(reasoning_parts),
        "answer_chars": len(answer_text),
        "delta_chars": len(delta_text),
        "reasoning_isolated": bool(
            not reasoning_text
            or (reasoning_text not in delta_text and reasoning_text not in answer_text)
        ),
        "delta_matches_answer": delta_text == answer_text or not delta_text,
        "duration_seconds": (finished or {}).get("duration_seconds"),
        "usage": usage,
        "context": context,
        "warning": (finished or {}).get("warning"),
        "finished_reasoning_chars": len(str((finished or {}).get("reasoning") or "")),
        "failed_message": (failed or {}).get("message"),
        "elapsed_seconds": round(elapsed, 3),
    }


def evaluate(report: dict[str, Any]) -> list[dict[str, Any]]:
    """六条断言（契约 v1 的真实链路版）。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add(
        "a. 事件顺序 started→…→finished",
        report["order_ok"],
        f"events={report['event_counts']}"
        + (f" failed={report['failed_message']}" if report["failed_message"] else ""),
    )
    add(
        "b. 思考与正文隔离",
        report["reasoning_isolated"],
        f"reasoning={report['reasoning_chars']}chars, delta={report['delta_chars']}chars",
    )
    duration = report["duration_seconds"]
    add(
        "c. duration_seconds>0",
        isinstance(duration, (int, float)) and float(duration) > 0,
        f"finished.duration_seconds={duration!r}, wall_clock={report['elapsed_seconds']}s",
    )
    usage = report["usage"]
    add(
        "d. usage 真实返回",
        isinstance(usage, dict) and int(usage.get("prompt_tokens") or 0) > 0,
        f"usage={usage!r}（本地端点可能忽略→这本身就是差异，记录不判代码对错）",
    )
    context = report["context"]
    add(
        "e. context.used_tokens 有值",
        isinstance(context, dict) and int((context or {}).get("used_tokens") or 0) > 0,
        f"context={context!r}",
    )
    add(
        "f. 答案非空（预算兜底有效）",
        report["answer_chars"] > 0,
        f"answer={report['answer_chars']}chars, warning={report['warning']!r}",
    )
    return checks


def render(report: dict[str, Any], checks: list[dict[str, Any]], model: str) -> None:
    log("")
    log("=" * 72)
    log(f"真实链路验收 · Ollama · {model}")
    log("=" * 72)
    log(f"事件计数 : {report['event_counts']}")
    log(f"思考长度 : {report['reasoning_chars']} 字符（{report['reasoning_events']} 个 delta 帧）")
    log(f"正文长度 : {report['delta_chars']} 字符（流式累积）")
    log(f"答案长度 : {report['answer_chars']} 字符")
    log(f"finished : duration={report['duration_seconds']!r} warning={report['warning']!r}")
    log(f"usage    : {report['usage']!r}")
    log(f"context  : {report['context']!r}")
    log("")
    log("断言：")
    for check in checks:
        mark = "PASS" if check["passed"] else "FAIL"
        log(f"  [{mark}] {check['name']}")
        log(f"         {check['detail']}")
    passed = sum(1 for c in checks if c["passed"])
    log("")
    log(f"结论：{passed}/{len(checks)} 条通过")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama 模型名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Ollama 根地址（默认本机 11434）")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="验收提示词")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单轮超时秒（默认 600）")
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    args = parser.parse_args(argv)

    if not args.json:
        log(f"探活 Ollama：{args.base_url}")
    alive, models = probe_ollama(args.base_url)
    if not alive:
        log("错误：Ollama 不在线（检查 127.0.0.1:11434）")
        return 2
    if models and args.model not in models:
        log(f"警告：模型 {args.model!r} 不在本机列表 {models}，仍继续（Ollama 可能自动拉取/报错）")
    if not args.json:
        log(f"  在线，模型列表：{models}")

    events, reply, elapsed = asyncio.run(run_chat(args.model, args.prompt, args.timeout))
    if not reply.get("ok"):
        log(f"chat.send 失败：{reply.get('error')!r}")
        return 2

    report = analyze(events, reply, elapsed)
    checks = evaluate(report)

    if args.json:
        print(json.dumps({"report": report, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        render(report, checks, args.model)

    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
