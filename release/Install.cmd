@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Arch Helper - Install

echo.
echo  Arch Helper - Install
echo  =====================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not on PATH.
    echo Install Python 3.12+ from https://www.python.org/downloads/
    echo Check "Add python.exe to PATH" in the installer.
    pause
    exit /b 1
)

python --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo Created .env from .env.example - check MuMu path if needed.
    )
)

echo.
echo [OK] Install complete.
echo.
echo Next: open MuMu + Archero 2 on the lobby, then run:
echo   release\Start-Panel.cmd
echo.
pause
