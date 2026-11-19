@echo off
setlocal
call "%~dp0..\..\CHECK.cmd" %*
exit /b %errorlevel%
