import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_bridge.py"), *args], check=True)


run("init")
run(
    "dispatch",
    "--agent",
    "claude",
    "--task-id",
    "claude-backend-audit",
    "--objective",
    "只读审计 Python JSONL 后端、历史隔离、session 重建和模型路由一致性。",
    "--scope",
    "docs/DEV_RECORD.md",
    "--prompt",
    "读取当前项目源码和测试，重点核对 config.py、jsonl_server.py、BackendClient 协议。只读，不改源码。将证据型报告写入 docs/DEV_RECORD.md，包含问题分级、路径、行号、复现命令、验证结论。",
)
run(
    "dispatch",
    "--agent",
    "mimo",
    "--task-id",
    "mimo-tui-audit",
    "--objective",
    "只读审计 OpenTUI Composer、命令菜单、焦点、窄终端布局和源码/安装版启动差异。",
    "--scope",
    "docs/DEV_RECORD.md",
    "--prompt",
    "读取 frontend/tui 和本地 MiMo-Code 参考源码，结合当前 TUI 实际交互设计。只读，不改源码。将 UI/交互审计写入 docs/DEV_RECORD.md，包含复现步骤、截图/终端证据、问题分级和建议。",
)
