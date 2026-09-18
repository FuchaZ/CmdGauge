@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  CmdGauge 打包脚本 (PyInstaller 单文件 exe)
echo ============================================
echo.

echo [1/4] 安装依赖...
pip install -q pywebview pystray pillow pyinstaller || goto :err

echo [2/4] 生成应用图标...
python scripts\build_icon.py || goto :err

echo [3/4] 打包单文件 exe (无控制台窗口, logo 图标)...
echo       裁剪误收集依赖 (numpy/cryptography/PIL._avif), 体积约减半
pyinstaller --noconfirm --clean --onefile --noconsole --name CmdGauge ^
  --add-data "app\web;app\web" ^
  --add-data "assets;assets" ^
  --icon assets\CmdGauge.ico ^
  --collect-submodules webview ^
  --hidden-import clr ^
  --hidden-import pythonnet ^
  --hidden-import pystray ^
  --exclude-module numpy ^
  --exclude-module cryptography ^
  --exclude-module PIL._avif ^
  entry.py || goto :err

echo [4/4] 完成!
echo.
echo 输出: dist\CmdGauge.exe
echo 数据目录: 首次运行会在 exe 同目录创建 data\ 文件夹
echo.
pause
exit /b 0

:err
echo.
echo 打包失败, 请检查上方错误信息
pause
exit /b 1
