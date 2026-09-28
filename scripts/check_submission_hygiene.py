#!/usr/bin/env python3
"""提交包密钥卫生守卫。

参赛提交包最常见的两类事故是「把本地凭据一起打包」和「Key 曾经明文出现过却没轮换」。
本守卫把可机器判定的那部分钉死，让人工只需处理「轮换」这不可自动化的动作。

检查项
------
1. **敏感路径是否被 Git 跟踪** —— 用 ``git ls-files``（只读）判断，见 :data:`SENSITIVE_PATTERNS`。
2. **``.gitignore`` 是否覆盖这些模式** —— 缺失时只在文件**末尾追加**，
   不删除、不重排已有内容（:data:`GITIGNORE_REQUIRED`）。
3. **已跟踪文本文件里是否残留疑似真实密钥** —— 见 :data:`SECRET_PATTERNS`。
   命中时只打印 ``文件:行号 [已掩码]``，**绝不输出命中原值**。
4. **``dist/`` ``build/`` 产物是否夹带敏感路径** —— 用 ``zipfile`` / ``tarfile``
   只列目录名，不解包；没有产物时跳过并提示。
5. **许可与权属文档是否齐备** —— 见 :data:`REQUIRED_DOCS`。

安全约束
--------
- 只用 Python 标准库。
- **不读取** ``.ai_pr_review/config.local.json``（或任何 ``.ai_pr_review/config*.json``）
  的**内容**，只按**路径**判定；:data:`NEVER_READ` 里的路径在扫描阶段直接跳过。
- 不执行任何 ``git`` 写操作（不 add / commit / checkout / reset / clean）。
- 唯一的写操作是向 ``.gitignore`` **末尾追加**缺失模式，可用 ``--check-only`` 关掉。

退出码：0 = 全部通过；1 = 有未通过项。
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# 判定口径
# --------------------------------------------------------------------------- #

#: 敏感路径模式。``_SENSITIVE_TRACKED`` 里的每一项都要同时满足：不被 Git 跟踪、
#: 且被 ``.gitignore`` 覆盖。注意 ``.ai_pr_review/config.local.json.example``
#: 是只含占位符的模板，**应当提交**，因此这里用精确路径而不是 ``config*.json`` 通配。
SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".ai_pr_review/config.local.json",
    ".ai_pr_review/config.json",
    "*.web.json",
    ".env",
    "secrets.env",
    "FIX_GITHUB_TOKEN.txt",
    "_p5_verify/*",
)

#: ``.gitignore`` 必须出现的行（逐行精确匹配，去空白）。
GITIGNORE_REQUIRED: tuple[str, ...] = (
    ".ai_pr_review/config.local.json",
    ".ai_pr_review/config.json",
    "*.web.json",
    ".env",
    "secrets.env",
    "FIX_GITHUB_TOKEN.txt",
    "_p5_verify/",
)

#: 疑似真实密钥。命中原值一律不打印。
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-classic-token", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("github-fine-grained-token", re.compile(r"github_pat_[A-Za-z0-9_]{30,}")),
    ("sk-style-api-key", re.compile(r"sk-[A-Za-z0-9]{30,}")),
    ("aws-access-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
)

#: 占位符特征：命中任一即视为测试用的假值，放行。
#: 仓库里真实存在的样例形如 ``ghp_abcdefghij...``、``sk-testsecret000...``、
#: ``ghp_xxxx...``、``ghp_1234567890...``。
_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "xxx",
    "test",
    "example",
    "abcdef",
    "dummy",
    "fake",
    "sample",
    "placeholder",
    "1234567890",
)

#: 二进制 / 体积闸门：这些不按文本扫，也不读内容。
_SKIP_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".whl", ".exe"}
)
_MAX_TEXT_BYTES = 8 * 1024 * 1024

#: **只按路径判定、绝不读取内容**的本地凭据文件。
NEVER_READ: tuple[str, ...] = (
    ".ai_pr_review/config.local.json",
    ".ai_pr_review/config.json",
    ".ai_pr_review/config.web.json",
)

#: 产物目录（只看压缩包内的路径名，不解包）。
_ARTIFACT_DIRS: tuple[str, ...] = ("dist", "build")
_ARCHIVE_SUFFIXES: frozenset[str] = frozenset({".whl", ".zip", ".tar.gz", ".tgz"})

#: 合规文档与其必须出现的关键词。
REQUIRED_DOCS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "THIRD_PARTY_NOTICES.md",
        (
            "商标声明",
            "SIL OFL",
            "LGPL",
            "GreenSock Standard License",
            "二进制",
            "PyGithub",
            "solid-js",
        ),
    ),
    (
        "docs/COMPLIANCE_AND_ORIGINALITY.md",
        (
            "团队权属声明",
            "AI 生成内容",
            "第三方权利归属",
            "免责",
            "密钥",
            "MIT",
        ),
    ),
)


class Report:
    """收集检查结果；``ok`` 为假时以退出码 1 收场。"""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failures: list[str] = []
        self.notes: list[str] = []

    def ok(self, message: str) -> None:
        self.passed.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #


def mask(value: str) -> str:
    """掩码：只留前 4 位与后 2 位，长度归一化到原值之外不泄露信息。"""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:4]}…{value[-2:]}(len={len(value)})"


def is_placeholder(value: str) -> bool:
    """明显的占位符（测试夹具 / 文档示例）不算真实密钥。"""
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    # 全是同一个字符重复（ghp_aaaa… / sk-0000…）
    tail = re.sub(r"^[A-Za-z_]+-?", "", value)
    return len(tail) > 8 and len(set(tail)) == 1


def is_sensitive(relpath: str) -> bool:
    """仓库相对路径是否命中敏感模式。

    同时按**整条路径**与**basename**判定：``web/.env`` 和仓库根目录的 ``.env``
    一样危险，但 ``src/ai_pr_review/config.py`` 不是 ``.ai_pr_review/config.json``。
    """
    normalized = relpath.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    return any(
        normalized == pattern
        or fnmatch.fnmatch(normalized, pattern)
        or fnmatch.fnmatch(basename, pattern)
        for pattern in SENSITIVE_PATTERNS
    )


def tracked_files(root: Path) -> list[str] | None:
    """``git ls-files``（只读）。返回 None 表示拿不到列表。"""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def read_gitignore(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def iter_text_lines(path: Path) -> list[str]:
    """按行读文本文件；疑似二进制或超限则返回空列表（**不抛错**）。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if len(raw) > _MAX_TEXT_BYTES:
        return []
    if b"\0" in raw[:65536]:
        return []
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return []


