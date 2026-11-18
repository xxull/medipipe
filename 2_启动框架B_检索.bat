@echo off
chcp 65001 >nul
title 框架 B · 数据检索
cd /d "%~dp0"
echo ============================================================
echo   框架 B · 数据检索
echo   地址：http://127.0.0.1:8502
echo.
echo   五个标签页：概览 / 相似病例 / 关键词检索 / 病历总结 / 自检
echo   不配 Key 也能用；相似检索需要本机 Ollama 的 bge-m3
echo   关闭这个窗口 = 停止服务
echo ============================================================
echo.
python -m streamlit run framework_b\app_b.py --server.port=8502 --server.headless=true
if errorlevel 1 (
  echo.
  echo [启动失败] 可能没装依赖，先运行：pip install -r requirements.txt
)
pause
