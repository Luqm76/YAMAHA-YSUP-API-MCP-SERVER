@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m builder --open
) else (
  py -3.12 -m builder --open
)
if errorlevel 1 pause
