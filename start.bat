@echo off
REM =================================================================
REM  start.bat - 手动启动 NDX 打分系统（不依赖自启）
REM =================================================================
REM  - 启动 watchdog.py（断线自动重启 serve.py）
REM  - 2 秒后在默认浏览器打开页面
REM =================================================================

setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYW_EXE=%CD%\python\pythonw.exe"

if not exist "%PYW_EXE%" (
    echo [错误] 找不到 %PYW_EXE%
    echo 请先运行 setup.bat 完成安装。
    pause
    exit /b 1
)

echo 启动 watchdog ...
start "" "%PYW_EXE%" "%CD%\watchdog.py"
timeout /t 2 >nul

REM 如果浏览器还没打开就打开一下
powershell -NoProfile -Command ^
    "$ErrorActionPreference='SilentlyContinue';" ^
    "if (-not (Get-Process chrome -ErrorAction SilentlyContinue) -and -not (Get-Process msedge -ErrorAction SilentlyContinue)) {" ^
    "  Start-Process 'http://localhost:8765/index.html'" ^
    "}"

echo 浏览器若没自动弹出，请手动访问 http://localhost:8765/index.html
echo.
pause
endlocal
