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

echo [3/3] 打包单文件 exe（含图标与离线词典数据，约 1-3 分钟）...
python -m PyInstaller -w --onefile -n PromptLibraryManager ^
    --icon assets\icon.ico ^
    --add-data "assets\icon.png;assets" ^
    --add-data "assets\翻译.svg;assets" ^
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
echo 完成！单文件程序在：dist\PromptLibraryManager.exe
echo 双击即可运行（首次启动会解压，稍慢几秒）。
pause
