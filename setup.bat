@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 goto nopython

echo [1/2] Creating virtual environment .venv ...
python -m venv .venv
if errorlevel 1 goto fail

echo [2/2] Installing dependencies ...
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo Done. Now run run.bat
pause
exit /b 0

:nopython
echo Python not found. Install it from https://www.python.org/downloads/
echo During install check "Add python.exe to PATH", then run setup.bat again.
pause
exit /b 1

:fail
echo Setup failed, see messages above.
pause
exit /b 1
