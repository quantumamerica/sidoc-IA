@echo off
setlocal enabledelayedexpansion

set "WORKSPACE=C:\Users\adamonte\Desktop\AGUSTIN\Python\SGQ_Quantum\sidoc_ia\tender_ai_agent"
set "VENV_PATH=%WORKSPACE%\.venv\Scripts"
set "PYTHON_PATH=%VENV_PATH%\python.exe"
set "LOG_FILE=%WORKSPACE%\script_log.txt"

echo ========================================== >> "%LOG_FILE%"
echo Iniciando script: %date% %time% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"

cd /d "%WORKSPACE%"
if errorlevel 1 (
    echo ERROR: No se pudo cambiar al directorio %WORKSPACE% >> "%LOG_FILE%"
    exit /b 1
)

echo Directorio actual: %CD% >> "%LOG_FILE%"

if exist "%VENV_PATH%\activate.bat" (
    echo Activando entorno virtual: %VENV_PATH% >> "%LOG_FILE%"
    call "%VENV_PATH%\activate.bat" >> "%LOG_FILE%" 2>&1
) else if exist "%WORKSPACE%\venv\Scripts\activate.bat" (
    set "VENV_PATH=%WORKSPACE%\venv\Scripts"
    set "PYTHON_PATH=!VENV_PATH!\python.exe"
    echo Activando entorno virtual: !VENV_PATH! >> "%LOG_FILE%"
    call "!VENV_PATH!\activate.bat" >> "%LOG_FILE%" 2>&1
) else (
    echo ADVERTENCIA: No se encontro entorno virtual en .venv\Scripts ni venv\Scripts. Se usara python del PATH. >> "%LOG_FILE%"
    set "PYTHON_PATH=python"
)

echo Ejecutando tender_ai_agent con provider perplexity... >> "%LOG_FILE%"
echo Comando: "%PYTHON_PATH%" main.py run --all --provider perplexity >> "%LOG_FILE%"
"%PYTHON_PATH%" main.py run --all --provider perplexity >> "%LOG_FILE%" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo Script ejecutado exitosamente >> "%LOG_FILE%"
) else (
    echo ERROR: Script fallo con codigo %EXIT_CODE% >> "%LOG_FILE%"
)

echo ========================================== >> "%LOG_FILE%"
echo Finalizando script: %date% %time% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"

if exist "%VENV_PATH%\deactivate.bat" (
    call "%VENV_PATH%\deactivate.bat" >> "%LOG_FILE%" 2>&1
)

exit /b %EXIT_CODE%
