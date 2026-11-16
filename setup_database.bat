@echo off
title Invoice Agent - database setup
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [FAIL] The .venv folder is missing. Run run_app.bat once first, then run this again.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python setup_local_db.py
echo.
pause
