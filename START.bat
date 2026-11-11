@echo off
setlocal DisableDelayedExpansion

set "PYTHONUTF8=1"
set "LIVE_DB="
if /i "%~1"=="--live" if /i "%~2"=="--db" if "%~3"=="" (
    echo Missing workbook path. Usage: START.bat --live --db "path to workbook.sqlite3"
    exit /b 2
)
if /i "%~1"=="--live" if /i "%~2"=="--db" set "LIVE_DB=%~f3"
pushd "%~dp0finance_agent" || goto missing
if /i "%~1"=="--live" goto live
set "DEMO_RESET="
if /i "%~2"=="--reset" set "DEMO_RESET=--reset-mock-demo"
if /i "%~1"=="--mock" goto mock

:menu
echo(
echo Economy-guy Workbench  v2.0.2
echo [1] Start live workbench
echo [2] Start offline Textual demo
echo [3] Install or check Python dependencies
echo [0] Exit
choice /c 1230 /n /m "Select 1, 2, 3 or 0: "
if errorlevel 255 goto menu_failed
if errorlevel 4 goto success
if errorlevel 3 goto install
if errorlevel 2 goto menu_mock
if errorlevel 1 goto menu_live
goto success

:menu_live
call :run_live
goto menu

:menu_mock
call :run_mock
goto menu

:live
call :run_live
goto finish

:mock
call :run_mock
goto finish

:run_live
call :check_environment || exit /b 1
echo Workbench source: "%CD%"
if exist "..\.git" git -C ".." rev-parse HEAD 2>nul
if defined LIVE_DB echo Workbook: "%LIVE_DB%"
echo Use a terminal at least 137 columns wide for the two-pane layout.
if defined LIVE_DB (
    "%DEMO_PY%" %DEMO_PY_ARGS% -X utf8 main.py --db "%LIVE_DB%"
) else (
    "%DEMO_PY%" %DEMO_PY_ARGS% -X utf8 main.py
)
if errorlevel 1 goto run_failed
exit /b 0

:run_mock
call :check_environment || exit /b 1
echo OFFLINE DEMO - fixed examples, no API requests.
"%DEMO_PY%" %DEMO_PY_ARGS% -X utf8 main.py --mock-demo %DEMO_RESET%
if errorlevel 1 goto run_failed
exit /b 0

:install
if exist ".venv\Scripts\python.exe" goto install_dependencies
call :find_system_python
if errorlevel 1 goto install_failed
"%DEMO_PY%" %DEMO_PY_ARGS% -m venv ".venv"
if errorlevel 1 goto install_failed

:install_dependencies
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto install_failed
call :check_environment
if errorlevel 1 goto menu
echo Python environment ready.
goto menu

:install_failed
echo Installation failed. Check the error above, network access and write access.
pause
goto menu

:check_environment
set "DEMO_PY=.venv\Scripts\python.exe"
set "DEMO_PY_ARGS="
if exist "%DEMO_PY%" goto validate_python
call :find_system_python
if errorlevel 1 goto environment_failed
:validate_python
"%DEMO_PY%" %DEMO_PY_ARGS% -c "import sys; assert sys.version_info >= (3, 11); from importlib.metadata import version; import openpyxl, openai, textual; assert version('textual') == '1.0.0'"
if errorlevel 1 goto environment_failed
exit /b 0

:find_system_python
set "DEMO_PY=py.exe"
set "DEMO_PY_ARGS=-3"
"%DEMO_PY%" %DEMO_PY_ARGS% -c "import sys; assert sys.version_info >= (3, 11)" 2>nul
if not errorlevel 1 exit /b 0
set "DEMO_PY=python.exe"
set "DEMO_PY_ARGS="
"%DEMO_PY%" -c "import sys; assert sys.version_info >= (3, 11)"
exit /b %ERRORLEVEL%

:environment_failed
echo Python or dependencies unavailable. Install Python 3.11+ and select 3.
pause
exit /b 1

:run_failed
set "DEMO_EXIT=%ERRORLEVEL%"
echo The workbench exited with code %DEMO_EXIT%. See the output above.
pause
exit /b %DEMO_EXIT%

:missing
echo finance_agent is missing. Extract the entire ZIP before running START.bat.
pause
exit /b 1

:menu_failed
echo The menu could not read input. Run START.bat in an interactive Windows console.
pause
popd
exit /b 255

:success
popd
exit /b 0

:finish
set "DEMO_EXIT=%ERRORLEVEL%"
popd
exit /b %DEMO_EXIT%
