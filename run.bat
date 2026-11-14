@echo off
rem Double-click to start PDF Touch-up from the source code.
rem First run sets everything up (needs internet once); later runs just open the app.
cd /d "%~dp0"

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3 run.py %*
    goto done
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    python run.py %*
    goto done
)
echo Python is not installed.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click run.bat again.
pause
exit /b 1

:done
if errorlevel 1 pause
