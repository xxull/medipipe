@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================
echo   Framework B · 检索应用（独立运行）
echo   地址：http://127.0.0.1:8502
echo   它只读数据库，不生产数据
echo   关闭这个窗口 = 停止服务
echo ============================================
echo.
python -m streamlit run framework_b\app_b.py --server.port=8502 --server.headless=true
pause
