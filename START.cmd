@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
