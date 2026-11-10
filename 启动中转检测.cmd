@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -I -S -B "%~dp0run.py" serve
) else (
  python -I -S -B "%~dp0run.py" serve
)
if errorlevel 1 (
  echo Unable to start. Python 3.11 or newer is required. No dependencies are downloaded.
  pause
)
endlocal
