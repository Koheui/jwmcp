@echo off
REM jwmcp Windows setup (run once, safe to re-run).
REM  - virtualenv goes to %LOCALAPPDATA%\jwmcp\venv (never inside a synced folder such as Google Drive)
REM  - if the repo lives in <share>\jwmcp, then <share>\home (profiles, drawings) and <share>\exchange
REM    (外部変形 bridge) are used so Mac and Windows see the same data
REM  - registers the MCP server with Claude Code when the `claude` CLI exists; prints the JSON for
REM    Antigravity / Claude Desktop otherwise
setlocal enabledelayedexpansion
cd /d "%~dp0\..\.."
set "ROOT=%CD%"
for %%I in ("%ROOT%\..") do set "SHARE=%%~fI"
echo === jwmcp setup   repo: %ROOT%

where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>&1 || (
  echo Python 3.11 or newer is required. Install from https://www.python.org/downloads/windows/
  echo and tick "Add python.exe to PATH", then run this again.
  pause & exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PY% --version') do echo Python %%v

set "VENV=%LOCALAPPDATA%\jwmcp\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo creating virtualenv %VENV% ...
  %PY% -m venv "%VENV%" || (echo venv failed & pause & exit /b 1)
)
set "VPY=%VENV%\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul
echo installing jwmcp and dependencies ...
"%VPY%" -m pip install -e "%ROOT%[dev]" || (echo install failed & pause & exit /b 1)

REM ---- shared data folders (next to the repo if they exist, else user profile)
if exist "%SHARE%\exchange" (set "JWMCP_EXCHANGE=%SHARE%\exchange") else (set "JWMCP_EXCHANGE=%USERPROFILE%\JW_MCP_Exchange")
if exist "%SHARE%\home" (set "JWMCP_HOME=%SHARE%\home") else (set "JWMCP_HOME=%USERPROFILE%\.jwmcp")
echo data   : JWMCP_HOME=%JWMCP_HOME%
echo bridge : JWMCP_EXCHANGE=%JWMCP_EXCHANGE%
setx JWMCP_HOME "%JWMCP_HOME%" >nul
setx JWMCP_EXCHANGE "%JWMCP_EXCHANGE%" >nul

echo running tests ...
"%VPY%" -m pytest -q "%ROOT%\tests" || echo (some tests failed - see above)

echo preparing the 外部変形 batch files in %JWMCP_EXCHANGE%\gaihen ...
"%VPY%" -c "from jwmcp import bridge; r=bridge.setup(); print('\n'.join(r['bat_files']))"

set "VPYJ=%VPY:\=\\%"
set "HOMEJ=%JWMCP_HOME:\=\\%"
set "EXJ=%JWMCP_EXCHANGE:\=\\%"
echo.
echo === MCP server registration
where claude >nul 2>&1 && (
  claude mcp add jwmcp --scope user --env JWMCP_HOME="%JWMCP_HOME%" --env JWMCP_EXCHANGE="%JWMCP_EXCHANGE%" -- "%VPY%" -m jwmcp && echo registered with Claude Code: jwmcp
)
echo For Antigravity ^(Manage MCP servers ^> View raw config^) or Claude Desktop, add this to mcp_config.json:
echo {"mcpServers": {"jwmcp": {"command": "%VPYJ%", "args": ["-m", "jwmcp"], "env": {"JWMCP_HOME": "%HOMEJ%", "JWMCP_EXCHANGE": "%EXJ%"}}}}
echo.
echo === done.  settings UI: scripts\windows\settings.bat   Jw_cad: 外部変形 ^> %JWMCP_EXCHANGE%\gaihen\JWMCP_send.bat
pause
