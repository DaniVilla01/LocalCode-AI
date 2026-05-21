@echo off
setlocal

REM Construye un .exe de consola para Windows usando PyInstaller.
REM Requisitos:
REM   py -3 -m pip install -r requirements-build.txt
REM   py -3 build_windows.bat

cd /d "%~dp0"

py -3 -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

py -3 -m PyInstaller --clean --noconfirm local-code-agent.spec
if errorlevel 1 exit /b 1

echo.
echo EXE generado en:
echo   %CD%\dist\local-code-agent.exe
echo.
echo Ejemplo:
echo   dist\local-code-agent.exe --root C:\ruta\a\tu\proyecto --model qwen2.5-coder:7b

endlocal
