@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "HERE=%~dp0"
if exist "%HERE%bot\cli.py" (cd /d "%HERE%") else (cd /d "%HERE%..")
title Arch Helper - Bot

if not exist ".venv\Scripts\python.exe" (
    echo Run install first: Install.cmd
    pause
    exit /b 1
)

if exist "STOP" del /F /Q "STOP" >nul 2>&1

echo.
echo  Arch Helper - Run bot
echo  ====================
echo.
echo Presets: data\presets.json
echo Recovery state: data\run-state.json
echo.
echo Examples:
echo   Run-Bot.cmd 5-arena-farm
echo   Run-Bot.cmd arena:5 farm:forever
echo   Run-Bot.cmd --resume
echo   Run-Bot.cmd --list
echo.

if "%~1"=="" (
    ".venv\Scripts\python.exe" -m bot.cli run --list
    echo.
    set /p PRESET="Preset or steps (Enter = 5-arena-farm): "
    if "!PRESET!"=="" set PRESET=5-arena-farm
    ".venv\Scripts\python.exe" -m bot.cli run !PRESET!
) else (
    ".venv\Scripts\python.exe" -m bot.cli run %*
)

echo.
pause
