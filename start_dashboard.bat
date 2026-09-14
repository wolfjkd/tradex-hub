@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  tradex-hub Dashboard Launcher  (v3.3.13)
REM
REM  Usage:
REM     start_dashboard.bat              default port 8765
REM     start_dashboard.bat 9000         custom port
REM     start_dashboard.bat --check      probe interpreter + dep versions only
REM
REM  v3.3.13 fixes (both caused this script to be unusable):
REM   1) Interpreter probe. The old script ran `where python` and took the
REM      first hit -- on this machine that is a bare interpreter
REM      (binaries\python\versions\3.13.12) WITHOUT the tradex package,
REM      so it always died with: No module named 'tradex'.
REM      We now walk candidates and require the FULL dashboard import set
REM      (`tradex.dashboard, eltdx, akshare`) to load. Probing bare
REM      `import tradex` is not enough: with cwd=tradex-hub, Python treats
REM      the local `tradex\` folder as a namespace package and the import
REM      succeeds even in an empty venv.
REM   2) Port was only used for the printed URL and never handed to the
REM      dashboard, which reads TRADEX_DASHBOARD_PORT. A custom port
REM      therefore served on 8765 while the browser opened the wrong URL.
REM      The port is now exported as TRADEX_DASHBOARD_PORT.
REM ============================================================

cd /d "%~dp0"

set "CHECKONLY="
set "PORT=8765"
if /i "%~1"=="--check" set "CHECKONLY=1"
if not defined CHECKONLY if not "%~1"=="" set "PORT=%~1"
set "TRADEX_DASHBOARD_PORT=%PORT%"

REM ---------- locate a python that can actually import tradex ----------
set "PYEXE="

REM candidate 1: project-local .venv
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import tradex.dashboard,eltdx,akshare" >nul 2>&1
    if not errorlevel 1 set "PYEXE=%~dp0.venv\Scripts\python.exe"
)

REM candidate 2: WorkBuddy managed env (the one the MCP server uses)
if not defined PYEXE (
    set "CAND=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    if exist "!CAND!" (
        "!CAND!" -c "import tradex.dashboard,eltdx,akshare" >nul 2>&1
        if not errorlevel 1 set "PYEXE=!CAND!"
    )
)

REM candidate 3: every python on PATH, in order
if not defined PYEXE (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        if not defined PYEXE (
            "%%I" -c "import tradex.dashboard,eltdx,akshare" >nul 2>&1
            if not errorlevel 1 set "PYEXE=%%I"
        )
    )
)

if not defined PYEXE (
    echo.
    echo [ERROR] No Python interpreter with "tradex" installed was found.
    echo.
    echo   Tried, in order:
    echo     1^) "%~dp0.venv\Scripts\python.exe"
    echo     2^) "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    echo     3^) every "python" on PATH
    echo.
    echo   Fix - install the package into one of them, for example:
    echo     "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m pip install -e tradex
    echo.
    pause
    exit /b 1
)

if defined CHECKONLY (
    echo ============================================================
    echo   tradex dependency check
    echo ============================================================
    echo   Python : %PYEXE%
    "%PYEXE%" -c "import tradex,eltdx,akshare; print('  tradex :', tradex.__version__); print('  eltdx  :', getattr(eltdx,'__version__','?')); print('  akshare:', getattr(akshare,'__version__','?'))"
    echo.
    echo   Run without --check and open the dashboard for update info.
    echo.
    pause
    exit /b 0
)

echo ============================================================
echo   tradex Dashboard
echo   Python : %PYEXE%
echo   Port   : %PORT%
echo   URL    : http://127.0.0.1:%PORT%/
echo ============================================================
echo.
echo Starting... browser will open in 5s
echo Press Ctrl+C to stop
echo.

start "" /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:%PORT%/"

"%PYEXE%" -m tradex.dashboard
if errorlevel 1 (
    echo.
    echo [ERROR] dashboard failed to start
    pause
)