# --------------------------------------------------------------------------- #
# 检查 1：敏感路径是否被 Git 跟踪
# --------------------------------------------------------------------------- #


def check_tracked_sensitive(root: Path, report: Report) -> list[str]:
    files = tracked_files(root)
    if files is None:
        report.fail("无法执行 `git ls-files`（不在 Git 仓库内，或 git 不可用）")
        return []
    leaked = sorted(rel for rel in files if is_sensitive(rel))
    if leaked:
        report.fail(
            f"{len(leaked)} 个敏感路径被 Git 跟踪，必须先停止跟踪并轮换凭据："
            + ", ".join(leaked[:10])
        )
    else:
        report.ok(f"敏感路径未被 Git 跟踪（检查 {len(SENSITIVE_PATTERNS)} 类模式）")
    return files


# --------------------------------------------------------------------------- #
# 检查 2：.gitignore 覆盖度
# --------------------------------------------------------------------------- #


def check_gitignore(root: Path, report: Report, *, fix: bool) -> None:
    path = root / ".gitignore"
    lines = read_gitignore(root)
    existing = {line.strip() for line in lines}
    missing = [pattern for pattern in GITIGNORE_REQUIRED if pattern not in existing]
    if not missing:
        report.ok(f".gitignore 覆盖全部 {len(GITIGNORE_REQUIRED)} 个必检模式")
        return

    if not fix:
        report.fail(f".gitignore 缺少：{', '.join(missing)}")
        return

    try:
        # 沿用文件既有的换行风格：`.gitattributes` 把 `.gitignore` 钉成 LF，
        # 但别的仓库可能是 CRLF，混写会改变 git 的模式匹配语义。
        existing_bytes = path.read_bytes() if path.exists() else b""
        eol = "\r\n" if b"\r\n" in existing_bytes else "\n"
        # 追加块与原内容之间恰好隔一个空行，且绝不改动上面的任何一行。
        if existing_bytes and not existing_bytes.endswith(eol.encode("ascii") * 2):
            separator = eol if existing_bytes.endswith(eol.encode("ascii")) else eol * 2
        else:
            separator = ""
        block = [f"# 提交包密钥卫生守卫追加（scripts/check_submission_hygiene.py）", *missing]
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(separator + eol.join(block) + eol)
    except OSError as exc:
        report.fail(f".gitignore 追加失败：{exc}")
        return
    report.ok(f".gitignore 已追加缺失模式：{', '.join(missing)}")


