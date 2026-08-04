@echo off
echo Starting CBRIN — Semantic Search for Your Content...
echo.

REM Bare "python" resolves to the Windows Store App Execution Alias on machines where it's
REM enabled, NOT the project's .venv — silently running a different interpreter with none of
REM backend/requirements.txt installed (verified live on this box: it has just enough
REM pre-existing packages to boot the app, making the mismatch easy to miss). Call the venv's
REM python.exe by its full path so this can't happen regardless of what's on PATH.
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo ERROR: Virtual environment not found at "%VENV_PYTHON%".
    echo Create it first: python -m venv .venv ^&^& .venv\Scripts\pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo [1/2] Starting Python FastAPI Backend Server on http://localhost:8000 ...
start "CBRIN Backend" cmd /k "cd backend && "%VENV_PYTHON%" main.py"
echo.
echo [2/2] Starting Vite Frontend App on http://localhost:3000 ...
start "CBRIN Frontend" cmd /k "npm run dev"
echo.
echo Done! Open http://localhost:3000 in your browser.
