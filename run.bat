@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo 首次运行：正在安装依赖（PySide6 较大，请耐心等待）...
    python -m pip install --disable-pip-version-check -r requirements.txt
)

rem 用 pythonw 启动，不保留命令行窗口
start "" pythonw main.py
