@echo off
REM =================================================================
REM  uninstall.bat - 干净卸载 NDX 打分系统
REM =================================================================
REM  - 杀掉后台进程 (watchdog / serve)
REM  - 移除开机自启
REM  - 删除生成的数据文件（可选：index.html / ndx_*.json / 日志）
REM =================================================================

setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PY_EXE=%CD%\python\python.exe"

echo.
echo === NDX 打分系统 - 卸载 ===
echo.

REM ---------- 杀掉后台进程 ----------
echo [1/3] 停止后台进程 ...
taskkill /F /IM pythonw.exe /T 2>nul
taskkill /F /IM python.exe /T 2>nul
echo   已结束。

REM ---------- 移除自启 ----------
echo [2/3] 移除开机自启 ...
if exist "%PY_EXE%" (
    "%PY_EXE%" "%CD%\register_autostart.py" remove
) else (
    REM Embedded Python 不在时, 直接清理兜底项
    set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\NDXDashboard.vbs"
    if exist "!VBS!" del /q "!VBS!"
    echo   （注意：嵌入版 Python 不在，只清掉了 Startup 兜底）
)

REM ---------- 询问是否清除生成的输出 ----------
echo [3/3] 清理运行时生成的数据...
set /p "CLEAN=是否删除 index.html / ndx_*.json / 日志？(y/N): "
if /I "!CLEAN!"=="y" (
    if exist index.html del /q index.html
    if exist ndx_history.json del /q ndx_history.json
    if exist ndx_snapshot.json del /q ndx_snapshot.json
    if exist serve.log del /q serve.log
    if exist serve.err.log del /q serve.err.log
    if exist serve.watchdog.log del /q serve.watchdog.log
    if exist ndx_crash.log del /q ndx_crash.log
    echo   已删除。
) else (
    echo   保留。
)

echo.
echo === 卸载完成 ===
echo 如需彻底删除项目，请连同本目录一起 rm。
echo.
pause
endlocal
