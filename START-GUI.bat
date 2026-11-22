@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
cd /d "%~dp0finance_agent" || goto failed
set "GUI_PY=%ECONOMYGUY_PYTHON%"
set "GUI_PY_ARGS="
if defined GUI_PY (
  call :probe "%GUI_PY%" ""
  if errorlevel 1 goto failed
  goto run
)
call :probe "%CD%\.venv\Scripts\python.exe" ""
if not errorlevel 1 goto run
call :probe "%CD%\..\.venv\Scripts\python.exe" ""
if not errorlevel 1 goto run
call :probe "py" "-3"
if not errorlevel 1 goto run
call :probe "python" ""
if not errorlevel 1 goto run
echo No usable Python 3.11+ environment with the required dependencies was found.
goto failed
:probe
set "GUI_PY=%~1"
set "GUI_PY_ARGS=%~2"
"%GUI_PY%" %GUI_PY_ARGS% -c "import sys; assert sys.version_info >= (3,11); import openai,openpyxl,textual,pypdf; from importlib.metadata import version; assert version('textual') == '1.0.0'; assert version('openai').split('.')[0] == '1'; assert (3,1) <= tuple(map(int,version('openpyxl').split('.')[:2])) < (4,0); assert version('pypdf').split('.')[0] == '6'" >nul 2>nul
exit /b %errorlevel%
:run
"%GUI_PY%" %GUI_PY_ARGS% -X utf8 run_gui.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo(
echo GUI not started. Read the message above; no model fallback was selected.
echo Python 3.11+ required. From this finance_agent directory: python -m pip install -r requirements.txt
echo See START-HERE.md for the existing Profile and local trusted binding setup.
pause
exit /b 2
