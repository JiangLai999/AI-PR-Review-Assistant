@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo ========================================
echo   AI PR Review Assistant - Install
echo ========================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3.12"
    %PYTHON_CMD% --version >nul 2>&1
    if errorlevel 1 set "PYTHON_CMD=py"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Error: Python was not found. Please install Python 3.12+
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

for /f "delims=" %%i in ('%PYTHON_CMD% -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%i"
echo Using Python: !PYTHON_EXE!

if not exist ".venv" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo Error: failed to create virtual environment.
        pause
        exit /b 1
    )
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PR_REVIEW=%~dp0.venv\Scripts\pr-review.exe"
set "VENV_SCRIPTS=%~dp0.venv\Scripts"

echo Upgrading pip...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Error: failed to upgrade pip.
    pause
    exit /b 1
)

echo Installing AI PR Review Assistant...
"%VENV_PYTHON%" -m pip install -e .
if errorlevel 1 (
    echo Error: failed to install project dependencies.
    pause
    exit /b 1
)

echo Configuring user PATH...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$scripts = [IO.Path]::GetFullPath('.venv\\Scripts'); $current = [Environment]::GetEnvironmentVariable('Path', 'User'); $parts = @(); if ($current) { $parts = $current -split ';' | Where-Object { $_ } }; if ($parts -notcontains $scripts) { [Environment]::SetEnvironmentVariable('Path', (($parts + $scripts) -join ';'), 'User'); Write-Host 'Added to user PATH:' $scripts } else { Write-Host 'User PATH already contains:' $scripts }"
if errorlevel 1 (
    echo Warning: failed to update PATH automatically. You can still use start.bat.
)

echo.
echo ========================================
echo   Installation completed
echo ========================================
echo.
echo Launch methods:
echo   1. Double-click start.bat
echo   2. Run start.ps1 in PowerShell
echo   3. Reopen terminal and run: pr-review config
echo   4. Or run directly: "%VENV_PR_REVIEW%" config
echo.
pause
