@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
.venv\Scripts\python app.py
pause
exit /b 0

:nosetup
echo Run setup.bat first.
pause
exit /b 1
