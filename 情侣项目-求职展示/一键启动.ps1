﻿# ============================================================
#   情侣项目 一键启动脚本
#   作用：自动检查环境 -> 补装缺失依赖 -> 启动后端 -> 启动前端 -> 打开浏览器
#   用法：双击「一键启动.bat」即可
# ============================================================

$ErrorActionPreference = 'Continue'
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend  = Join-Path $root 'couple-backend'
$frontend = Join-Path $root 'couple-frontend'

$BACKEND_URL  = 'http://127.0.0.1:5000/api/health'
$FRONTEND_URL = 'http://127.0.0.1:5173/'

Write-Host ''
Write-Host '======== 情侣项目 一键启动 ========' -ForegroundColor Cyan

function Pause-Exit {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
    Read-Host '按回车键退出'
    exit 1
}

# ---------- 0. 基础环境检查 ----------
& cmd /c "python --version >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    Pause-Exit '[错误] 未找到 python，请先安装 Python 3.10+ 并加入 PATH'
}
& cmd /c "node --version >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    Pause-Exit '[错误] 未找到 node，请先安装 Node.js 并加入 PATH'
}

# ---------- 1. 检查并补装后端依赖（只装缺失的，装过则秒过） ----------
Write-Host '[1/4] 检查后端 Python 依赖...' -ForegroundColor Yellow

$depMap = [ordered]@{
    'flask'           = 'flask'
    'flask_cors'      = 'flask-cors'
    'flask_migrate'   = 'flask-migrate'
    'flask_sqlalchemy'= 'flask-sqlalchemy'
    'flask_jwt_extended' = 'flask-jwt-extended'
    'flask_socketio'  = 'flask-socketio'
    'gevent'          = 'gevent'
    'gevent_websocket'= 'gevent-websocket'
    'pytz'            = 'pytz'
    'pydub'           = 'pydub'
    'PIL'             = 'pillow'
}
$missing = @()
foreach ($mod in $depMap.Keys) {
    & cmd /c "python -c ""import $mod"" >nul 2>nul"
    if ($LASTEXITCODE -ne 0) { $missing += $depMap[$mod] }
}

if ($missing.Count -gt 0) {
    Write-Host ("      首次运行，正在安装缺失依赖: " + ($missing -join ', ')) -ForegroundColor Yellow
    & python -m pip install @missing --disable-pip-version-check -q
    if ($LASTEXITCODE -ne 0) {
        Pause-Exit '[错误] 依赖安装失败，请检查网络后重试'
    }
    Write-Host '      依赖安装完成' -ForegroundColor Green
} else {
    Write-Host '      后端依赖齐全' -ForegroundColor Green
}

# ---------- 2. 启动后端（已在本跑则跳过） ----------
Write-Host '[2/4] 启动后端服务 (端口 5000)...' -ForegroundColor Yellow

$backendRunning = $false
try {
    $null = Invoke-WebRequest -Uri $BACKEND_URL -UseBasicParsing -TimeoutSec 2
    $backendRunning = $true
    Write-Host '      检测到后端已在运行，直接复用' -ForegroundColor Green
} catch { }

if (-not $backendRunning) {
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', "title 情侣项目-后端 && cd /d `"$backend`" && python -m backend.app"
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-WebRequest -Uri $BACKEND_URL -UseBasicParsing -TimeoutSec 2
            $ok = $true; break
        } catch { }
    }
    if ($ok) { Write-Host '      后端启动成功' -ForegroundColor Green }
    else {
        Pause-Exit '[错误] 后端 60 秒内未就绪，请查看"情侣项目-后端"窗口里的报错信息'
    }
}

# ---------- 3. 检查前端依赖并启动前端 ----------
Write-Host '[3/4] 启动前端服务 (端口 5173)...' -ForegroundColor Yellow

if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host '      首次运行，正在安装前端依赖 (npm install, 使用淘宝镜像)...' -ForegroundColor Yellow
    Push-Location $frontend
    & cmd /c "npm install --registry=https://registry.npmmirror.com"
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Pause-Exit '[错误] 前端依赖安装失败，请检查网络后重试'
    }
}

$frontendRunning = $false
try {
    $null = Invoke-WebRequest -Uri $FRONTEND_URL -UseBasicParsing -TimeoutSec 2
    $frontendRunning = $true
    Write-Host '      检测到前端已在运行，直接复用' -ForegroundColor Green
} catch { }

if (-not $frontendRunning) {
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', "title 情侣项目-前端 && cd /d `"$frontend`" && npm run dev"
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-WebRequest -Uri $FRONTEND_URL -UseBasicParsing -TimeoutSec 2
            $ok = $true; break
        } catch { }
    }
    if (-not $ok) {
        Pause-Exit '[错误] 前端 60 秒内未就绪，请查看"情侣项目-前端"窗口里的报错信息'
    }
}
Write-Host '      前端启动成功' -ForegroundColor Green

# ---------- 4. 打开浏览器 ----------
Write-Host '[4/4] 打开浏览器...' -ForegroundColor Yellow
Start-Process $FRONTEND_URL

Write-Host ''
Write-Host '====================================' -ForegroundColor Cyan
Write-Host ' 启动完成！' -ForegroundColor Green
Write-Host '  · 网页地址:  http://127.0.0.1:5173/' -ForegroundColor White
Write-Host '  · 后端地址:  http://127.0.0.1:5000/' -ForegroundColor White
Write-Host '  · 停止方法:  关闭"情侣项目-后端"和"情侣项目-前端"两个黑色窗口即可' -ForegroundColor White
Write-Host '====================================' -ForegroundColor Cyan
Write-Host ''
Read-Host '按回车键关闭本窗口（前后端窗口会继续保留运行）'
