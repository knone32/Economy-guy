@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0finance_agent" || goto missing
if /i "%~1"=="--live" goto live
if /i "%~1"=="--mock" goto mock

:menu
echo(
echo Economy-guy 财税工作台  v2.0.1
echo [1] 启动真实财税 Agent 工作台
echo [2] 运行离线 Mock 业务流程演示
echo [3] 安装或检查 Python 环境
echo [0] 退出
choice /c 1230 /n /m "请选择 1、2、3 或 0："
if errorlevel 255 goto failed
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
echo 建议将终端最大化至至少 137 列。模型和账簿请在工作台内选择。
"%DEMO_PY%" %DEMO_PY_ARGS% -X utf8 main.py
if errorlevel 1 goto run_failed
exit /b 0

:run_mock
call :check_environment || exit /b 1
echo 离线脚本模拟，不代表真实模型理解。API 请求为零。
"%DEMO_PY%" %DEMO_PY_ARGS% -X utf8 scripts\demo_stepper.py --mode mock --scenario all
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
echo Python 环境就绪。
goto menu

:install_failed
echo 安装失败。请检查上方错误、Python 3.11+、网络和解压目录写入权限，再选 3 重试。
pause
goto menu

:check_environment
set "DEMO_PY=.venv\Scripts\python.exe"
set "DEMO_PY_ARGS="
if exist "%DEMO_PY%" goto validate_python
call :find_system_python
if errorlevel 1 goto environment_failed
:validate_python
"%DEMO_PY%" %DEMO_PY_ARGS% -c "import sys; assert sys.version_info >= (3, 11); import openpyxl, openai, textual; assert textual.__version__ == '1.0.0'"
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
echo Python 或依赖尚未就绪。请安装 Python 3.11 或更新版本，再双击 START.bat 选择 3。
pause
exit /b 1

:run_failed
echo 运行中断或失败。请查看上方错误和已生成的本地报告。
pause
exit /b 1

:missing
echo 找不到 finance_agent。请完整解压比赛包后再启动。
pause
exit /b 1

:failed
popd
exit /b 1

:success
popd
exit /b 0

:finish
set "DEMO_EXIT=%ERRORLEVEL%"
popd
exit /b %DEMO_EXIT%
