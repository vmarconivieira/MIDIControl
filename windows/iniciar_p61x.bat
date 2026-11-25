@echo off
chcp 65001 >nul
setlocal EnableExtensions
title P61x Console v1.3.7
cd /d "%~dp0"

echo =======================================================
echo   P61x Console v1.3.7 (Stage Synth, Worship Pad & Drums)
echo =======================================================
echo.

set "RUN_PY="
if exist "%~dp0runtime\python.exe" set "RUN_PY=%~dp0runtime\python.exe"
if not defined RUN_PY if exist "%~dp0.venv\Scripts\python.exe" set "RUN_PY=%~dp0.venv\Scripts\python.exe"
set "PATH=%~dp0dsp;%~dp0runtime;%~dp0runtime\Lib\site-packages\PySide6;%~dp0runtime\Lib\site-packages\shiboken6;%PATH%"
if not defined RUN_PY if exist "%~dp0config\.python_exe.txt" (
    for /f "usebackq delims=" %%P in ("%~dp0config\.python_exe.txt") do (
        if exist "%%~P" set "RUN_PY=%%~P"
    )
)
if not defined RUN_PY (
    for %%V in (3.12 3.11 3.10 3.13 3.14) do (
        if not defined RUN_PY (
            py -%%V -c "import PySide6; import sys; print(sys.executable)" >nul 2>&1
            if not errorlevel 1 (
                for /f "usebackq delims=" %%P in (`py -%%V -c "import sys; print(sys.executable)" 2^>nul`) do set "RUN_PY=%%P"
            )
        )
    )
)
if not defined RUN_PY (
    python -c "import PySide6" >nul 2>&1
    if not errorlevel 1 (
        for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "RUN_PY=%%P"
    )
)

if not defined RUN_PY (
    echo [ERRO] Ambiente Python com PySide6 nao encontrado!
    echo Execute primeiro o arquivo 'instalar_windows.bat' ^(apos extrair toda a pasta do ZIP^).
    echo.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
set "QTWEBENGINE_DISABLE_SANDBOX=1"
set "QTWEBENGINE_CHROMIUM_FLAGS=--disable-features=WebMidi,WebHID,WebUSB,HardwareMediaKeyHandling"

echo Usando Python: "%RUN_PY%"
echo Iniciando motor de audio DSP e interface grafica...
echo ^(Mantenha esta janela aberta enquanto toca ou use 'iniciar_p61x_sem_terminal.vbs'^)
echo.

"%RUN_PY%" "%~dp0main.py" %*
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERRO] O P61x Console encerrou com codigo %EXIT_CODE%.
    if exist "%~dp0logs\p61x_startup_error.log" (
        echo --- Detalhes em logs\p61x_startup_error.log ---
        type "%~dp0logs\p61x_startup_error.log"
    )
    echo.
    pause
    exit /b %EXIT_CODE%
)
