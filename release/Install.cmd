@echo off
setlocal EnableExtensions
set "HERE=%~dp0"
if exist "%HERE%bot\cli.py" (cd /d "%HERE%") else (cd /d "%HERE%..")
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

if not exist "data" mkdir "data" >nul 2>&1

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo.
        echo Created .env from .env.example
        echo Edit .env if your MuMu/LDPlayer path or ADB port is different.
    ) else (
        echo [WARN] .env.example not found - create .env manually.
    )
) else (
    echo .env already exists - left unchanged.
)

echo.
echo [OK] Install complete.
echo.
echo Next: open MuMu + Archero 2 on the lobby, then run Start-Panel.cmd
echo.
pause
