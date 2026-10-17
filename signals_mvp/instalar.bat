@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
title Instalar o bot de sinais
echo Instalando dependencias (requests, PyYAML e matplotlib)...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip install -r signals_mvp\requirements.txt
) else (
  python -m pip install -r signals_mvp\requirements.txt
)
if not exist signals_mvp\.env (
  copy signals_mvp\.env.example signals_mvp\.env >nul
  echo.
  echo Criei o arquivo signals_mvp\.env. Vou abrir no Bloco de Notas: preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID e salve.
  start notepad signals_mvp\.env
)
echo.
echo Pronto. Proximo passo: testar.bat
pause
