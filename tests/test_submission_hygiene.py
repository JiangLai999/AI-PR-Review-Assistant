"""提交包密钥卫生守卫的回归测试。

对应交付物：`scripts/check_submission_hygiene.py`。

**安全约束（与守卫脚本一致）**：本文件**不读取** `.ai_pr_review/config.local.json`
或任何本地凭据文件的内容，也不打印任何密钥原值。构造样例时用的都是本地生成的
假字符串。

为什么除了"跑一遍退出码 0"之外还要写单测：一个恒为 0 的守卫和没有守卫在 CI 上
长得一模一样。所以这里额外钉住

1. 敏感路径判定确实会命中（否则第 1 项检查是空壳）；
2. 疑似密钥正则确实会命中**非占位符**、且会放过**占位符**（否则第 3 项检查是空壳）；
3. 掩码不泄露原值（否则守卫的输出本身就是泄露渠道）；
4. ``.gitignore`` 覆盖必检模式（否则打包时会把凭据带进去）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_submission_hygiene.py"

# 一个"看起来很真"但纯属本地构造的假 Key：长度与字符集都满足 ghp_ 前缀的规则。
# 构造方式保证它绝不可能是任何真实凭据。
FAKE_REALISTIC = "ghp_" + "Zq7XmR2vTb9LpK4wNc8YdH3sJf6Qa1Ze5Ux0Gi"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_submission_hygiene_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None, f"无法加载守卫脚本：{SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 端到端：脚本本身必须通过
# --------------------------------------------------------------------------- #


def test_guard_exits_zero_on_this_repo() -> None:
    """在当前仓库上跑守卫必须退出码 0。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, f"守卫未通过：\n{proc.stdout}\n{proc.stderr}"
    assert "[FAIL]" not in proc.stdout, proc.stdout


def test_guard_never_reads_local_credential_contents() -> None:
    """守卫的"不读凭据内容"约束必须写在代码里，而不是只写在文档里。"""
    source = SCRIPT.read_text(encoding="utf-8")

    assert ".ai_pr_review/config.local.json" in source
    # 路径常量可以出现在源码里，但绝不能出现读取/打开它的调用。
    for forbidden in ('open(".ai_pr_review', 'read_text(".ai_pr_review', "json.load(open("):
        assert forbidden not in source, f"守卫疑似直接读取凭据内容：{forbidden}"


# --------------------------------------------------------------------------- #
# 非空壳：敏感路径判定
# --------------------------------------------------------------------------- #


def test_sensitive_patterns_match_expected_paths() -> None:
    guard = _load_guard()

    must_match = (
        ".ai_pr_review/config.local.json",
        ".ai_pr_review/config.json",
        ".ai_pr_review/config.web.json",
        "web/.env",
        "secrets.env",
        "FIX_GITHUB_TOKEN.txt",
        "_p5_verify/venv/whatever.txt",
    )
    for path in must_match:
        assert guard.is_sensitive(path), f"应判定为敏感：{path}"


def test_non_sensitive_paths_are_not_flagged() -> None:
    guard = _load_guard()

    must_not_match = (
        # 只含占位符的模板是**应该提交**的，不能误伤
        ".ai_pr_review/config.local.json.example",
        "src/ai_pr_review/config.py",
        "src/ai_pr_review/config_commands.py",
        "docs/COMPLIANCE_AND_ORIGINALITY.md",
        "tests/test_submission_hygiene.py",
        "env.sample",
    )
    for path in must_not_match:
        assert not guard.is_sensitive(path), f"不应判定为敏感：{path}"


# --------------------------------------------------------------------------- #
# 非空壳：疑似密钥判定与掩码
# --------------------------------------------------------------------------- #


def _scan(guard: ModuleType, text: str) -> list[str]:
    """复用守卫的正则，模拟它对一行文本的扫描，返回未过滤的命中值。"""
    return [m.group(0) for _, pattern in guard.SECRET_PATTERNS for m in pattern.finditer(text)]


def test_secret_patterns_catch_each_supported_prefix() -> None:
    guard = _load_guard()
    samples = (
        FAKE_REALISTIC,
        "github_pat_" + "11" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "sk-" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "AKIA" + "QWERTYUIOPASDFGH",
    )

    for sample in samples:
        assert _scan(guard, f'token = "{sample}"'), f"正则漏检：{sample[:8]}…"


def test_placeholders_are_allowed_through() -> None:
    """测试夹具里的假值必须放行，否则守卫会天天红。"""
    guard = _load_guard()

    for value in (
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
        "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "sk-testsecret000000000000000000000",
        "ghp_123456789012345678901234567890123456",
    ):
        assert guard.is_placeholder(value), f"应识别为占位符：{value[:10]}…"


def test_realistic_value_is_not_treated_as_placeholder() -> None:
    guard = _load_guard()

    assert not guard.is_placeholder(FAKE_REALISTIC)


def test_mask_does_not_leak_the_secret() -> None:
    guard = _load_guard()

    masked = guard.mask(FAKE_REALISTIC)

    assert FAKE_REALISTIC not in masked
    assert masked.startswith("ghp_")
    assert f"len={len(FAKE_REALISTIC)}" in masked


def test_mask_collapses_short_values() -> None:
    guard = _load_guard()

    assert guard.mask("abcdef") == "******"


# --------------------------------------------------------------------------- #
# .gitignore 覆盖度
# --------------------------------------------------------------------------- #


def test_gitignore_covers_every_required_pattern() -> None:
    guard = _load_guard()
    lines = {
        line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }

    missing = [pattern for pattern in guard.GITIGNORE_REQUIRED if pattern not in lines]
    assert not missing, f".gitignore 缺少必检模式：{missing}"


# --------------------------------------------------------------------------- #
# 合规文档齐备
# --------------------------------------------------------------------------- #


def test_required_compliance_docs_exist_with_keywords() -> None:
    guard = _load_guard()

    for rel, keywords in guard.REQUIRED_DOCS:
        path = ROOT / rel
        assert path.is_file(), f"缺少合规文档：{rel}"
        text = path.read_text(encoding="utf-8")
        absent = [kw for kw in keywords if kw not in text]
        assert not absent, f"{rel} 缺少关键章节关键词：{absent}"
