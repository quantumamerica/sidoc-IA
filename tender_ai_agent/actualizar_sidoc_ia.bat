@echo off
rem Actualiza esta copia de sidoc-IA con la rama main (git pull --ff-only).
rem Programado en la VM de lunes a viernes a las 15:00, una hora antes de la corrida.
rem Si hay cambios locales sin commitear no pisa nada: anota el error y sale.
rem
rem Como el pull puede reemplazar este mismo archivo, primero se copia a %TEMP% y
rem sigue desde la copia (cmd lee los .bat linea por linea mientras corren).
setlocal enabledelayedexpansion

if /i not "%~1"=="--desde-copia" (
    copy /y "%~f0" "%TEMP%\actualizar_sidoc_ia_copia.bat" >nul
    "%TEMP%\actualizar_sidoc_ia_copia.bat" --desde-copia "%~dp0"
)

set "WORKSPACE=%~2"
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOG_FILE=%WORKSPACE%\actualizar_log.txt"
set "PYTHON_PATH=%WORKSPACE%\.venv\Scripts\python.exe"

echo ========================================== >> "%LOG_FILE%"
echo Actualizacion: %date% %time% >> "%LOG_FILE%"

cd /d "%WORKSPACE%\.."
if errorlevel 1 (
    echo ERROR: no se pudo entrar a la carpeta del repo >> "%LOG_FILE%"
    exit /b 1
)

set "CAMBIOS="
for /f "delims=" %%l in ('git status --porcelain --untracked-files^=no') do set "CAMBIOS=1"
if defined CAMBIOS (
    echo ERROR: hay cambios locales sin commitear; no se actualiza. Revisar con git status. >> "%LOG_FILE%"
    git status --short --untracked-files=no >> "%LOG_FILE%" 2>&1
    exit /b 1
)

for /f "delims=" %%h in ('git rev-parse HEAD') do set "ANTES=%%h"
git pull --ff-only origin main >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo ERROR: git pull fallo >> "%LOG_FILE%"
    exit /b 1
)
for /f "delims=" %%h in ('git rev-parse HEAD') do set "DESPUES=%%h"

if "%ANTES%"=="%DESPUES%" (
    echo Sin cambios: %DESPUES% >> "%LOG_FILE%"
    exit /b 0
)
echo Actualizado de %ANTES% a %DESPUES% >> "%LOG_FILE%"
git log --oneline %ANTES%..%DESPUES% >> "%LOG_FILE%" 2>&1

set "REQS="
for /f "delims=" %%f in ('git diff --name-only %ANTES% %DESPUES% -- tender_ai_agent/requirements.txt') do set "REQS=1"
if defined REQS (
    if not exist "%PYTHON_PATH%" set "PYTHON_PATH=python"
    echo requirements.txt cambio: instalando dependencias >> "%LOG_FILE%"
    "!PYTHON_PATH!" -m pip install -r "%WORKSPACE%\requirements.txt" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo ERROR: pip install fallo >> "%LOG_FILE%"
        exit /b 1
    )
)

echo Listo >> "%LOG_FILE%"
exit /b 0
