@echo off
REM ============================================
REM tradex-hub Dashboard Launcher
REM Usage: double-click or start_dashboard.bat [port]
REM Default port: 8765
REM ============================================

cd /d "%~dp0"

set PORT=8765
if not "%~1"=="" set PORT=%~1

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found in PATH
    pause
    exit /b 1
)

echo ============================================
echo   tradex Dashboard
echo   Port: %PORT%
echo   URL:  http://127.0.0.1:%PORT%/
echo ============================================
echo.
echo Starting... browser will open in 5s
echo Press Ctrl+C to stop
echo.

start "" /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:%PORT%/"

python -m tradex.dashboard
if errorlevel 1 (
    echo.
    echo [ERROR] dashboard failed to start
    pause
)
