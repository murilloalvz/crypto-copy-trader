@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
title Testar o bot de sinais
echo === 1/3 Self-check (sem rede, dados falsos) ===
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m signals_mvp selfcheck
) else (
  python -m signals_mvp selfcheck
)
echo.
echo === 2/3 Teste de rede (APIs reais, so leitura) ===
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m signals_mvp teste-rede
) else (
  python -m signals_mvp teste-rede
)
echo.
echo === 3/3 Teste do Telegram (envia UMA mensagem de teste) ===
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m signals_mvp teste-telegram
) else (
  python -m signals_mvp teste-telegram
)
echo.
pause
