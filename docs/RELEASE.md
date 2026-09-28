# Release Guide

> 最后更新：2026-09-21 · 状态：对外文档

## Distribution Strategy

This project should ship through GitHub as the verified installation source while the package name is shared on PyPI.

1. GitHub is the default source for this repository.
2. PyPI may be used only after the package name and published artifact have been independently verified.

For a CLI tool, the best user-facing install target is `pipx` because it:

- creates an isolated environment automatically
- exposes the `pr-review` command globally
- avoids polluting the user's main Python environment

## Recommended User Commands

### Primary: install from GitHub

```bash
pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"
```

### Optional: install from PyPI after artifact verification

```bash
pipx install ai-pr-review
```

### One-line bootstrap from GitHub script

Linux/macOS, install the verified GitHub source:

```bash
curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh
```

Linux/macOS, force GitHub source:

```bash
curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | INSTALL_SOURCE=github GITHUB_REPOSITORY=JiangLai999/AI-PR-Review-Assistant sh
```

Windows PowerShell, install the verified GitHub source:

```powershell
irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex
```

Windows PowerShell, force GitHub source:

```powershell
 $env:INSTALL_SOURCE='github'; $env:GITHUB_REPOSITORY='JiangLai999/AI-PR-Review-Assistant';irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex
```

## Why This Is The Best Fit

- GitHub installation is the verified source for this repository.
- PyPI installation is available only after the artifact and package ownership have been verified.
- Remote install scripts give a true one-line onboarding path.
- `pipx` matches CLI distribution best practices better than plain `pip install`.
- The same package entry point works for both channels.

## Packaging Requirements

The package must provide:

- a valid `pyproject.toml`
- a `project.scripts` entry for `pr-review`
- source and wheel build support
- a README that documents both install channels

## Release Flow

1. Update version in `pyproject.toml` and `src/ai_pr_review/__init__.py`.
2. Push the version commit and tag a release in GitHub.
3. GitHub Actions builds the package and publishes it to PyPI when the artifact has been verified.
4. The repository documentation continues to recommend GitHub installation while the package name is shared.
5. Users who need unreleased changes install from GitHub.

## Validation Checklist

Before publishing:

```bash
pip install -e .[dev]
pytest
python -m build
twine check dist/*
```

After publishing, verify both channels:

```bash
pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"
# Only after verifying the published artifact:
pipx install ai-pr-review
pr-review --help
```
