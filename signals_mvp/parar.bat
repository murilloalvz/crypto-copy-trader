@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
title Parar o bot de sinais
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m signals_mvp parar
) else (
  python -m signals_mvp parar
)
echo.
pause
