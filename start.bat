@echo off
echo Starting CBRIN — Semantic Search for Your Content...
echo.
echo [1/2] Starting Python FastAPI Backend Server on http://localhost:8000 ...
start "CBRIN Backend" cmd /k "cd backend && python main.py"
echo.
echo [2/2] Starting Vite Frontend App on http://localhost:3000 ...
start "CBRIN Frontend" cmd /k "npm run dev"
echo.
echo Done! Open http://localhost:3000 in your browser.
