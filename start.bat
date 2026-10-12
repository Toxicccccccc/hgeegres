@echo off
setlocal EnableExtensions
title Disabled AI — Launcher

rem Always run from the folder that holds this script, whatever the shortcut's
rem "Start in" happens to be, so the relative engine/, ui/ and config/ paths
rem resolve correctly.
cd /d "%~dp0"

echo ============================================
echo   Disabled AI - starting
echo ============================================
echo.

rem Prefer the project virtual environment. Fall back to a plain "python" on
rem PATH so the launcher still works on a machine that installed the deps
rem globally.
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] No Python interpreter found.
    echo         Install Python and the dependencies, or create .venv, then retry.
    echo.
    pause
    exit /b 1
)

echo Using interpreter: %PY%
echo.

"%PY%" "%~dp0run_app.py"
set "EXITCODE=%errorlevel%"

rem A non-zero exit means the app closed on an error; keep the window open so
rem the traceback stays readable instead of vanishing with the console.
if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] Disabled AI exited with code %EXITCODE%.
    echo Check the messages above for the reason.
    echo.
    pause
)

endlocal
exit /b %EXITCODE%
