@echo off
setlocal
call "%~dp0..\..\INSTALL.cmd" %*
exit /b %errorlevel%
