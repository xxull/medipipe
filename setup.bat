@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
  python -m venv .venv
  if errorlevel 1 (
    echo 创建虚拟环境失败：请先安装 Python 3.10+ 并加入 PATH
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 pause
