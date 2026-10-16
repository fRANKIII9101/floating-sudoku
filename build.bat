@echo off
REM ============================================================
REM  悬浮窗数独 —— 一键打包为单文件 exe
REM  需要本机有「自带 tkinter 的 Python 3」（Windows 标准 CPython 都有）
REM  用法：把本文件放在 sudoku 目录，双击即可
REM  产物：dist\SudokuFloat.exe（双击就是悬浮窗数独，不再依赖 Python）
REM ============================================================

cd /d %~dp0

REM ---- 找一个带 tkinter 的 Python ----
REM 优先用本机已有的 SDK / 独立 Python（%USERPROFILE% 会自动展开，无硬编码用户名）
set "PY="
if exist "%USERPROFILE%\python-sdk\python3.13.2\python.exe" (
    set "PY=%USERPROFILE%\python-sdk\python3.13.2\python.exe"
)
if not defined PY (
    for %%P in (python py) do (
        if not defined PY (
            %%P -c "import tkinter" >nul 2>nul && set "PY=%%P"
        )
    )
)
if not defined PY (
    echo [fail] 没找到带 tkinter 的 Python。请安装标准 CPython 3（python.org）后重试。
    pause
    exit /b 1
)
echo [*] 使用 Python: %PY%

echo [*] 正在安装/升级 PyInstaller 与托盘依赖 ...
"%PY%" -m pip install --upgrade pyinstaller pystray pillow

echo [*] 正在打包（单文件 / 无控制台窗口）...
"%PY%" -m PyInstaller --onefile --windowed --clean ^
    --name SudokuFloat --hidden-import pystray._win32 sudoku_floating.py

echo.
if exist dist\SudokuFloat.exe (
    echo [done] 打包成功：dist\SudokuFloat.exe
) else (
    echo [fail] 未生成 exe，请看上方报错（通常是该 Python 缺少 tkinter）。
)
pause
