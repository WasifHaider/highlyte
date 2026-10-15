@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo Setup hasn't been run yet. Double-click setup.bat first.
    pause
    exit /b 1
)
if not exist ".env" (
    echo No .env file found. Put the one you were given in this folder:
    echo %cd%
    pause
    exit /b 1
)

echo Starting HighLyte...
start "HighLyte backend" cmd /k ".venv\Scripts\python -m uvicorn backend.main:app --port 8000"
cd frontend
start "HighLyte app" cmd /k "npm run dev"
cd ..

echo Waiting for the app to start...
timeout /t 6 /nobreak >nul
start http://localhost:6100

echo.
echo HighLyte is running in the two new windows that opened.
echo Leave them open while you use the app. Close them to stop HighLyte.
pause
