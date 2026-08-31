@echo off
cd /d "%~dp0"

rem Python automatisch finden:
rem  1) Hermes-eigene venv (falls vorhanden)
rem  2) py launcher (Windows-Standard)
rem  3) python im PATH
set "PYTHON="
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PYTHON (
    where py >nul 2>nul && set "PYTHON=py"
)
if not defined PYTHON (
    where python >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    echo Python wurde nicht gefunden.
    echo Bitte installiere Python 3.11+ von https://python.org und starte neu.
    pause
    exit /b 1
)

rem tkinter pruefen (fuer die GUI)
%PYTHON% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo tkinter ist nicht installiert. Bitte Python mit tkinter installieren.
    pause
    exit /b 1
)

%PYTHON% monitor.py
if errorlevel 1 pause
