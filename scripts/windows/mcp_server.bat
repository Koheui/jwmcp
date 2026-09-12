@echo off
REM Starts the MCP server on stdio (what Claude Code / Antigravity launch). Handy for a manual check.
cd /d "%~dp0\..\.."
for %%I in ("%CD%\..") do set "SHARE=%%~fI"
if "%JWMCP_HOME%"=="" if exist "%SHARE%\home" set "JWMCP_HOME=%SHARE%\home"
if "%JWMCP_EXCHANGE%"=="" set "JWMCP_EXCHANGE=%LOCALAPPDATA%\jwmcp\exchange"
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m jwmcp
