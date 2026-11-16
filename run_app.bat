@echo off
title Invoice Agent - launcher
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Python was not found on PATH. Install Python 3.10+ and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [FAIL] Could not create the virtual environment.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"

python -c "import streamlit, psycopg2, google.genai, dotenv" >nul 2>nul
if errorlevel 1 (
    echo Installing packages from requirements.txt - this can take a few minutes ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [FAIL] Package install failed. See the messages above.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    echo.
    echo [WARN] No .env file in this folder. The app needs GEMINI_API_KEY and the
    echo        PostgreSQL settings DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT.
)

echo.
echo ===== Preflight check =====
python check_setup.py
echo.
echo ===== Starting the app at http://localhost:8501 =====
echo Close this window to stop the app.
python -m streamlit run app.py
pause
