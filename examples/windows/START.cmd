@echo off
setlocal
call "%~dp0..\..\START.cmd" %*
exit /b %errorlevel%
