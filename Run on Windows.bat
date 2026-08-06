@echo off
REM Double-click launcher for Windows.
REM First run sets things up (a minute or two). After that it opens straight away.

cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo.
        echo Python is not installed, or it was installed without "Add Python to PATH".
        echo.
        echo Install it from https://www.python.org/downloads/
        echo On the first installer screen, TICK "Add Python to PATH", then run this again.
        echo.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time. This takes a minute...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the environment. The message above says why.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Could not install the requirements. The message above says why.
        pause
        exit /b 1
    )
    echo Setup complete.
)

start "" ".venv\Scripts\pythonw.exe" run.py

REM If the window does not appear, run this file from a Command Prompt to see the error.
