@echo off
:: Double-click this file to start the AgriGrant dashboard.

cd /d "%~dp0"

echo Stopping any existing server on port 7654...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":7654 "') do taskkill /f /pid %%a 2>nul

echo Starting AgriGrant backend...
start /b python server.py

echo Waiting for server to start...
:wait
ping -n 2 127.0.0.1 >nul
curl -s http://localhost:7654/api/dashboard >nul 2>&1
if errorlevel 1 goto wait

echo Opening browser...
start http://localhost:7654

echo.
echo AgriGrant is running at http://localhost:7654
echo Admin panel:  http://localhost:7654/admin.html
echo.
echo Close this window to stop the server.
pause
