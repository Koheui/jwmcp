@echo off
REM Opens the jwmcp settings UI in the browser.
cd /d "%~dp0\..\.."
".venv\Scripts\python.exe" -m jwmcp settings %*
