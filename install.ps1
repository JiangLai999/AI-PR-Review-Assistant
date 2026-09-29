$ErrorActionPreference = "Stop"

$PackageName = "ai-pr-review"
$InstallSource = if ($env:INSTALL_SOURCE) { $env:INSTALL_SOURCE } else { "github" }
$GithubRepository = if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { "JiangLai999/AI-PR-Review-Assistant" }

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

function Test-PythonCommand {
    # 逐个候选探测：`py -3.12` 在只装了 3.13 的机器上会以非 0 退出码打印
    # "No suitable Python runtime found"，而 Windows PowerShell 5.1 不会因为
    # 原生命令失败而抛异常 —— 所以必须**读输出 + 校验版本**，不能靠 try/catch。
    param([string[]]$Command)
    $versionText = (Invoke-PythonCommand $Command --version 2>&1 | Out-String).Trim()
    if ($versionText -notmatch 'Python\s+(\d+)\.(\d+)') {
        return $false
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    return ($major -eq 3 -and $minor -ge 12)
}

function Get-PythonCommand {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3.12")
        $candidates += ,@("py", "-3.13")
        $candidates += ,@("py", "-3")
        $candidates += ,@("py")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += ,@("python")
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $candidates += ,@("python3")
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand $candidate) {
            return $candidate
        }
    }

    throw "Python 3.12+ was not found. Please install Python first."
}

function Ensure-Pipx {
    if (Get-Command pipx -ErrorAction SilentlyContinue) {
        return
    }

    $pythonCmd = Get-PythonCommand
    Write-Host "pipx not found, installing with Python..." -ForegroundColor Yellow
    Invoke-PythonCommand $pythonCmd -m pip install --user --upgrade pipx
    if ($LASTEXITCODE -ne 0) {
        throw "pipx installation failed with exit code $LASTEXITCODE."
    }

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

$pythonCmd = Get-PythonCommand
Write-Host "Python: $((Invoke-PythonCommand $pythonCmd --version 2>&1 | Out-String).Trim())" -ForegroundColor DarkGray
Ensure-Pipx
$packageSpec = Get-PackageSpec

Write-Host "Installing package with pipx..." -ForegroundColor Yellow
pipx install --force $packageSpec

# Windows PowerShell 5.1 不会因为原生命令非 0 退出而抛异常，必须显式检查，
# 否则安装失败也会打印 "Installation completed"（2026-09-29 实测踩到）。
if ($LASTEXITCODE -ne 0) {
    # pipx 默认优先用 uv；uv 对 git fetch 的超时更短，网络抖动时会直接失败。
    # 这里回落一次 pip 后端，仍失败才报错（2026-09-29 实测 uv 失败、pip 成功）。
    Write-Host "pipx install failed (exit $LASTEXITCODE); retrying with the pip backend..." -ForegroundColor Yellow
    pipx install --force --backend pip $packageSpec
}
if ($LASTEXITCODE -ne 0) {
    throw "pipx install failed with exit code $LASTEXITCODE. See the pipx log under `$env:PIPX_HOME\logs for details."
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation completed" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Run: pr-review --help" -ForegroundColor White
Write-Host "Then configure: pr-review config" -ForegroundColor White
