@echo off
REM Opens the jwmcp settings UI (http://127.0.0.1:8765). Run setup.bat first (it sets JWMCP_HOME / JWMCP_EXCHANGE).
cd /d "%~dp0\..\.."
for %%I in ("%CD%\..") do set "SHARE=%%~fI"
if "%JWMCP_HOME%"=="" if exist "%SHARE%\home" set "JWMCP_HOME=%SHARE%\home"
if "%JWMCP_EXCHANGE%"=="" set "JWMCP_EXCHANGE=%LOCALAPPDATA%\jwmcp\exchange"
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m jwmcp settings %*
