@echo off
call "%~dp0START.bat" --mock %1
exit /b %ERRORLEVEL%
