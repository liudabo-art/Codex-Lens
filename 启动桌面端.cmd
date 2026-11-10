@echo off
setlocal
cd /d "%~dp0"
if exist "dist\latest-desktop.cmd" (
  call "dist\latest-desktop.cmd"
  exit /b
)
if exist "dist\Relay-Auditor\Relay-Auditor.exe" (
  start "" "dist\Relay-Auditor\Relay-Auditor.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -I -B desktop.py
  exit /b
)
start "" pythonw -I -B desktop.py
