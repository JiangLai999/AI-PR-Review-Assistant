"""安装脚本守卫：官网一键安装命令不能回退到"只认 Python 3.12"或吞掉失败。

回归点（2026-09-29 实测）：
1. ``install.ps1`` 原先只探测 ``py -3.12``，且用 try/catch 判断成功 —— Windows
   PowerShell 5.1 不会因为原生命令非 0 退出而抛异常，于是只装 3.13 的机器上
   脚本继续用 ``py -3.12``，最后抛 "Unable to determine Python version from:
   No suitable Python runtime found"。
2. ``pipx install`` 失败后脚本仍打印 "Installation completed"（同样因为原生命令
   失败不触发 $ErrorActionPreference="Stop"）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "install.ps1"
SH = ROOT / "install.sh"


def test_install_ps1_probes_multiple_python_candidates() -> None:
    text = PS1.read_text(encoding="utf-8")
    for candidate in ('@("py", "-3.12")', '@("py", "-3.13")', '@("py", "-3")', '@("python")'):
        assert candidate in text, f"install.ps1 缺少 Python 候选：{candidate}"
    assert "function Test-PythonCommand" in text, "install.ps1 必须先校验候选能否真正运行"
    assert "$versionText -notmatch 'Python\\s+(\\d+)\\.(\\d+)'" in text


def test_install_ps1_checks_pipx_exit_code() -> None:
    text = PS1.read_text(encoding="utf-8")
    assert (
        text.count("$LASTEXITCODE -ne 0") >= 2
    ), "install.ps1 必须在 pipx 引导与 pipx install 之后显式检查 $LASTEXITCODE"
    assert "--backend pip" in text, "uv 后端失败后应回落一次 pip 后端"


def test_install_sh_accepts_any_python_at_least_312() -> None:
    text = SH.read_text(encoding="utf-8")
    assert "set -eu" in text, "install.sh 必须在失败时中止"
    assert "if need_command python3" in text and "if need_command python" in text
    assert 'MINOR" -lt 12' in text, "install.sh 必须校验 >= 3.12 而不是写死 3.12"
    assert "pipx install --force" in text
