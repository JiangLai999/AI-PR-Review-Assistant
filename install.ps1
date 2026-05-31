$ErrorActionPreference = "Stop"

$PackageName = "ai-pr-review"
$InstallSource = if ($env:INSTALL_SOURCE) { $env:INSTALL_SOURCE } else { "pypi" }
$GithubRepository = if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { "JiangLai999/AI-PR-Review-Assistant" }

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3.12 --version *> $null
            return @("py", "-3.12")
        }
        catch {
            return @("py")
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }

    throw "Python 3.12+ was not found. Please install Python first."
}

function Invoke-PythonCommand {
    param(
        [string[]]$Command,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    if ($Command.Length -gt 1) {
        & $Command[0] $Command[1..($Command.Length - 1)] @Arguments
        return
    }

    & $Command[0] @Arguments
}

function Ensure-Pipx {
    if (Get-Command pipx -ErrorAction SilentlyContinue) {
        return
    }

    $pythonCmd = Get-PythonCommand
    Write-Host "pipx not found, installing with Python..." -ForegroundColor Yellow
    Invoke-PythonCommand $pythonCmd -m pip install --user --upgrade pipx

    $userBase = (Invoke-PythonCommand $pythonCmd -m site --user-base).Trim()
    $pipxPath = Join-Path $userBase "Scripts"

    if ($env:Path -notlike "*$pipxPath*") {
        $env:Path = "$pipxPath;$env:Path"
    }

    try {
        Invoke-PythonCommand $pythonCmd -m pipx ensurepath *> $null
    }
    catch {
    }

    if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
        throw "pipx installation succeeded but is not on PATH yet. Reopen PowerShell and retry."
    }
}

function Get-PackageSpec {
    switch ($InstallSource) {
        "pypi" {
            return $PackageName
        }
        "github" {
            return "git+https://github.com/$GithubRepository.git"
        }
        default {
            throw "Unsupported INSTALL_SOURCE '$InstallSource'. Use 'pypi' or 'github'."
        }
    }
}

Write-Host "========================================" -ForegroundColor Green
Write-Host "  AI PR Review Assistant - Install" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Source: $InstallSource" -ForegroundColor Cyan
if ($InstallSource -eq "github") {
    Write-Host "Repository: $GithubRepository" -ForegroundColor Cyan
}

Ensure-Pipx
$packageSpec = Get-PackageSpec

Write-Host "Installing package with pipx..." -ForegroundColor Yellow
pipx install --force $packageSpec

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation completed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Run: pr-review --help" -ForegroundColor White
Write-Host "Then configure: pr-review config" -ForegroundColor White
