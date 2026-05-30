@echo off
setlocal EnableExtensions

echo ========================================
echo   AI PR Review Assistant - Start
echo ========================================
echo.

set "ROOT=%~dp0"
set "VENV_PR_REVIEW=%ROOT%.venv\Scripts\pr-review.exe"
set "VENV_PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%VENV_PR_REVIEW%" (
    echo Project is not installed yet. Running installer...
    call "%ROOT%install.bat"
    if errorlevel 1 exit /b 1
)

if not exist "%VENV_PR_REVIEW%" (
    echo Error: pr-review is still unavailable after installation.
    pause
    exit /b 1
)

if "%~1"=="" (
    "%VENV_PR_REVIEW%" config
    exit /b %errorlevel%
)

"%VENV_PR_REVIEW%" %*
exit /b %errorlevel%
