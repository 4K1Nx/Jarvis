@echo off
setlocal
cd /d "%~dp0"
title Viv

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: ambiente Python nao encontrado. Veja a secao Instalacao do README_VIV.md.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -u main.py %*
set "VIV_EXIT_CODE=%ERRORLEVEL%"

if not "%VIV_EXIT_CODE%"=="0" (
    echo.
    echo A Viv encerrou com erro. Codigo: %VIV_EXIT_CODE%
    pause
)
exit /b %VIV_EXIT_CODE%
