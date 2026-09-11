"""File-queue bridge between Jw_cad (Windows, 外部変形 .bat) and this MCP server.

Jw_cad has no external API. Its extension point is 外部変形: the user picks a .bat from inside
Jw_cad, Jw_cad writes JWC_TEMP.TXT, runs the .bat, then reads JWC_TEMP.TXT back. The .bat files
generated here copy JWC_TEMP.TXT into `<exchange>/inbox/<job>.txt`, wait for
`<exchange>/outbox/<job>.txt` to appear, and copy that back. The exchange folder can be a
Google Drive / Dropbox / SMB folder, so the Mac running the MCP server and the Windows PC
running Jw_cad need no network configuration at all.

Safety: while waiting, JWC_TEMP.TXT is overwritten with just `hq`, so if the .bat times out or
is killed Jw_cad reports 「未実行」 and changes nothing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import jwc_temp

DEFAULT_WAIT = 900
IMPORT_NAME = "IMPORT"


def default_exchange() -> Path:
    return Path(os.environ.get("JWMCP_EXCHANGE", Path.home() / "JW_MCP_Exchange")).expanduser()


def _dirs(ex: Path) -> dict[str, Path]:
    d = {k: ex / k for k in ("inbox", "outbox", "done")}
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


_BAT_COMMON = r"""@echo off
setlocal enabledelayedexpansion
set "EX={win_exchange}"
set "WAIT={wait}"
set "KIND={kind}"
for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%a"
if "%TS%"=="" set "TS=%RANDOM%%RANDOM%"
set "JOB=%TS%_%KIND%"
if not exist "%EX%\inbox" mkdir "%EX%\inbox"
if not exist "%EX%\outbox" mkdir "%EX%\outbox"
"""

_BAT_SEND_BODY = r"""copy /y JWC_TEMP.TXT "%EX%\inbox\%JOB%.tmp" >nul
ren "%EX%\inbox\%JOB%.tmp" "%JOB%.txt"
echo hq> JWC_TEMP.TXT
echo [JW MCP] job %JOB% sent. waiting for Claude (max %WAIT% s)...
set /a N=0
:wait
if exist "%EX%\outbox\%JOB%.txt" goto got
set /a N+=1
if !N! GEQ %WAIT% goto timeout
timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul
goto wait
:got
copy /y "%EX%\outbox\%JOB%.txt" JWC_TEMP.TXT >nul
del /q "%EX%\outbox\%JOB%.txt"
echo [JW MCP] response received.
exit /b 0
:timeout
echo [JW MCP] timeout - nothing changed.
exit /b 0
"""

_BAT_IMPORT_BODY = r"""copy /y JWC_TEMP.TXT "%EX%\inbox\%JOB%.tmp" >nul
ren "%EX%\inbox\%JOB%.tmp" "%JOB%.txt"
echo hq> JWC_TEMP.TXT
echo [JW MCP] waiting for a prepared drawing from Claude (max %WAIT% s)...
set /a N=0
:wait
if exist "%EX%\outbox\{import}.txt" goto got
if exist "%EX%\outbox\%JOB%.txt" goto gotjob
set /a N+=1
if !N! GEQ %WAIT% goto timeout
timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul
goto wait
:got
copy /y "%EX%\outbox\{import}.txt" JWC_TEMP.TXT >nul
del /q "%EX%\outbox\{import}.txt"
echo [JW MCP] drawing imported.
exit /b 0
:gotjob
copy /y "%EX%\outbox\%JOB%.txt" JWC_TEMP.TXT >nul
del /q "%EX%\outbox\%JOB%.txt"
echo [JW MCP] drawing imported.
exit /b 0
:timeout
echo [JW MCP] timeout - nothing changed.
exit /b 0
"""

BATS = {
    "JWMCP_send.bat": {
        "kind": "send",
        "header": ["REM AI連携: 選択図形をClaudeへ送り、応答を取り込む (JW MCP)", "REM #jww", "REM #cd", "REM #hf", "REM #h2",
                   "REM #hcClaudeに渡す図形を範囲選択（文字を含めるなら終点を右クリック）", "REM #zz", "REM #zc", "REM #gn", "REM #zs", "REM #e"],
        "body": _BAT_SEND_BODY,
    },
    "JWMCP_send_all.bat": {
        "kind": "sendall",
        "header": ["REM AI連携: 図面全体をClaudeへ送る (JW MCP)", "REM #jww", "REM #cd", "REM #hf", "REM #h4", "REM #g1",
                   "REM #zz", "REM #zc", "REM #gn", "REM #zs", "REM #e"],
        "body": _BAT_SEND_BODY,
    },
    "JWMCP_import.bat": {
        "kind": "import",
        "header": ["REM AI連携: Claudeが用意した図形を取り込む (JW MCP)", "REM #jww", "REM #cd", "REM #hf", "REM #h0",
                   "REM #gn", "REM #zs", "REM #e"],
        "body": _BAT_IMPORT_BODY,
    },
}


def setup(exchange: Path | None = None, win_exchange: str | None = None, wait: int = DEFAULT_WAIT) -> dict:
    ex = (exchange or default_exchange()).expanduser()
    _dirs(ex)
    bat_dir = ex / "gaihen"
    bat_dir.mkdir(exist_ok=True)
    win = win_exchange or str(ex)
    written = []
    for name, spec in BATS.items():
        body = _BAT_COMMON.format(win_exchange=win, wait=int(wait), kind=spec["kind"])
        body += spec["body"].replace("{import}", IMPORT_NAME)
        text = "\r\n".join(spec["header"]) + "\r\n" + body.replace("\n", "\r\n")
        (bat_dir / name).write_bytes(text.encode("cp932", errors="replace"))
        written.append(str(bat_dir / name))
    readme = (
        "JW MCP 外部変形ブリッジ\r\n"
        f"1. このフォルダ全体（{ex.name}）を Windows 側から見える場所に置く（Google Drive 等）。\r\n"
        f"   .bat 内の EX= が Windows 側のパス（{win}）になっていることを確認。\r\n"
        "2. gaihen フォルダ内の .bat を Jw_cad の 外部変形 から選ぶ。\r\n"
        "   JWMCP_send.bat      : 範囲選択した図形を Claude へ送り、応答を取り込む\r\n"
        "   JWMCP_send_all.bat  : 図面全体を Claude へ送る\r\n"
        "   JWMCP_import.bat    : Claude が用意した図形（outbox/IMPORT.txt）を取り込む\r\n"
        "3. Mac 側の MCP サーバーは inbox/ を監視し、outbox/ に応答を書く。\r\n"
    )
    (ex / "README.txt").write_bytes(readme.encode("cp932", errors="replace"))
    cfg = {"exchange": str(ex), "win_exchange": win, "wait": int(wait), "created": time.time()}
    (ex / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**cfg, "bat_files": written, "readme": str(ex / "README.txt")}


def list_jobs(exchange: Path | None = None) -> list[dict]:
    ex = (exchange or default_exchange()).expanduser()
    d = _dirs(ex)
    jobs = []
    for p in sorted(d["inbox"].glob("*.txt")):
        st = p.stat()
        job = {"id": p.stem, "kind": p.stem.rsplit("_", 1)[-1], "received": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
               "age_s": int(time.time() - st.st_mtime), "size_bytes": st.st_size,
               "answered": (d["outbox"] / p.name).exists()}
        try:
            j = jwc_temp.parse(jwc_temp.decode(p.read_bytes()))
            from collections import Counter
            job["entity_count"] = len(j.entities)
            job["by_type"] = dict(Counter(e["type"] for e in j.entities))
            job["file"] = j.file
            job["selection_range"] = j.hn
            job["points"] = {k: [v["x"], v["y"]] for k, v in j.points.items()}
        except Exception as exc:  # pragma: no cover
            job["parse_error"] = str(exc)
        jobs.append(job)
    return jobs


def job_path(exchange: Path | None, job_id: str) -> Path:
    ex = (exchange or default_exchange()).expanduser()
    d = _dirs(ex)
    p = d["inbox"] / f"{job_id}.txt"
    if not p.exists():
        q = d["done"] / f"{job_id}.txt"
        if q.exists():
            return q
        raise FileNotFoundError(f"job {job_id} not found in {d['inbox']}")
    return p


def read_job(exchange: Path | None, job_id: str) -> jwc_temp.JwcTemp:
    return jwc_temp.parse(jwc_temp.decode(job_path(exchange, job_id).read_bytes()))


def _atomic_write(target: Path, data: bytes) -> None:
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def respond(exchange: Path | None, job_id: str, text: str, *, keep_job: bool = False) -> dict:
    ex = (exchange or default_exchange()).expanduser()
    d = _dirs(ex)
    src = d["inbox"] / f"{job_id}.txt"
    if not src.exists():
        raise FileNotFoundError(f"job {job_id} is not pending (already answered or unknown)")
    target = d["outbox"] / f"{job_id}.txt"
    _atomic_write(target, jwc_temp.encode(text))
    if not keep_job:
        src.replace(d["done"] / src.name)
    return {"job": job_id, "outbox": str(target), "bytes": target.stat().st_size, "lines": text.count("\n")}


def cancel(exchange: Path | None, job_id: str, reason: str = "") -> dict:
    # A file that still contains 'hq' makes Jw_cad report 未実行 and change nothing.
    text = "hq\r\n" + (f"h#{reason}\r\n" if reason else "")
    return respond(exchange, job_id, text)


def prepare_import(exchange: Path | None, text: str) -> dict:
    ex = (exchange or default_exchange()).expanduser()
    d = _dirs(ex)
    target = d["outbox"] / f"{IMPORT_NAME}.txt"
    _atomic_write(target, jwc_temp.encode(text))
    return {"outbox": str(target), "bytes": target.stat().st_size,
            "next_step": "Jw_cad で 外部変形 > JWMCP_import.bat を実行すると取り込まれます"}


def status(exchange: Path | None = None) -> dict:
    ex = (exchange or default_exchange()).expanduser()
    d = _dirs(ex)
    cfg = {}
    if (ex / "config.json").exists():
        cfg = json.loads((ex / "config.json").read_text(encoding="utf-8"))
    return {"exchange": str(ex), "config": cfg, "bats_present": sorted(p.name for p in (ex / "gaihen").glob("*.bat")) if (ex / "gaihen").exists() else [],
            "pending_jobs": len(list(d["inbox"].glob("*.txt"))), "unconsumed_responses": sorted(p.name for p in d["outbox"].glob("*.txt")),
            "done_jobs": len(list(d["done"].glob("*.txt")))}
