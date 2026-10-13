@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
title Bot de sinais (PAPER) - Ctrl+C para parar
echo Bot de sinais de memecoins - PAPER / somente leitura. Nada aqui compra ou vende.
echo Para parar: Ctrl+C nesta janela, ou rode parar.bat em outra.
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m signals_mvp iniciar %*
) else (
  python -m signals_mvp iniciar %*
)
echo.
echo O bot parou. Se foi erro, veja signals_mvp\logs\signals_mvp.log
pause
