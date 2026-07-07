@echo off
title Vagas Academicas - Dashboard
cd /d "%~dp0"
echo Iniciando o dashboard... o navegador abre em alguns segundos.
start "" /min cmd /c "timeout /t 4 >nul & start http://localhost:8501"
python -m streamlit run dashboard.py --server.headless true --server.port 8501
