@echo off
REM =================================================================
REM  setup.bat - 一键安装 NDX 打分系统 (Portable / Embedded Python)
REM =================================================================
REM  此脚本在任意 Windows 电脑上均可运行。无需任何已装的 Python。
REM  流程：
REM    1) 检测（或解压）嵌入版 Python（python\python.exe）
REM    2) 开启 site-packages 支持（修改 python313._pth）
REM    3) 安装 pip + yfinance/pandas/numpy
REM    4) 注册开机自启（watchdog）
REM    5) 立即启动并打开浏览器
REM =================================================================

setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PY_DIR=%CD%\python"
set "PY_EXE=%PY_DIR%\python.exe"
set "PYW_EXE=%PY_DIR%\pythonw.exe"

echo.
echo === NDX 打分系统 - 一键安装 ===
echo 工作目录: %CD%
echo.

REM ---------- Step 1: Python interpreter ----------
if not exist "%PY_EXE%" (
    echo [1/5] 检测到嵌入版 Python 缺失，正在准备...
    if not exist python-embed.zip (
        echo   [错误] 缺少 python-embed.zip，请把它放回此目录再重试。
        pause
        exit /b 1
    )
    if not exist "%PY_DIR%" mkdir "%PY_DIR%"
    echo   解压 python-embed.zip ...
    powershell -NoProfile -Command "Expand-Archive -Force -Path '.\python-embed.zip' -DestinationPath '.\python'"
    if errorlevel 1 (
        echo   [错误] 解压失败。请检查 PowerShell 可用性或手动解压。
        pause
        exit /b 1
    )
) else (
    echo [1/5] 嵌入版 Python 已就绪: %PY_EXE%
)

REM ---------- Step 2: 开启 site-packages ----------
echo [2/5] 配置 site-packages ...
set "_PTH=%PY_DIR%\python313._pth"
> "%_PTH%.tmp" echo python313.zip
>>"%_PTH%.tmp" echo .
>>"%_PTH%.tmp" echo.
>>"%_PTH%.tmp" echo # Uncomment to run site.main() automatically
>>"%_PTH%.tmp" echo import site
>>"%_PTH%.tmp" echo Lib\site-packages
move /y "%_PTH%.tmp" "%_PTH%" >nul

REM ---------- Step 3: 安装依赖 ----------
echo [3/5] 检查并安装依赖 (pip / yfinance / pandas / numpy)...
"%PY_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo   下载 get-pip.py ...
    powershell -NoProfile -Command "$wc = New-Object Net.WebClient; $wc.DownloadFile('https://bootstrap.pypa.io/get-pip.py','%CD%\get-pip.py')"
    if errorlevel 1 (
        echo   [错误] 无法下载 get-pip.py，请检查网络。
        pause
        exit /b 1
    )
    "%PY_EXE%" get-pip.py --no-warn-script-location >nul
    if exist get-pip.py del /q get-pip.py
)
"%PY_EXE%" -c "import yfinance, pandas, numpy; print('  已就绪')" 2>nul
if errorlevel 1 (
    echo   正在安装 yfinance pandas numpy ...
    "%PY_EXE%" -m pip install --no-warn-script-location yfinance pandas numpy requests
    if errorlevel 1 (
        echo   [错误] pip install 失败。
        pause
        exit /b 1
    )
)

REM ---------- Step 4: 注册开机自启 ----------
echo [4/5] 注册开机自启 ...
"%PY_EXE%" "%CD%\register_autostart.py" install
if errorlevel 1 (
    echo   [警告] 自启注册失败。可以稍后手动执行。
)

REM ---------- Step 5: 立即启动并打开浏览器 ----------
echo [5/5] 启动 watchdog 并打开浏览器...
start "" "%PYW_EXE%" "%CD%\watchdog.py"
timeout /t 2 >nul
start "" "http://localhost:8765/index.html"

echo.
echo === 安装完成 ===
echo - 重启电脑后会自动运行。
echo - 浏览器已打开: http://localhost:8765/index.html
echo - 如需卸载请运行 uninstall.bat
echo.
pause
endlocal
