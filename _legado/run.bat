@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo             INICIANDO VIV
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: Ambiente Python nao encontrado.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -u -X faulthandler "main.py" %*
set "VIV_EXIT_CODE=%ERRORLEVEL%"

if not "%VIV_EXIT_CODE%"=="0" (
    echo.
    echo A Viv encerrou com erro. Codigo: %VIV_EXIT_CODE%
    echo Confira data\native-crash.log para o diagnostico.
    pause
)

exit /b %VIV_EXIT_CODE%
