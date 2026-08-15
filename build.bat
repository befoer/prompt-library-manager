@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 安装 PyInstaller...
python -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败
    pause
    exit /b 1
)

echo [2/3] 清理旧构建...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist PromptLibraryManager.spec del /q PromptLibraryManager.spec

echo [3/3] 打包（含离线词典数据，约 1-2 分钟）...
python -m PyInstaller -w -n PromptLibraryManager ^
    --add-data "Tags\zh-CN.txt;Tags" ^
    --add-data "Tags\danbooru.csv;Tags" ^
    --add-data "Tags\e621.csv;Tags" ^
    main.py
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo 完成！程序在：dist\PromptLibraryManager\PromptLibraryManager.exe
echo 可双击运行，或拷贝整个 dist\PromptLibraryManager 文件夹到其他电脑。
pause
