@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
cd /d "%~dp0finance_agent" || goto failed
set "GUI_PY=%ECONOMYGUY_PYTHON%"
set "GUI_PY_ARGS="
if defined GUI_PY goto run
if exist ".venv\Scripts\python.exe" set "GUI_PY=%CD%\.venv\Scripts\python.exe"
if defined GUI_PY goto run
if exist "..\.venv\Scripts\python.exe" set "GUI_PY=%CD%\..\.venv\Scripts\python.exe"
if defined GUI_PY goto run
where py >nul 2>nul
if not errorlevel 1 (
  set "GUI_PY=py"
  set "GUI_PY_ARGS=-3"
) else (
  set "GUI_PY=python"
)
:run
"%GUI_PY%" %GUI_PY_ARGS% -c "import sys; assert sys.version_info >= (3,11)"
if errorlevel 1 goto failed
"%GUI_PY%" %GUI_PY_ARGS% -X utf8 run_gui.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo(
echo GUI not started. Read the message above; no model fallback was selected.
echo Python 3.11+ required. Install: python -m pip install -r finance_agent\requirements.txt
echo See START-HERE.md for the existing Profile and local trusted binding setup.
pause
exit /b 2
