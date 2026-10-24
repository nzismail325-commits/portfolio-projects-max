@echo off
setlocal EnableExtensions
rem ===========================================================
rem  WorkBuddy 网关（wb-proxy-max） - 统一启动脚本
rem
rem  与原二开项目同款，仅去掉 OC 上游代理设置（本版本无 oc 免登上游）。
rem
rem  双击运行弹出菜单选择启动方式：
rem    1 = 带终端窗口（日志显示在屏幕上，关窗口即停）
rem    2 = 后台无窗口（日志写入 usage\wb-proxy.log）
rem
rem  也保留命令行快捷方式（给脚本/快捷方式调用）：
rem    启动.bat hidden [端口]   -> 直接后台无窗口
rem    启动.bat h [端口]        -> 同 hidden
rem    启动.bat [端口]          -> 直接带终端
rem
rem  LAN 模式（局域网其他设备可访问）由下面的 LAN_MODE 变量控制：
rem    1 = 局域网开放（默认）   0 = 仅本机
rem
rem  停止：运行 停止.bat（或直接关掉终端窗口）。
rem  查看后台模式日志：usage\wb-proxy.log
rem
rem  注意：本文件必须以 GBK（ANSI 936）编码保存，cmd 按 936 代码页
rem  解析，存成 UTF-8 中文会乱码；if( ... ) 块内不要读 %VAR%，用 goto。
rem ===========================================================

set "MODE=%~1"
set "PORT=%~2"
set "KEY=%~3"
if "%PORT%"=="" set "PORT=8788"

rem ---- LAN 模式：1 = 监听全部网卡（局域网可用），0 = 仅本机
set "LAN_MODE=1"

set "EXTRA="
if "%LAN_MODE%"=="1" set "EXTRA=--lan"

set "HERE=%~dp0"
set "SCRIPT=%HERE%wb_proxy.py"
set "LOGFILE=%HERE%usage\wb-proxy.log"

rem ---- 命令行快捷入口：带参数时跳过菜单（给脚本/快捷方式用）----
if /i "%MODE%"=="hidden" goto mode_hidden
if /i "%MODE%"=="h" goto mode_hidden
if "%MODE%"=="" goto show_menu
rem 第一个参数不是 hidden/h 时，按旧习惯当作端口号（终端模式）
set "PORT=%~1"
goto mode_console

:show_menu
echo ===========================================================
echo   WorkBuddy 网关 - 启动方式
echo.
echo   端口 %PORT%   （改端口：编辑本文件顶部的 PORT，或命令行传入）
echo.
echo   [1] 带终端窗口启动 —— 日志实时显示，关窗口即停止
echo   [2] 后台无窗口启动 —— 日志写入文件，适合常驻
echo   [0] 退出
echo.
set "CHOICE="
set /p "CHOICE=请输入编号后回车 [1/2/0]: "
if "%CHOICE%"=="1" goto mode_console
if "%CHOICE%"=="2" goto mode_hidden
if "%CHOICE%"=="0" exit /b 0
rem 直接回车/输入为空：回到菜单重问，不当成错误
if "%CHOICE%"=="" goto show_menu
echo.
echo   无效输入：%CHOICE% （请输入 1、2 或 0）
echo.
pause
goto show_menu

:mode_hidden
rem ================= 无窗口：日志写文件 =================
if not exist "%SCRIPT%" goto no_script
if not exist "%HERE%usage" mkdir "%HERE%usage"

set "PYW="
call :resolve_python
if not defined PYEXE goto no_python
call :resolve_pyw
if not defined PYW goto no_python

rem ---- 防重复启动：服务自己也会拒绝第二份 ----
call :probe_port
if not errorlevel 1 goto already_running

rem ---- 后台拉起，无窗口 ----
powershell -NoProfile -Command "Start-Process -FilePath '%PYW%' -WorkingDirectory '%HERE%' -WindowStyle Hidden -ArgumentList @('\"%SCRIPT%\"','--port','%PORT%',\"%EXTRA%\",'--quiet')"
rem pythonw / 隐藏窗口立即返回，轮询等健康检查通过
call :wait_up 20
if errorlevel 1 goto start_failed

echo ===========================================================
echo   WorkBuddy 网关已在后台启动
echo.
echo   端口     : %PORT%
echo   日志文件 : %LOGFILE%
echo.
echo   代理运行期间不显示任何窗口，本启动器可以关闭。
echo.
echo   停止服务 : 停止.bat
echo   查看日志 : type %LOGFILE% （或用任意日志工具）
echo ===========================================================
echo.
pause
exit /b 0

