@echo off
setlocal EnableExtensions
rem ===========================================================
rem  WorkBuddy 网关（wb-proxy-max） - 统一停止脚本
rem
rem  与原二开项目同款：结束所有在跑 wb_proxy.py 的 python/pythonw
rem  进程，两种启动方式都管：
rem    - 后台无窗口副本（启动.bat hidden 拉起的）
rem    - 终端窗口副本（直接关那个窗口也可以停）
rem  手动敲 python wb_proxy.py 起的进程同样能停（按脚本名匹配，
rem  不看目录，怎么启动的都能停）。
rem
rem  先尝试优雅关闭（WM_CLOSE），不行就强制结束：部分启动形态下
rem  服务主循环不理会关闭信号，强杀是可靠的兜底。
rem
rem  用法：停止.bat [端口]  （端口只用于探活确认）
rem
rem  注意：本文件必须以 GBK（ANSI 936）编码保存。
rem ===========================================================

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8788"

rem ---- 先探一下：是不是真的有服务在跑 ----
call :probe_port
if errorlevel 1 goto not_running

echo 正在停止 WorkBuddy 网关（端口 %PORT%）...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process -Filter \"Name like 'python%%.exe'\" | Where-Object { $_.CommandLine -match 'wb_proxy\.py' };" ^
  "if (-not $procs) { exit 1 };" ^
  "foreach ($p in $procs) {" ^
  "  try { (Get-Process -Id $p.ProcessId).CloseMainWindow() | Out-Null } catch { };" ^
  "  $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" ^
  "}" ^
  "exit 0"

rem ---- 等端口真正释放 ----
call :wait_down 8
if errorlevel 1 goto still_running

echo 已停止 - 网关已结束，端口 %PORT% 已释放。
echo.
pause
exit /b 0

:still_running
echo [警告] 8 秒后端口 %PORT% 上仍有进程应答。
echo        可能是别的程序占着这个端口，也可能结束被拦。
echo        排查命令：
echo          netstat -ano ^| findstr :%PORT%
echo.
pause
exit /b 1

:not_running
echo 没有需要停止的服务 - 端口 %PORT% 上没有网关在运行。
echo （如果服务起在其他端口，请带端口运行：停止.bat ^<端口^>）
echo.
pause
exit /b 0

:probe_port
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ('http://127.0.0.1:' + '%PORT%' + '/health'); if ($r.StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>nul
goto :eof

:wait_down
rem %1 = 等待秒数
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(%1); do { try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 ('http://127.0.0.1:' + '%PORT%' + '/health'); if ($r.StatusCode -eq 200) { exit 1 } } catch { exit 0 }; Start-Sleep -Milliseconds 300 } while ((Get-Date) -lt $deadline); exit 0" >nul 2>nul
goto :eof
