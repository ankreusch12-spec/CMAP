@echo off
rem ===================================================================
rem  Controle CMAP - ABRIR (use sempre que quiser usar o controle)
rem ===================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Controle CMAP - deixe esta janela aberta enquanto usa

rem A instalacao fica numa pasta fixa (feita uma vez pelo instalar.bat)
set "VENV=%LOCALAPPDATA%\ControleCMAP\venv"
if exist "%VENV%\Scripts\python.exe" goto instalado
rem Instalacoes antigas tinham a pasta .venv aqui mesmo: continuam funcionando
if exist ".venv\Scripts\python.exe" set "VENV=.venv"
if exist "%VENV%\Scripts\python.exe" goto instalado
echo "%~dp0" | find /i "\AppData\Local\Temp\" >nul && goto dentro_do_zip
goto sem_instalar

:instalado
rem Abre o navegador daqui a 3 segundos (tempo do controle ligar)
start "" /min cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"

echo ============================================================
echo  Controle CMAP ligado em http://127.0.0.1:5000
echo  Deixe esta janela aberta enquanto usa.
echo  Para desligar: feche esta janela (ou Ctrl+C).
echo ============================================================
"%VENV%\Scripts\python.exe" app.py
pause
exit /b 0

:dentro_do_zip
echo Voce abriu o controle de DENTRO do ZIP.
echo Botao direito no ZIP ^> Extrair tudo... e abra o abrir_controle.bat da pasta extraida.
pause
exit /b 1

:sem_instalar
echo O controle ainda nao foi instalado neste computador.
echo De dois cliques em instalar.bat (so uma vez; depois nao precisa mais).
pause
exit /b 1
