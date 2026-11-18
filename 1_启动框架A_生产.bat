@echo off
chcp 65001 >nul
title 框架 A · 数据生产
cd /d "%~dp0"
echo ============================================================
echo   框架 A · 数据生产
echo   地址：http://127.0.0.1:8501
echo.
echo   三页流程：主模型配置 → 画布编排 → 开始工作
echo   关闭这个窗口 = 停止服务
echo ============================================================
echo.
python -m streamlit run app.py --server.port=8501 --server.headless=true
if errorlevel 1 (
  echo.
  echo [启动失败] 可能没装依赖，先运行：pip install -r requirements.txt
)
pause
