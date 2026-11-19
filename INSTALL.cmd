@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.12 x64 with the Python launcher first.
  pause
  exit /b 1
)
if "%~1"=="" (
  py -3.12 scripts\install.py --interactive
) else (
  py -3.12 scripts\install.py %*
)
set "result=%errorlevel%"
if not "%result%"=="0" (
  echo Installation stopped. Read the message above before trying again.
) else (
  echo Ready. Run CHECK.cmd, then START.cmd.
)
pause
exit /b %result%
