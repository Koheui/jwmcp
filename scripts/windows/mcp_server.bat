@echo off
REM Starts the MCP server on stdio (what Claude Code / Claude Desktop launch). Useful for manual checks.
cd /d "%~dp0\..\.."
".venv\Scripts\python.exe" -m jwmcp
