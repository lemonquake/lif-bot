@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===================================================
echo Love in Faith Bot - Startup Script
echo ===================================================
echo [INFO] Project folder: %CD%
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.10 or newer.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created successfully.
)

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo [WARN] Existing virtual environment is broken. Recreating it...
        rmdir /s /q venv
        python -m venv venv
        if !errorlevel! neq 0 (
            echo [ERROR] Failed to recreate virtual environment.
            pause
            exit /b 1
        )
    )
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Install requirements
echo [INFO] Installing/updating dependencies...
pip install -r requirements.txt --upgrade
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Ensure data directory exists
if not exist "data\" (
    mkdir data
)

if exist ".env" (
    echo [INFO] Found .env file in project folder.
) else (
    echo [WARN] No .env file found in project folder.
)

if "%DISCORD_TOKEN%"=="" if not exist ".env" (
    echo [ERROR] DISCORD_TOKEN is not set.
    echo Set it before starting the bot, for example:
    echo set DISCORD_TOKEN=your_bot_token_here
    echo Or create a .env file in this folder with DISCORD_TOKEN=your_bot_token_here
    pause
    exit /b 1
)

:: Start the bot
echo.
echo [INFO] Starting Love in Faith Bot...
echo ===================================================
python bot.py
if %errorlevel% neq 0 (
    echo [ERROR] Bot exited with an error.
    pause
    exit /b 1
)

pause
