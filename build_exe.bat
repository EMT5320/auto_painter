@echo off
echo ===================================
echo   Auto Painter - 打包为 EXE
echo ===================================
echo.

REM 检查 pyinstaller
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
)

echo 开始打包...
pyinstaller --onefile --windowed --name "AutoPainter" ^
    --add-data "image_processor.py;." ^
    --add-data "path_optimizer.py;." ^
    --add-data "mouse_controller.py;." ^
    --hidden-import=customtkinter ^
    --hidden-import=windnd ^
    --hidden-import=PIL ^
    gui_app.py

echo.
if exist "dist\AutoPainter.exe" (
    echo ✅ 打包成功！
    echo    输出: dist\AutoPainter.exe
) else (
    echo ❌ 打包失败，请检查错误信息
)
echo.
pause
