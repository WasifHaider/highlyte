@echo off
setlocal

echo ============================================
echo  HighLyte setup - run this once
echo ============================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [1/6] Python not found - installing...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
) else (
    echo [1/6] Python found.
)

where node >nul 2>nul
if errorlevel 1 (
    echo [2/6] Node.js not found - installing...
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
) else (
    echo [2/6] Node.js found.
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [3/6] ffmpeg not found - installing...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
) else (
    echo [3/6] ffmpeg found.
)

echo.
echo A new terminal may have been needed for Python/Node/ffmpeg to be found.
echo If the next steps fail with "not recognized", close this window, open a
echo fresh one, and run setup.bat again.
echo.

echo [4/6] Setting up the backend (this can take a few minutes)...
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
    echo [5/6] No .env file found.
    echo        Ask whoever set up HighLyte for the .env file and put it in
    echo        this folder: %cd%
    echo        Then run setup.bat again.
    goto :done
) else (
    echo [5/6] .env found.
)

echo [6/6] Setting up the app window (this can take a few minutes)...
cd frontend
call npm install
if errorlevel 1 goto :error
cd ..

:done
echo.
echo ============================================
echo  Setup finished. Double-click start.bat to run HighLyte.
echo ============================================
pause
exit /b 0

:error
echo.
echo Something went wrong above. Scroll up to see the error, or ask for help.
pause
exit /b 1
