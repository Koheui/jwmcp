@echo off
REM Opens the jwmcp settings UI (http://127.0.0.1:8765). Run setup.bat first.
cd /d "%~dp0\..\.."
for %%I in ("%CD%\..") do set "SHARE=%%~fI"
if "%JWMCP_HOME%"=="" if exist "%SHARE%\home" set "JWMCP_HOME=%SHARE%\home"
if "%JWMCP_EXCHANGE%"=="" if exist "%SHARE%\exchange" set "JWMCP_EXCHANGE=%SHARE%\exchange"
"%LOCALAPPDATA%\jwmcp\venv\Scripts\python.exe" -m jwmcp settings %*
