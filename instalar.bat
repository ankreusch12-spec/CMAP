@echo off
rem ===================================================================
rem  Controle CMAP - INSTALAR (rode uma vez so; pode rodar de novo)
rem ===================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Controle CMAP - Instalacao

echo ============================================================
echo  Controle CMAP - instalacao
echo ============================================================
echo.
rem --- 0) Nao pode rodar de dentro do ZIP (o Windows usa uma pasta temporaria) ---
echo "%~dp0" | find /i "\AppData\Local\Temp\" >nul && goto dentro_do_zip


rem --- 1) Procura o Python -------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto sem_python
echo [1/4] Python encontrado:
%PY% --version
echo.

rem --- 2) Cria o ambiente .venv (so na primeira vez) ------------------
if exist ".venv\Scripts\python.exe" goto tem_venv
echo [2/4] Criando o ambiente do controle (.venv)...
%PY% -m venv .venv
if errorlevel 1 goto erro
:tem_venv
echo [2/4] Ambiente OK.
echo.

rem --- 3) Instala as bibliotecas (Flask e openpyxl) -------------------
echo [3/4] Instalando as bibliotecas (pode levar 1 ou 2 minutos)...
rem    Primeiro tenta pelos pacotes que ja vem na pasta "pacotes" (sem internet).
rem    Se nao der (ex.: Python diferente), baixa da internet.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-index --find-links pacotes -r requirements.txt
if not errorlevel 1 goto pip_ok
echo       Pacotes da pasta nao serviram; baixando da internet...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto erro_pip
:pip_ok
echo [3/4] Bibliotecas OK.
echo.

rem --- 4) Pergunta seu nome e o caminho do forecast -------------------
echo [4/4] Configuracao:
".venv\Scripts\python.exe" configurar.py
if errorlevel 1 goto erro

echo.
echo ============================================================
echo  Tudo certo! Para usar, de dois cliques em abrir_controle.bat
echo ============================================================
pause
exit /b 0

:dentro_do_zip
echo [ATENCAO] Voce abriu o instalar.bat de DENTRO do ZIP.
echo O Windows colocou os arquivos numa pasta temporaria, que pode ser apagada.
echo.
echo Feche esta janela e faca assim:
echo   1. Botao direito no "Controle CMAP.zip" ^> Extrair tudo...
echo   2. Escolha uma pasta fixa, por exemplo Documentos
echo   3. Abra a pasta extraida e de dois cliques no instalar.bat
pause
exit /b 1

:sem_python
echo [ERRO] Nao achei o Python neste computador.
echo Instale o Python 3.11 ou mais novo (peca ao TI ou pelo Portal da Empresa)
echo e marque a opcao "Add python.exe to PATH". Depois rode este arquivo de novo.
pause
exit /b 1

:erro_pip
echo [ERRO] Nao consegui baixar as bibliotecas.
echo Confira a internet/VPN. Se a rede da empresa bloquear, mande print desta tela ao TI.
pause
exit /b 1

:erro
echo [ERRO] Algo deu errado acima. Tire um print desta janela e me mande.
pause
exit /b 1
