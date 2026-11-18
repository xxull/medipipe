@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo ============================================
echo   Framework A - 数据生产兵工厂
echo   浏览器：http://127.0.0.1:8501
echo   关闭窗口 = 停止服务
echo ============================================
echo.

"%PY%" -m streamlit run app.py --server.port=8501
if errorlevel 1 pause