# --------------------------------------------------------------------------- #
# 检查 3：已跟踪文本文件中的疑似真实密钥
# --------------------------------------------------------------------------- #


def check_secrets(root: Path, files: list[str], report: Report) -> None:
    hits: list[str] = []
    scanned = 0
    for rel in files:
        if is_sensitive(rel) or rel in NEVER_READ or rel.startswith("_p5_verify/"):
            continue
        if Path(rel).suffix.lower() in _SKIP_SUFFIXES:
            continue
        absolute = root / rel
        if not absolute.is_file():
            continue
        scanned += 1
        for lineno, line in enumerate(iter_text_lines(absolute), 1):
            for label, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if is_placeholder(value):
                        continue
                    hits.append(f"{rel}:{lineno} [{label} {mask(value)}]")

    if hits:
        report.fail(
            f"{len(hits)} 处疑似真实密钥（已掩码，请轮换后改用环境变量）：\n    "
            + "\n    ".join(hits[:20])
        )
    else:
        report.ok(
            f"已跟踪文本文件未发现疑似真实密钥（扫描 {scanned} 个文件，"
            f"{len(SECRET_PATTERNS)} 条模式）"
        )


# --------------------------------------------------------------------------- #
# 检查 4：dist / build 产物
# --------------------------------------------------------------------------- #


def _archive_sensitive_names(archive: Path) -> list[str]:
    names: list[str] = []
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                names = tf.getnames()
    except (OSError, zipfile.BadZipFile, tarfile.TarError):
        return []
    hits = []
    for name in names:
        parts = name.replace("\\", "/").split("/")
        # 产物包会带一层顶层目录，所以按**任意路径段**判定而不是整串匹配。
        if any(is_sensitive(seg) or seg == "_p5_verify" for seg in parts):
            hits.append(name)
        if any(seg in {".env", "secrets.env"} for seg in parts):
            hits.append(name)
    return sorted(set(hits))


def check_artifacts(root: Path, report: Report) -> None:
    archives: list[Path] = []
    for name in _ARTIFACT_DIRS:
        directory = root / name
        if not directory.is_dir():
            continue
        archives.extend(
            p
            for p in sorted(directory.iterdir())
            if p.is_file() and any(str(p.as_posix()).endswith(s) for s in _ARCHIVE_SUFFIXES)
        )

    if not archives:
        report.note("未发现 dist/ 或 build/ 产物，跳过压缩包检查（构建后请复跑本守卫）")
        return

    bad: list[str] = []
    for archive in archives:
        for name in _archive_sensitive_names(archive):
            bad.append(f"{archive.relative_to(root).as_posix()} -> {name}")
    if bad:
        report.fail(f"{len(bad)} 个产物内含敏感路径，必须重新打包：\n    " + "\n    ".join(bad))
    else:
        report.ok(f"{len(archives)} 个产物均不含敏感路径")


# --------------------------------------------------------------------------- #
# 检查 5：许可与权属文档
# --------------------------------------------------------------------------- #


def check_required_docs(root: Path, report: Report) -> None:
    missing: list[str] = []
    thin: list[str] = []
    for rel, keywords in REQUIRED_DOCS:
        path = root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        absent = [kw for kw in keywords if kw not in text]
        if absent:
            thin.append(f"{rel} 缺少关键词：{', '.join(absent)}")
    if missing:
        report.fail(f"缺少合规文档：{', '.join(missing)}")
    if thin:
        report.fail("；".join(thin))
    if not missing and not thin:
        report.ok(f"许可与权属文档齐备且含关键章节（{len(REQUIRED_DOCS)} 份）")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def run(root: Path, *, fix: bool) -> Report:
    report = Report()
    files = check_tracked_sensitive(root, report)
    check_gitignore(root, report, fix=fix)
    if files is not None:
        check_secrets(root, files, report)
    check_artifacts(root, report)
    check_required_docs(root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检查提交包是否夹带本地凭据，以及许可 / 权属文档是否齐备。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="仓库根目录（默认：脚本所在仓库的根目录）",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只报告，不向 .gitignore 追加缺失模式",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    report = run(root, fix=not args.check_only)

    print(f"提交包密钥卫生守卫 · root={root}")
    for message in report.passed:
        print(f"  [PASS] {message}")
    for message in report.notes:
        print(f"  [NOTE] {message}")
    for message in report.failures:
        print(f"  [FAIL] {message}")

    if report.failures:
        print(f"\n结果：{len(report.failures)} 项未通过，请按上方提示处理后复跑。")
        return 1
    print(f"\n结果：全部 {len(report.passed)} 项通过（不含凭据内容输出）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
