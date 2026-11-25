@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Instalador P61x Console v1.3.6 - Windows
cd /d "%~dp0"

echo =====================================================================
echo         INSTALADOR AUTOMATICO DO P61X CONSOLE v1.3.6 (WINDOWS)
echo =====================================================================
echo.

:: 1. Localizar Python 3.10+ (64-bit), dando preferencia ao Python 3.12 (wheels completos)
echo [1/5] Verificando Python 3.10+ (64-bit) no sistema...
set "PY_EXE="

for %%V in (3.12 3.11 3.10 3.13 3.14) do (
    if not defined PY_EXE (
        py -%%V -c "import sys; sys.exit(0 if sys.version_info >= (3,10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
        if not errorlevel 1 (
            for /f "usebackq delims=" %%P in (`py -%%V -c "import sys; print(sys.executable)" 2^>nul`) do (
                if not defined PY_EXE set "PY_EXE=%%P"
            )
        )
    )
)

if defined PY_EXE goto :found_python

for %%D in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
) do (
    if not defined PY_EXE if exist "%%~D" (
        "%%~D" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_EXE=%%~D"
    )
)

if defined PY_EXE goto :found_python

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 (
    for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
        if not defined PY_EXE set "PY_EXE=%%P"
    )
)

if defined PY_EXE goto :found_python

echo [AVISO] Python 64-bit nao encontrado. Tentando instalar Python 3.12 via Winget...
where winget >nul 2>&1
if errorlevel 1 goto :python_not_found
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
for %%D in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%ProgramFiles%\Python312\python.exe"
) do (
    if not defined PY_EXE if exist "%%~D" set "PY_EXE=%%~D"
)
if not defined PY_EXE (
    for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys; print(sys.executable)" 2^>nul`) do (
        if not defined PY_EXE set "PY_EXE=%%P"
    )
)
if defined PY_EXE goto :found_python

:python_not_found
echo.
echo [ERRO] Python 3.10+ (64-bit) nao foi encontrado no Windows!
echo Instale em: https://www.python.org/downloads/ (recomendado Python 3.12 64-bit)
echo IMPORTANTE: Na primeira tela do instalador, marque "[X] Add python.exe to PATH".
echo Depois execute este instalador novamente.
echo.
pause
exit /b 1

:found_python
echo Python 64-bit encontrado: "%PY_EXE%"
"%PY_EXE%" --version
echo.

:: 2. Criar ambiente virtual isolado (.venv)
echo [2/5] Configurando ambiente virtual (.venv)...
set "RUN_PY=%~dp0.venv\Scripts\python.exe"
if exist "%RUN_PY%" goto :venv_ready

"%PY_EXE%" -m venv "%~dp0.venv"
if not errorlevel 1 goto :venv_ready

echo [AVISO] Falha ao criar .venv, instalando no Python principal selecionado...
set "RUN_PY=%PY_EXE%"
if not exist "%~dp0config" mkdir "%~dp0config" >nul 2>&1
> "%~dp0config\.python_exe.txt" echo %PY_EXE%
goto :install_deps

:venv_ready
if exist "%~dp0config\.python_exe.txt" del "%~dp0config\.python_exe.txt" >nul 2>&1

:install_deps
echo.
echo [3/5] Instalando PySide6 e NumPy (e python-rtmidi quando suportado)...
"%RUN_PY%" -m pip install --upgrade pip
"%RUN_PY%" -m pip install -r "%~dp0requirements-windows.txt"
if not errorlevel 1 goto :deps_ok

echo.
echo [AVISO] Tentando instalar pacotes essenciais (PySide6 e numpy) sem rtmidi...
"%RUN_PY%" -m pip install "PySide6>=6.5.0" "numpy>=1.24.0"
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao baixar dependencias Python. Verifique sua conexao com a internet.
    pause
    exit /b 1
)

:deps_ok
:: 4. Teste rapido dos modulos Python e biblioteca DSP (stagerig_dsp.dll)
echo.
echo [4/5] Verificando modulos graficos e motor DSP nativo...
set "PATH=%~dp0dsp;%PATH%"
set "PYTHONUTF8=1"
"%RUN_PY%" -c "import os, ctypes, numpy, PySide6.QtWebEngineWidgets; ctypes.CDLL(os.path.join(r'%~dp0dsp', 'stagerig_dsp.dll')); import standalone_midi_engine; print('[OK] PySide6 WebEngine, NumPy, stagerig_dsp.dll e MIDI verificados!')"
if errorlevel 1 (
    echo.
    echo [ERRO] Falha na verificacao dos componentes do P61x Console.
    echo Confira se voce extraiu TODA a pasta do ZIP antes de executar o instalador!
    echo Se o erro mencionar VCRUNTIME140.dll, instale o Microsoft Visual C++ Redistributable 64-bit.
    pause
    exit /b 1
)

:: 5. Criar atalho na Area de Trabalho via VBScript (suporta acentos e OneDrive)
echo.
echo [5/5] Criando atalho na Area de Trabalho...
set "SHORTCUT_VBS=%TEMP%\CreateP61xShortcut_%RANDOM%.vbs"
> "%SHORTCUT_VBS%" (
    echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
    echo Set oWS = CreateObject^("WScript.Shell"^)
    echo desktopDir = oWS.SpecialFolders^("Desktop"^)
    echo If desktopDir = "" Then desktopDir = oWS.ExpandEnvironmentStrings^("%%USERPROFILE%%\Desktop"^)
    echo baseDir = fso.GetAbsolutePathName^("%~dp0."^)
    echo Set oLink = oWS.CreateShortcut^(desktopDir ^& "\P61x Console.lnk"^)
    echo oLink.TargetPath = baseDir ^& "\iniciar_p61x_sem_terminal.vbs"
    echo oLink.WorkingDirectory = baseDir
    echo oLink.Description = "P61x Console v1.3.5 - Stage Synth, Worship Pad & Drum Pads"
    echo iconPath = baseDir ^& "\ui\p61x-keyboard.ico"
    echo If fso.FileExists^(iconPath^) Then oLink.IconLocation = iconPath ^& ", 0"
    echo oLink.Save
)
cscript //nologo "%SHORTCUT_VBS%"
set "VBS_ERR=%errorlevel%"
del "%SHORTCUT_VBS%" >nul 2>&1
if not "%VBS_ERR%"=="0" (
    echo [AVISO] Nao foi possivel criar o atalho automatico. Use 'iniciar_p61x.bat' ou 'iniciar_p61x_sem_terminal.vbs'.
)

echo.
echo =====================================================================
echo  [SUCESSO] Instalacao do P61x Console v1.3.4 concluida!
echo  Abra pelo atalho "P61x Console" na Area de Trabalho, ou executando
echo  'iniciar_p61x.bat' / 'iniciar_p61x_sem_terminal.vbs'.
echo =====================================================================
echo.
pause
