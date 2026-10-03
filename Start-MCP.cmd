@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m builder.mcp_server %*
) else (
  py -3.12 -m builder.mcp_server %*
)