:already_running
echo ===========================================================
echo   端口 %PORT% 上已经有代理在运行。
echo.
echo   看板地址 : http://127.0.0.1:%PORT%/
echo   日志文件 : %LOGFILE%
echo.
echo   本次没有启动任何东西。要重启请先运行 停止.bat。
echo ===========================================================
echo.
pause
exit /b 0

:start_failed
echo ===========================================================
echo   [出错] 代理在 20 秒内没有启动成功。
echo.
echo   请查看日志文件找原因：
echo     %LOGFILE%
echo.
echo   常见原因：
echo     - 端口 %PORT% 被其他程序占用
echo     - Python 启动失败（可先用菜单选 [1] 带终端启动，在窗口里看报错）
echo ===========================================================
echo.
pause
exit /b 1

:mode_console
rem ================= 终端窗口：日志上屏 =================
if not exist "%SCRIPT%" goto no_script

set "PYEXE="
call :resolve_python
if not defined PYEXE goto no_python

echo ===========================================================
echo   WorkBuddy 网关
echo.
echo   接口地址 : http://127.0.0.1:%PORT%/v1
echo   看板地址 : http://127.0.0.1:%PORT%/
echo.
echo   Python   : %PYEXE%
if "%LAN_MODE%"=="1" echo   运行模式 : 局域网开放（端口 %PORT%，调用 /v1 需要密钥）
echo.
echo   请保持本窗口开启，关掉窗口服务即停止。
echo   按 Ctrl+C 也可停止。
echo ===========================================================
echo.

"%PYEXE%" "%SCRIPT%" --port %PORT% %EXTRA%

echo.
echo [服务已退出]
pause
exit /b 0

rem -----------------------------------------------------------
rem  辅助过程
rem -----------------------------------------------------------

:resolve_python
rem ---- 1) 绿色包自带的运行时 ----
if not exist "%HERE%python\python.exe" goto rp_try_path
"%HERE%python\python.exe" --version >nul 2>nul
if errorlevel 1 goto rp_try_path
set "PYEXE=%HERE%python\python.exe"
goto :eof

:rp_try_path
rem ---- 2) PATH 上的 python ----
python --version >nul 2>nul
if errorlevel 1 goto rp_try_py
set "PYEXE=python"
goto :eof

:rp_try_py
rem ---- 3) py 启动器 ----
py --version >nul 2>nul
if errorlevel 1 goto rp_try_codex
set "PYEXE=py"
goto :eof

:rp_try_codex
rem ---- 4) Codex 自带的运行时 ----
call :find_codex
goto :eof

:find_codex
if not exist "%USERPROFILE%\.cache\codex-runtimes" goto :eof
for /d %%D in ("%USERPROFILE%\.cache\codex-runtimes\*") do call :probe "%%~D"
goto :eof

:probe
if defined PYEXE goto :eof
for /f "delims=" %%P in ('dir /b /s "%~1\python.exe" 2^>nul') do call :probe_one "%%~P"
goto :eof

:probe_one
if defined PYEXE goto :eof
"%~1" --version >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof

:resolve_pyw
rem ---- 优先用解释器旁边的 pythonw（完全无控制台）----
if exist "%HERE%python\pythonw.exe" goto use_bundled_pyw
for %%P in ("%PYEXE%") do set "PYDIR=%%~dpP"
if exist "%PYDIR%pythonw.exe" goto use_local_pyw
set "PYW=%PYEXE%"
goto :eof

:use_bundled_pyw
set "PYW=%HERE%python\pythonw.exe"
goto :eof

:use_local_pyw
set "PYW=%PYDIR%pythonw.exe"
goto :eof

:probe_port
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ('http://127.0.0.1:' + '%PORT%' + '/health'); if ($r.StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>nul
goto :eof

:wait_up
rem %1 = 等待秒数
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(%1); do { try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ('http://127.0.0.1:' + '%PORT%' + '/health'); if ($r.StatusCode -eq 200) { exit 0 } } catch { }; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1" >nul 2>nul
goto :eof

:no_python
echo [出错] 没有找到可用的 Python。
echo.
echo 解决办法：
echo   1. 使用打包好的绿色版（已自带 python\ 目录）
echo   2. 安装 Python 3.9 以上版本
echo      （安装时勾选 Add python.exe to PATH）
echo   3. 或在本文件开头手动指定完整路径，例如：
echo        set "PYEXE=C:\Python312\python.exe"
echo.
pause
exit /b 1

:no_script
echo [出错] 在脚本旁边找不到 wb_proxy.py。
echo         应在位置：%SCRIPT%
echo.
pause
exit /b 1
