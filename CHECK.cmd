@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py --check --cpu-budget 2 --cpu-per-job 1 --workers 2
set "result=%errorlevel%"
pause
exit /b %result%
