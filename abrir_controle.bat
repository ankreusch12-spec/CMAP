@echo off
rem ===================================================================
rem  Controle CMAP - ABRIR (use sempre que quiser usar o controle)
rem ===================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Controle CMAP - deixe esta janela aberta enquanto usa

if not exist ".venv\Scripts\python.exe" goto sem_instalar

rem Abre o navegador daqui a 3 segundos (tempo do controle ligar)
start "" /min cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"

echo ============================================================
echo  Controle CMAP ligado em http://127.0.0.1:5000
echo  Deixe esta janela aberta enquanto usa.
echo  Para desligar: feche esta janela (ou Ctrl+C).
echo ============================================================
".venv\Scripts\python.exe" app.py
pause
exit /b 0

:sem_instalar
echo O controle ainda nao foi instalado.
echo De dois cliques em instalar.bat primeiro.
pause
exit /b 1
