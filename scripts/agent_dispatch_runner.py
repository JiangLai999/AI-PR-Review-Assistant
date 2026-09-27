"""Headless dispatcher for the local agent bus (.agent-bus).

Why this exists: the interactive claude-code / mimocode terminals only poll
the bus while a human keeps them awake. This runner instead drives them in
headless mode, so Codex can dispatch work without a human ping.

Flow per pending task:

1. ``agent_bridge.py claim <task_id> --agent <agent>``  (so the status
   machine is honest even if the headless agent dies halfway);
2. launch the headless CLI with a dispatch prompt telling it to read the
   task JSON and do the work inside its ``write_scope``;
3. while it runs, poll for the report file: headless CLIs sometimes stay
   alive after finishing (no stdin to close), so once a report exists we
   give the process a short grace period and then terminate it;
4. on failure/timeout: ``agent_bridge.py release`` and report the error;
   on success: the agent itself is expected to run ``agent_bridge.py report``
   (the dispatch prompt spells it out).

Permission note: ``claude -p`` with only ``--permission-mode acceptEdits`` in
this environment auto-**denies** every command execution (no approval surface
exists in headless mode), which is how the first run ended up "blocked with
code written but tests never executed". The runner therefore passes
``--dangerously-skip-permissions`` for claude and
``--dangerously-skip-permissions`` for mimo, i.e. the agents run with full
local trust. Tasks must stay inside their ``write_scope``; the bus constraints
already forbid git operations and credential access.

Usage:
    python scripts/agent_dispatch_runner.py --dry-run
    python scripts/agent_dispatch_runner.py                       # all pending
    python scripts/agent_dispatch_runner.py --task-id claude-chat-routing
    python scripts/agent_dispatch_runner.py --timeout 2400
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUS = ROOT / ".agent-bus"
TASKS = BUS / "tasks"
RUNS = BUS / "runs"
REPORT_DIR = BUS / "reports"
REPORT_GRACE_SECONDS = 90
POLL_SECONDS = 5
# Agents that stream progress into their log (mimo does; `claude -p` stays
# silent until the end). For those we can detect a genuinely stuck worker as
# "the log has not grown for N seconds" — a real one was found this way at
# 21:44-21:52 (0% CPU, no output, no file changes).
# 这些 CLI 会持续往 stdout 打进度，因此"日志 N 秒没长"可以判为卡住
VERBOSE_AGENTS = {"mimo", "codex", "opencode", "workbuddy"}
STALL_SECONDS = 600
# 每 N 秒打印一次"日志多久没长"的心跳，便于事后判断卡住检测到底有没有跑
HEARTBEAT_SECONDS = 120

CLAUDE_CANDIDATES = (
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/claude.cmd",
)
MIMO_CANDIDATES = (
    pathlib.Path.home() / ".mimocode/bin/mimo.exe",
    pathlib.Path.home() / ".mimocode/bin/mimo.cmd",
)
CODEX_CANDIDATES = (
    # 用 .cmd：.ps1 不能直接被 subprocess 执行，CMD 包装器在两种 shell 下都可用
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/codex.cmd",
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/codex.exe",
)
OPENCODE_CANDIDATES = (
    pathlib.Path(os.environ.get("APPDATA", ""))
    / "npm/node_modules/opencode-ai/bin/opencode.exe",
)
# WorkBuddy 自带 headless agent CLI（Electron 应用 resources 下的 codebuddy）。
# 入口是 Node 脚本，所以命令行是 `node <cli>/bin/codebuddy ...`。
# 可用 WORKBUDDY_CLI 覆盖入口路径、WORKBUDDY_MODEL 覆盖模型（例如 deepseek 系）。
WORKBUDDY_CANDIDATES = (
    pathlib.Path(os.environ.get("WORKBUDDY_CLI", ""))
    if os.environ.get("WORKBUDDY_CLI")
    else pathlib.Path(r"G:\workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"),
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@genie/agent-cli/bin/codebuddy",
    pathlib.Path(os.environ.get("APPDATA", "")) / "npm/codebuddy.cmd",
)
# 该 CLI 是 Node 脚本；_find_exe 找不到候选时会回落到 PATH 上的 node。
NODE_CANDIDATES = (
    pathlib.Path(os.environ.get("ProgramFiles", "")) / "nodejs/node.exe",
    pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/nodejs/node.exe",
)
# 用户指定的协作模型（provider/model 形式，opencode 必须显式给 -m，否则用默认模型）
OPENCODE_MODEL = "opencode/mimo-v2.6-flash-free"

DISPATCH_PROMPT = """你是 {root} 项目的协作 agent（{agent}）。任务 {task_id} 已经由调度器用你的名义认领。

