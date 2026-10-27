@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "MAD_PYTHON=%~dp0runtime\python\pythonw.exe"
if not exist "%MAD_PYTHON%" set "MAD_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%MAD_PYTHON%" (
    echo MADAutoScript environment is missing. See README.md.
    pause
    exit /b 1
)
start "" "%MAD_PYTHON%" -E -s -X utf8 "%~dp0main.py"
exit /b 0
