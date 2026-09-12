@echo off
REM jwmcp Windows setup (run once). Creates .venv, installs jwmcp, prepares the 外部変形 exchange folder,
REM and registers the MCP server with Claude Code if the `claude` CLI is available.
setlocal enabledelayedexpansion
cd /d "%~dp0\..\.."
set "ROOT=%CD%"
echo === jwmcp setup in %ROOT%

where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>&1 || (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/windows/ ^(check "Add python.exe to PATH"^) and run this again.
  pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PY% --version') do set "PYVER=%%v"
echo Python %PYVER%

if not exist ".venv\Scripts\python.exe" (
  echo creating .venv ...
  %PY% -m venv .venv || (echo venv failed & pause & exit /b 1)
)
set "VPY=%ROOT%\.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul
echo installing jwmcp and dependencies ...
"%VPY%" -m pip install -e ".[dev]" || (echo install failed & pause & exit /b 1)

echo running tests ...
"%VPY%" -m pytest -q || echo (some tests failed - the server may still work; see output above)

echo preparing the 外部変形 exchange folder ...
"%VPY%" -c "from jwmcp import bridge; import json; print(json.dumps(bridge.setup(), ensure_ascii=False, indent=1))"

where claude >nul 2>&1 && (
  echo registering with Claude Code ...
  claude mcp add jwmcp --scope user -- "%VPY%" -m jwmcp && echo registered: jwmcp
) || (
  echo Claude Code CLI not found. Register manually:
  echo   claude mcp add jwmcp --scope user -- "%VPY%" -m jwmcp
  echo or add to Claude Desktop's claude_desktop_config.json:
  echo   {"mcpServers": {"jwmcp": {"command": "%VPY:\=\\%", "args": ["-m", "jwmcp"]}}}
)

echo.
echo === done.
echo   settings UI : scripts\windows\settings.bat   ^(http://127.0.0.1:8765^)
echo   Jw_cad      : copy %USERPROFILE%\JW_MCP_Exchange\gaihen\*.bat where you like and pick them from 外部変形
echo   The exchange folder is %USERPROFILE%\JW_MCP_Exchange ^(set JWMCP_EXCHANGE to move it, e.g. onto Google Drive^)
pause
