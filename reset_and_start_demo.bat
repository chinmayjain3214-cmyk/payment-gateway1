@echo off
title Invoice Agent - demo
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [FAIL] The .venv folder is missing. Run run_app.bat once first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

echo Stopping any copy of the app already running on port 8501 ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8501 .*LISTENING"') do taskkill /PID %%p /F >nul 2>nul
timeout /t 2 /nobreak >nul

python reset_demo_data.py
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo ===== Starting the app at http://localhost:8501 =====
echo Close this window to stop the app.
python -m streamlit run app.py
pause
