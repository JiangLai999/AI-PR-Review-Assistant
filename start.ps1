$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Green
Write-Host "  AI PR Review Assistant - Start" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

$venvCommand = Join-Path $PSScriptRoot ".venv\Scripts\pr-review.exe"

if (-not (Test-Path $venvCommand)) {
    Write-Host "Project is not installed yet. Running installer..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "install.ps1")
}

if (-not (Test-Path $venvCommand)) {
    throw "pr-review is still unavailable after installation."
}

if ($args.Count -eq 0) {
    & $venvCommand config
    exit $LASTEXITCODE
}

& $venvCommand @args
exit $LASTEXITCODE
