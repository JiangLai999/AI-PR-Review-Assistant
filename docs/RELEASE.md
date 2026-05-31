# Release Guide

## Distribution Strategy

This project should ship through two installation channels:

1. PyPI as the default and most stable source.
2. GitHub as the fallback source for unreleased fixes, testing, and users who prefer direct install from the repository.

For a CLI tool, the best user-facing install target is `pipx` because it:

- creates an isolated environment automatically
- exposes the `pr-review` command globally
- avoids polluting the user's main Python environment

## Recommended User Commands

### Primary: install from PyPI

```bash
pipx install ai-pr-review
```

### Fallback: install from GitHub

```bash
 pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"
```

### One-line bootstrap from GitHub script

Linux/macOS, default to PyPI:

```bash
 curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh
```

Linux/macOS, force GitHub source:

```bash
 curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | INSTALL_SOURCE=github GITHUB_REPOSITORY=JiangLai999/AI-PR-Review-Assistant sh
```

Windows PowerShell, default to PyPI:

```powershell
 irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex
```

Windows PowerShell, force GitHub source:

```powershell
 $env:INSTALL_SOURCE='github'; $env:GITHUB_REPOSITORY='JiangLai999/AI-PR-Review-Assistant'; irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex
```

## Why This Is The Best Fit

- PyPI gives the shortest stable install command.
- GitHub install covers users who want latest main branch code.
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
3. GitHub Actions builds the package and publishes it to PyPI.
4. Users install from PyPI with `pipx install ai-pr-review`.
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
pipx install ai-pr-review
 pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"
pr-review --help
```
