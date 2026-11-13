@echo off
setlocal
cd /d "%~dp0"
title Viv - cadastro de voz
set "PYTHONUTF8=1"
echo Feche a Viv antes de continuar.
echo.
".venv\Scripts\python.exe" scripts\enroll_voice.py %*
echo.
pause
