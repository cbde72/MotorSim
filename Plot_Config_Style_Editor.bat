@echo off
setlocal
cd /d "%~dp0"

set "EDITOR_PYTHON=C:\ProgramData\anaconda3\python.exe"
if exist "%EDITOR_PYTHON%" goto start_editor

where python >nul 2>nul
if errorlevel 1 goto no_python
set "EDITOR_PYTHON=python"

:start_editor
"%EDITOR_PYTHON%" scripts\run_plot_config_style_editor.py
if errorlevel 1 pause
exit /b %errorlevel%

:no_python
echo Python wurde nicht gefunden.
echo Bitte Python mit PySide6 installieren oder den Editor aus der Projektumgebung starten.
pause
exit /b 1