严格按以下流程执行：
1. 读取 {root}/.agent-bus/tasks/{task_id}.json，重点是其中的 "prompt"、"write_scope" 与 "constraints" 字段。
2. 按 prompt 完成开发工作；只允许修改 write_scope 内的文件；不要做 git 操作；不要读取或输出任何凭据。
3. 验证：按 prompt 里的验证步骤运行测试（TEMP/TMP 指向 {temp_dir}），并记录真实数字。
4. 完成后必须运行上报命令：
   python scripts/agent_bridge.py report {task_id} --agent {agent} --status completed --summary "<一句话摘要>" --evidence "<命令与测试数字>" --blocker "<未决项，可为空>"
   如果确实无法完成，用 --status blocked 上报并说明原因。
"""


def _find_exe(candidates: tuple[pathlib.Path, ...], name: str) -> str | None:
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    return shutil.which(name)


def _load_pending(task_id: str | None) -> list[dict]:
    if not TASKS.is_dir():
        return []
    pending: list[dict] = []
    for path in sorted(TASKS.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("status", "")) != "pending":
            continue
        if task_id and payload.get("task_id") != task_id:
            continue
        pending.append(payload)
    return pending


def _run_bridge(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "agent_bridge.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _agent_command(
    agent: str, prompt: str, temp_dir: pathlib.Path
) -> tuple[list[str], dict[str, str]] | None:
    env = os.environ.copy()
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    if agent == "claude":
        exe = _find_exe(CLAUDE_CANDIDATES, "claude")
        if exe is None:
            return None
        env.setdefault("CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT", "1")
        env.setdefault("ANTHROPIC_MODEL", "deepseek-flash[1M]")
        return [
            exe,
            "-p",
            prompt,
            # Headless mode has no approval surface: without this flag every
            # Bash/Python call is auto-denied and the agent cannot even run
            # pytest or write its own report file.
            "--dangerously-skip-permissions",
        ], env
    if agent == "mimo":
        exe = _find_exe(MIMO_CANDIDATES, "mimo")
        if exe is None:
            return None
        return [
            exe,
            "run",
            prompt,
            "--dangerously-skip-permissions",
            "--dir",
            str(ROOT),
        ], env
    if agent == "codex":
        # `codex exec` 是官方非交互入口；与 claude/mimo 同样跳过确认（本地受控环境，
        # 任务自带 write_scope 约束）。真实模型由用户的 ~/.codex/config.toml 决定
        # （当前是 GLM-5.3-Flash + 第三方中转），运行器不覆盖它。
        exe = _find_exe(CODEX_CANDIDATES, "codex")
        if exe is None:
            return None
        return [
            exe,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--cd",
            str(ROOT),
            prompt,
        ], env
    if agent == "opencode":
        # `opencode run` 是非交互入口；--auto 自动批准未显式拒绝的权限（本地受控
        # 环境 + 任务的 write_scope 约束）；-m 必须显式指定，否则会用它的默认模型。
        exe = _find_exe(OPENCODE_CANDIDATES, "opencode")
        if exe is None:
            return None
        return [
            exe,
            "run",
            "--auto",
            "--dir",
            str(ROOT),
            "-m",
            OPENCODE_MODEL,
            prompt,
        ], env
    if agent == "workbuddy":
        # WorkBuddy（腾讯 CodeBuddy 系）自带的 headless CLI：`-p` 非交互输出、
        # `-y` 跳过权限确认（本地受控环境 + 任务 write_scope 约束）、
        # `--output-format stream-json` 让日志持续增长，从而启用失速检测。
        # 模型默认走账号配置；需要固定模型时设 WORKBUDDY_MODEL（如 deepseek 系）。
        cli = _find_exe(WORKBUDDY_CANDIDATES, "codebuddy")
        node = _find_exe(NODE_CANDIDATES, "node")
        if cli is None or node is None:
            return None
        command = [
            node,
            cli,
            "-p",
            prompt,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
        ]
        model = os.environ.get("WORKBUDDY_MODEL", "").strip()
        if model:
            command += ["--model", model]
        return command, env
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=2400, help="seconds per task")
    args = parser.parse_args(argv[1:])

    tasks = _load_pending(args.task_id or None)
    if not tasks:
        print("no pending tasks")
        return 0

    RUNS.mkdir(parents=True, exist_ok=True)
    failures = 0
    for task in tasks:
        task_id = str(task.get("task_id"))
        agent = str(task.get("agent", "")).strip().lower()
        temp_dir = ROOT / f".pytest_{agent}"
        temp_dir.mkdir(exist_ok=True)
        prompt = DISPATCH_PROMPT.format(
            root=ROOT, agent=agent, task_id=task_id, temp_dir=temp_dir
        )
        prepared = _agent_command(agent, prompt, temp_dir)
        if prepared is None:
            print(f"[{task_id}] SKIP: no CLI found for agent={agent}")
            failures += 1
            continue
        cmd, env = prepared

        if args.dry_run:
            print(f"[{task_id}] agent={agent} temp={temp_dir}")
            print("  cmd:", " ".join(f'"{c}"' if " " in c else c for c in cmd[:2]), "...")
            continue

        claim = _run_bridge("claim", task_id, "--agent", agent)
        if claim.returncode != 0:
            print(f"[{task_id}] claim failed: {claim.stdout.strip()} {claim.stderr.strip()}")
            failures += 1
            continue
        print(f"[{task_id}] claimed by {agent}; launching headless CLI (timeout {args.timeout}s)")

        log_path = RUNS / f"{task_id}-{dt.datetime.now():%Y%m%d-%H%M%S}.log"
        started = time.perf_counter()
        report = REPORT_DIR / f"{task_id}.json"
        report_seen_at: float | None = None
        timed_out = False
        try:
            with log_path.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(
                    cmd,
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                deadline = started + args.timeout
                last_size = 0
                last_progress_at = started
                last_heartbeat_at = started
                while proc.poll() is None:
                    now = time.perf_counter()
                    if now > deadline:
                        timed_out = True
                        proc.terminate()
                        break
                    if agent in VERBOSE_AGENTS:
                        try:
                            size = log_path.stat().st_size
                        except OSError:
                            size = last_size
                        if size != last_size:
                            last_size = size
                            last_progress_at = now
                        elif now - last_progress_at > STALL_SECONDS:
                            print(
                                f"[{task_id}] stalled: no log growth for "
                                f"{STALL_SECONDS}s; terminating worker",
                                flush=True,
                            )
                            proc.terminate()
                            break
                        if now - last_heartbeat_at >= HEARTBEAT_SECONDS:
                            last_heartbeat_at = now
                            print(
                                f"[{task_id}] heartbeat: log={last_size}B "
                                f"idle={now - last_progress_at:.0f}s "
                                f"(stall at {STALL_SECONDS}s)",
                                flush=True,
                            )
                    if report.exists():
                        if report_seen_at is None:
                            report_seen_at = now
                        elif now - report_seen_at > REPORT_GRACE_SECONDS:
                            # The agent finished and reported, but the headless
                            # CLI kept its process alive (no stdin to close).
                            proc.terminate()
                            break
                    time.sleep(POLL_SECONDS)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
            elapsed = time.perf_counter() - started
            reported = report.exists()
            if reported:
                status = "reported"
            elif timed_out:
                status = f"TIMEOUT after {elapsed:.0f}s"
            else:
                status = f"NO REPORT (exit {proc.returncode})"
            print(f"[{task_id}] finished in {elapsed:.0f}s -> {status}; log: {log_path}")
            if not reported:
                failures += 1
                # No report = the claim must go back to the bus, whether the
                # process timed out, crashed, or was killed as a stuck worker.
                print(f"[{task_id}] releasing claim (no report)")
                _run_bridge("release", task_id, "--agent", agent)
        except OSError as exc:
            print(f"[{task_id}] failed to launch: {exc}")
            _run_bridge("release", task_id, "--agent", agent)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
