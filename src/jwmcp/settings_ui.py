"""Local settings UI:  python -m jwmcp settings  →  http://127.0.0.1:8765

Edits profiles (company / project standards: layer groups, layers, scales, per-type defaults, pen colours,
text types, title-block frame) and per-drawing overrides, imports .jwf / template .jww, previews the frame.
Runs on Starlette + uvicorn which ship with the mcp SDK; no extra dependency.
"""
from __future__ import annotations

import json
import tempfile
import time
import webbrowser
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import profiles
from .model import PAPER_SIZES_MM, Drawing, ModelError, jwmcp_home
from .presets import PRESETS, preset_names
from .render import render


def _ok(data) -> JSONResponse:
    return JSONResponse(data)


def _err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


async def state(_: Request):
    from . import linetype
    return _ok({"profiles": profiles.list_profiles(), "drawings": Drawing.list_names(), "presets": preset_names(),
                "papers": list(PAPER_SIZES_MM), "home": str(jwmcp_home()),
                "linetype_defaults": linetype.DEFAULTS, "linetype_names": linetype.NAMES})


async def profile_get(req: Request):
    try:
        return _ok(profiles.load_profile(req.path_params["name"]))
    except ModelError as exc:
        return _err(str(exc), 404)


async def profile_put(req: Request):
    name = req.path_params["name"]
    try:
        body = await req.json()
        body["name"] = name
        profiles.save_profile(body)
        return _ok({"saved": name})
    except (ModelError, ValueError) as exc:
        return _err(str(exc))


async def profile_delete(req: Request):
    return _ok({"deleted": profiles.delete_profile(req.path_params["name"])})


async def profile_from_preset(req: Request):
    name = req.path_params["name"]
    body = await req.json()
    try:
        return _ok(profiles.update_profile(name, base_preset=body.get("preset")))
    except ModelError as exc:
        return _err(str(exc))


async def _save_upload(req: Request, suffix: str) -> tuple[Path | None, dict]:
    form = await req.form()
    f = form.get("file")
    if f is None:
        return None, dict(form)
    tmp = Path(tempfile.mkdtemp(prefix="jwmcp_")) / (Path(f.filename).name or f"upload{suffix}")
    tmp.write_bytes(await f.read())
    return tmp, dict(form)


async def profile_import_jwf(req: Request):
    name = req.path_params["name"]
    path, form = await _save_upload(req, ".jwf")
    src = str(path) if path else form.get("path")
    if not src:
        return _err("file or path required")
    base = None
    try:
        base = profiles.load_profile(name)
    except ModelError:
        pass
    try:
        p = profiles.from_jwf(src, name, base)
    except Exception as exc:
        return _err(f"jwf import failed: {exc}")
    return _ok(p)


async def profile_import_jww(req: Request):
    name = req.path_params["name"]
    path, form = await _save_upload(req, ".jww")
    src = str(path) if path else form.get("path")
    if not src:
        return _err("file or path required")
    frame_lg = form.get("frame_lg")
    frame_lg = int(str(frame_lg), 16) if frame_lg not in (None, "", "none") else None
    frame_texts = str(form.get("frame_texts") or "all")
    base = None
    try:
        base = profiles.load_profile(name)
    except ModelError:
        pass
    try:
        p = profiles.from_jww(src, name, base, frame_lg=frame_lg, frame_texts=frame_texts)
    except Exception as exc:
        return _err(f"jww import failed: {exc}")
    return _ok(p)


async def profile_logo(req: Request):
    name = req.path_params["name"]
    path, form = await _save_upload(req, ".png")
    src = str(path) if path else form.get("path")
    if not src:
        return _err("file or path required")
    try:
        thr = form.get("threshold")
        r = profiles.set_logo(name, src, float(form.get("width_mm") or 40),
                              threshold=int(thr) if thr not in (None, "", "auto") else None,
                              invert=str(form.get("invert", "")).lower() in ("1", "true", "on"),
                              simplify_px=float(form.get("simplify_px") or 1.0), lc=int(form.get("lc") or 2))
        return _ok(r)
    except (ModelError, RuntimeError, ValueError) as exc:
        return _err(str(exc))


async def profile_logo_delete(req: Request):
    try:
        return _ok(profiles.clear_logo(req.path_params["name"]))
    except ModelError as exc:
        return _err(str(exc), 404)


async def profile_export_jwf(req: Request):
    from .jwf import write_jwf
    name = req.path_params["name"]
    try:
        p = profiles.load_profile(name)
    except ModelError as exc:
        return _err(str(exc), 404)
    out = jwmcp_home() / "exports" / f"{name}.jwf"
    r = write_jwf(p, str(out))
    if req.query_params.get("download"):
        return FileResponse(str(out), media_type="application/octet-stream", filename=f"{name}.jwf")
    return _ok(r)


async def profile_linetype_test(req: Request):
    from . import bridge, jwc_temp, linetype
    name = req.path_params["name"]
    try:
        body = await req.json()
    except Exception:
        body = {}
    dpi = int(body.get("dpi") or 600)
    try:
        prof = profiles.load_profile(name)
    except ModelError as exc:
        return _err(str(exc), 404)
    lts = {**linetype.DEFAULTS, **(prof.get("linetypes") or {})}
    d = Drawing(f"線種テスト_{name}", scale=1, paper="A4")
    d.add(linetype.test_sheet_entities(lts, dpi))
    d.save()
    text = jwc_temp.serialize(d.entities, scale_for=lambda e: 1.0, paper_coords=True,
                              notice="線種テスト: 印刷倍率100%で印刷し、目盛と比べてください")
    return _ok({"drawing": d.name, **bridge.prepare_import(None, text)})


async def preview_frame(req: Request):
    name = req.path_params["name"]
    paper = req.query_params.get("paper", "A3")
    scale = float(req.query_params.get("scale", "50"))
    try:
        prof = profiles.load_profile(name)
        fields = {k[2:]: v for k, v in req.query_params.items() if k.startswith("f_") and v}
        fe = profiles.frame_entity(prof, paper, fields or {"title": "図面名サンプル", "no": "01", "scale": f"S=1:{scale:g}"})
        d = Drawing("_preview", scale=scale, paper=paper)
        d.group_scales[int(fe["lg"])] = 1.0
        d.add([fe])
        W, H = PAPER_SIZES_MM[paper]
        ents = [{"type": "rect", "x": -W / 2 * scale, "y": -H / 2 * scale, "w": W * scale, "h": H * scale, "lc": 9, "lt": 3}] + d.unified_entities()
        out = jwmcp_home() / "previews" / f"ui_frame_{name}_{paper}.png"
        render(ents, str(out), scale_for=lambda e: scale, width_px=1400)
        return FileResponse(str(out), media_type="image/png", headers={"Cache-Control": "no-store"})
    except (ModelError, KeyError, ValueError) as exc:
        return _err(str(exc))


async def preview_drawing(req: Request):
    name = req.path_params["name"]
    try:
        d = Drawing.load(name)
        W, H = PAPER_SIZES_MM[d.paper]
        k = d.main_scale
        ents = [{"type": "rect", "x": -W / 2 * k, "y": -H / 2 * k, "w": W * k, "h": H * k, "lc": 9, "lt": 3}] + d.unified_entities()
        out = jwmcp_home() / "previews" / f"ui_drawing_{name}.png"
        render(ents, str(out), scale_for=d.scale_for_unified, width_px=1400)
        return FileResponse(str(out), media_type="image/png", headers={"Cache-Control": "no-store"})
    except ModelError as exc:
        return _err(str(exc))


async def drawing_get(req: Request):
    try:
        d = Drawing.load(req.path_params["name"])
    except ModelError as exc:
        return _err(str(exc), 404)
    return _ok({**d.summary(), "group_scales_all": {f"{k:X}": v for k, v in d.group_scales.items()},
                "group_names_all": {f"{k:X}": v for k, v in d.group_names.items()}, "layer_names": d.layer_names,
                "profile": d.profile, "main_scale": d.main_scale})


async def drawing_put(req: Request):
    name = req.path_params["name"]
    try:
        d = Drawing.load(name)
        body = await req.json()
        if body.get("paper"):
            if body["paper"] not in PAPER_SIZES_MM:
                return _err("bad paper")
            d.paper = body["paper"]
        if body.get("description") is not None:
            d.description = body["description"]
        if body.get("main_scale"):
            d.main_scale = float(body["main_scale"])
        for k, v in (body.get("group_names") or {}).items():
            d.group_names[int(k, 16)] = v
        for k, v in (body.get("group_scales") or {}).items():
            d.group_scales[int(k, 16)] = float(v)
        if body.get("layer_names") is not None:
            d.layer_names = {k: v for k, v in body["layer_names"].items() if v}
        d.save()
        return _ok({"saved": name})
    except (ModelError, ValueError) as exc:
        return _err(str(exc))


async def drawing_apply_profile(req: Request):
    name = req.path_params["name"]
    body = await req.json()
    try:
        d = Drawing.load(name)
        prof = profiles.load_profile(body["profile"])
        profiles.apply_to_drawing(prof, d)
        if body.get("frame"):
            fe = profiles.frame_entity(prof, d.paper, body.get("fields"))
            d.entities = [e for e in d.entities if e["type"] != "frame"]
            d.group_scales[int(fe["lg"])] = 1.0
            d.add([fe])
        d.save()
        return _ok({"applied": body["profile"]})
    except (ModelError, KeyError) as exc:
        return _err(str(exc))


async def drawing_save_as_profile(req: Request):
    name = req.path_params["name"]
    body = await req.json()
    try:
        d = Drawing.load(name)
        pname = body["profile"]
        prof = profiles.update_profile(pname, paper=d.paper, scale=d.main_scale,
                                       group_names={f"{k:X}": v for k, v in d.group_names.items()},
                                       group_scales={f"{k:X}": v for k, v in d.group_scales.items() if v != d.main_scale or k in d.group_names},
                                       layer_names=dict(d.layer_names))
        return _ok(prof)
    except (ModelError, KeyError) as exc:
        return _err(str(exc))


async def index(_: Request):
    return HTMLResponse(HTML)


routes = [
    Route("/", index),
    Route("/api/state", state),
    Route("/api/profile/{name}", profile_get, methods=["GET"]),
    Route("/api/profile/{name}", profile_put, methods=["PUT"]),
    Route("/api/profile/{name}", profile_delete, methods=["DELETE"]),
    Route("/api/profile/{name}/from_preset", profile_from_preset, methods=["POST"]),
    Route("/api/profile/{name}/import_jwf", profile_import_jwf, methods=["POST"]),
    Route("/api/profile/{name}/import_jww", profile_import_jww, methods=["POST"]),
    Route("/api/profile/{name}/export_jwf", profile_export_jwf),
    Route("/api/profile/{name}/linetype_test", profile_linetype_test, methods=["POST"]),
    Route("/api/profile/{name}/logo", profile_logo, methods=["POST"]),
    Route("/api/profile/{name}/logo", profile_logo_delete, methods=["DELETE"]),
    Route("/api/preview/frame/{name}", preview_frame),
    Route("/api/preview/drawing/{name}", preview_drawing),
    Route("/api/drawing/{name}", drawing_get, methods=["GET"]),
    Route("/api/drawing/{name}", drawing_put, methods=["PUT"]),
    Route("/api/drawing/{name}/apply_profile", drawing_apply_profile, methods=["POST"]),
    Route("/api/drawing/{name}/save_as_profile", drawing_save_as_profile, methods=["POST"]),
]

app = Starlette(routes=routes)


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn
    url = f"http://{host}:{port}/"
    print(f"jwmcp settings UI: {url}   (Ctrl+C で終了)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Single-file UI
# ---------------------------------------------------------------------------

HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>jwmcp 設定</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#d9dde3;--ink:#1d2430;--mute:#6b7380;--acc:#0f6fbf;--acc2:#e8f1fb;--warn:#b54708}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,"Hiragino Sans","Yu Gothic UI",Meiryo,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;gap:12px;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:16px;margin:0 8px 0 0}header .sp{flex:1}
select,input[type=text],input[type=number],textarea{font:inherit;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:#fff}
input[type=number]{width:72px}button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
button.p{background:var(--acc);color:#fff;border-color:var(--acc)}button.w{color:var(--warn)}button:hover{filter:brightness(.96)}
main{display:grid;grid-template-columns:220px 1fr;gap:16px;padding:16px;max-width:1500px}
nav{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px}
nav a{display:block;padding:8px 10px;border-radius:6px;color:var(--ink);text-decoration:none;cursor:pointer}nav a.on{background:var(--acc2);color:var(--acc);font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;display:none}section.on{display:block}
h2{font-size:15px;margin:0 0 10px}h3{font-size:14px;margin:16px 0 6px;color:var(--mute)}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:middle}th{color:var(--mute);font-weight:600;font-size:12px}
td input[type=text]{width:100%}.grid16{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}.grid16 input{width:100%}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0}.hint{color:var(--mute);font-size:12px}
.drop{border:2px dashed var(--line);border-radius:10px;padding:14px;text-align:center;color:var(--mute);margin:8px 0}.drop.hover{border-color:var(--acc);background:var(--acc2)}
img.prev{max-width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}
.chip{display:inline-block;background:var(--acc2);color:var(--acc);border-radius:12px;padding:1px 8px;font-size:12px;margin-left:6px}
#toast{position:fixed;bottom:16px;right:16px;background:#1d2430;color:#fff;padding:10px 14px;border-radius:8px;opacity:0;transition:.2s}#toast.on{opacity:1}
.sw{width:22px;height:22px;border-radius:4px;border:1px solid var(--line);display:inline-block;vertical-align:middle}
textarea.json{width:100%;height:60vh;font:12px/1.4 ui-monospace,Menlo,monospace}
details summary{cursor:pointer;color:var(--mute)}
.ltcells{display:grid;grid-template-columns:repeat(32,11px);gap:1px;margin-bottom:3px}
.ltc{width:11px;height:16px;background:#e6e9ee;cursor:pointer;border-bottom:3px solid transparent;box-sizing:border-box}
.ltc.on{background:#1d2430}.ltc.u{border-bottom-color:#0f6fbf}
code.ltpat{font:11px ui-monospace,Menlo,Consolas,monospace;white-space:pre;color:#6b7380}
#ltTable td{vertical-align:top}#ltTable input[type=number]{width:56px}
</style></head><body>
<header><h1>jwmcp 設定</h1>
 <label>プロファイル <select id="profSel"></select></label>
 <button id="newProf">＋ 新規</button><button id="dupProf">複製</button><button id="delProf" class="w">削除</button>
 <span class="sp"></span><span class="hint" id="homeHint"></span><button class="p" id="save">保存</button></header>
<main>
<nav>
 <a data-t="basic" class="on">基本</a><a data-t="layers">レイヤ構成</a><a data-t="defaults">部品の既定</a><a data-t="frame">図面枠</a>
 <a data-t="pens">線色・文字種</a><a data-t="linetypes">線種</a><a data-t="drawings">図面ごとの設定</a><a data-t="json">JSON</a>
</nav>
<div>
<section id="t-basic" class="on"><h2>基本</h2>
 <div class="row"><label>会社名 <input type="text" id="company" style="width:260px"></label><label>説明 <input type="text" id="desc" style="width:360px"></label></div>
 <div class="row"><label>既定の用紙 <select id="paper"></select></label><label>既定の縮尺 1/ <input type="number" id="scale" min="1"></label>
 <label>フォント <input type="text" id="font" style="width:200px"></label></div>
 <h3>手持ちのファイルから取り込む</h3>
 <div class="row"><div class="drop" id="dropJwf" style="flex:1">jw_win.jwf（環境設定）をここへドロップ → 線色・印刷線幅・文字種・既定縮尺</div>
 <div class="drop" id="dropJww" style="flex:1">テンプレートの .jww をここへドロップ → レイヤ構成 ＋ 図面枠<br>
  <label class="hint">図面枠のグループ <select id="frameLgSel"><option value="none">（枠は取り込まない）</option></select></label>
  <label class="hint">文字 <select id="frameTextsSel"><option value="all">すべて残す（会社名など固定文字も）</option><option value="labels">ラベル（No./Title…）だけ残す</option></select></label></div></div>
 <p class="hint">Jw_cad で描いた枠をそのまま保存するなら: Jw_cad で枠を範囲選択 → 外部変形 JWMCP_send.bat → AI に「このジョブを図面枠として保存して」（profile_frame_from_job）。値の欄は空、会社名などの固定文字は欲しい大きさで描いておく。</p>
 <div class="row"><label>プリセットから初期化 <select id="presetSel"></select></label><button id="applyPreset">レイヤ構成と既定を読み込む</button>
 <span class="hint">既存の設定に上書き追加します</span></div>
 <h3>Jw_cad へ反映する</h3>
 <div class="row"><a id="exportJwf" href="#" class="hint"><button>Jw_cad 用 環境設定ファイル（.jwf）を書き出す</button></a>
 <span class="hint">レイヤグループ名・レイヤ名・縮尺・線色・文字種を Jw_cad 側に持ち込む。Jw_cad で 設定 → 環境設定ファイル → 読込。取り込み元の .jwf のその他の設定はそのまま引き継ぎます</span></div>
</section>
<section id="t-layers"><h2>レイヤ構成（16 グループ × 16 レイヤ）</h2>
 <p class="hint">グループ名・縮尺（1/N）・レイヤ名。図面枠のグループは縮尺 1 にします。空欄は Jw_cad の既定のままです。</p>
 <div id="layerEditor"></div></section>
<section id="t-defaults"><h2>部品の既定レイヤ・線色</h2>
 <p class="hint">AI が壁・柱・通り芯などを置くときの既定値（Jw_cad のレイヤグループ 0〜F、レイヤ 0〜F、線色 1〜9、線種 1〜9）。空欄は「指定なし」。図面側や指示で上書きできます。</p>
 <table id="defTable"><thead><tr><th>部品</th><th>グループ</th><th>レイヤ</th><th>線色</th><th>線種</th><th>その他</th></tr></thead><tbody></tbody></table>
 <h3>配管系統 → グループ / レイヤ</h3><table id="pipeTable"><thead><tr><th>系統</th><th>グループ</th><th>レイヤ</th></tr></thead><tbody></tbody></table></section>
<section id="t-frame"><h2>図面枠（S=1:1 のグループに配置）</h2>
 <div class="row"><label>方式 <select id="frStyle"><option value="strip">内蔵の表題帯</option><option value="template">テンプレート（.jww から取込）</option></select></label>
 <label>配置グループ（縮尺 1/1 にする） <input type="text" id="frLg" style="width:40px"></label>
 <label>左右余白 <input type="number" id="frMargin" step="0.5"></label><label>下端から <input type="number" id="frBottom" step="0.5"></label>
 <label>高さ <input type="number" id="frHeight" step="0.5"></label><label><input type="checkbox" id="frBorder"> 用紙外枠も描く</label></div>
 <div class="row"><label>会社名（ロゴ欄） <input type="text" id="frCompany" style="width:220px"></label>
 <label>会社名の文字高さ mm <input type="number" id="frCompanyH" step="0.5"></label>
 <label>タイトルの文字高さ mm <input type="number" id="frTitleH" step="0.5"></label>
 <label>値の文字高さ mm <input type="number" id="frValueH" step="0.5"></label>
 <label>ラベルの文字高さ mm <input type="number" id="frLabelH" step="0.5"></label></div>
 <div class="row"><span id="frTplInfo" class="hint"></span></div>
 <h3>ロゴ（ビットマップ → 線データ）</h3>
 <div class="row"><div class="drop" id="dropLogo" style="flex:1">ロゴ画像（PNG / BMP / JPG）をここへドロップ → 輪郭を線に変換してロゴ欄に入れる</div>
  <div><label>ロゴ幅 mm <input type="number" id="logoW" value="40" step="1"></label><br>
  <label>しきい値 <input type="text" id="logoThr" value="auto" style="width:60px"></label>
  <label><input type="checkbox" id="logoInv"> 白抜き（明るい線）</label><br>
  <label>簡略化 px <input type="number" id="logoSimp" value="1" step="0.5"></label>
  <button id="logoDel">ロゴを外す</button></div></div>
 <div class="row"><span id="logoInfo" class="hint"></span></div>
 <div class="row"><label>プレビュー用紙 <select id="frPaper"></select></label><label>縮尺 1/ <input type="number" id="frScale" value="50"></label><button id="frPrev">プレビュー更新</button>
 <span class="hint">保存してからプレビューが反映されます</span></div>
 <img class="prev" id="frImg" alt=""></section>
<section id="t-pens"><h2>線色・文字種</h2>
 <div class="row"><table style="width:auto" id="penTable"><thead><tr><th>線色 No.</th><th>画面色</th><th>RGB</th><th>印刷線幅</th><th>実点半径 mm</th></tr></thead><tbody></tbody></table>
 <table style="width:auto;margin-left:24px" id="ttTable"><thead><tr><th>文字種</th><th>幅 mm</th><th>高さ mm</th><th>間隔 mm</th><th>線色 No.</th></tr></thead><tbody></tbody></table></div>
 <p class="hint">jw_win.jwf から取り込むと Jw_cad と同じ値になります。プレビューの色と、AI が置く文字の寸法に使われます。</p></section>
<section id="t-linetypes"><h2>線種（点線・鎖線が印刷でどう見えるか）</h2>
 <p class="hint">Jw_cad の 基本設定「線種」タブと同じ値です。マス目をクリックすると線（黒）と空き（灰）が切り替わります。青い下線は「1 パターン」で繰り返す範囲。
 右側は印刷したときの実寸（mm）で描いた見本と、1 区切りごとの長さです。</p>
 <div class="row"><label>印刷の 1 ドット <select id="ltDpi"><option value="600">600dpi（1 ドット 0.042 mm）</option><option value="300">300dpi（1 ドット 0.085 mm）</option></select></label>
 <label>印刷倍率 <select id="ltScale"><option value="1">100%</option><option value="0.707">71%（A2 を A3 に）</option><option value="0.5">50%（A1 を A3 に）</option></select></label>
 <label>見本の拡大 <input type="range" id="ltZoom" min="3" max="16" value="8"> <span id="ltZoomV" class="hint"></span></label>
 <button id="ltReset">Jw_cad の初期値に戻す</button><button id="ltTest">線種テスト用の図形を作る</button></div>
 <p class="hint">印刷の 1 ドットが 300dpi と 600dpi のどちらで数えられるかは Jw_cad のヘルプに書かれていません。「線種テスト用の図形」を Jw_cad に取り込み、印刷倍率 100% で 1 回印刷して定規と比べると確実です（Jw_cad の設定「プリンタ dpi」は .jwf に保存されないため、ここで選びます）。</p>
 <div style="overflow-x:auto"><table id="ltTable"><thead><tr><th>線種</th><th>パターン（32 文字）</th><th>1 パターン</th><th>画面ピッチ</th><th>印刷ピッチ</th><th>印刷したときの見え方（実寸）</th></tr></thead><tbody></tbody></table></div>
</section>
<section id="t-drawings"><h2>図面ごとの設定</h2>
 <div class="row"><label>図面 <select id="drwSel"></select></label><button id="drwLoad">読み込む</button>
 <button id="drwApply">このプロファイルを適用</button><label><input type="checkbox" id="drwApplyFrame"> 図面枠も入れ直す</label>
 <button id="drwSaveProf">この図面の構成を新しいプロファイルに保存</button><button class="p" id="drwSave">図面を保存</button></div>
 <div class="row"><label>用紙 <select id="drwPaper"></select></label><label>主縮尺 1/ <input type="number" id="drwScale"></label><label>説明 <input type="text" id="drwDesc" style="width:320px"></label>
 <span class="hint" id="drwInfo"></span></div>
 <div id="drwLayerEditor"></div>
 <img class="prev" id="drwImg" alt="" style="margin-top:10px"></section>
<section id="t-json"><h2>JSON（そのまま編集可）</h2><textarea class="json" id="jsonArea"></textarea>
 <div class="row"><button id="jsonApply">JSON を画面に反映</button><span class="hint">このファイルを渡せば同じ設定を共有できます</span></div></section>
</div></main>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);const $$=s=>[...document.querySelectorAll(s)];
const HEX='0123456789ABCDEF'.split('');
const TYPES=[['wall','壁'],['structure_wall','躯体壁(structural)'],['column','柱'],['grid','通り芯'],['room','室名'],['text','文字'],['dimension','寸法'],['opening','建具'],['equipment','機器'],['pipe','配管'],['line','線']];
const PIPES=['給水','給湯','排水','汚水','雑排水','通気','ガス','冷媒','ドレン','ダクト','給気','排気','換気','消火'];
const LC_NAMES={1:'1 水色',2:'2 黒',3:'3 緑',4:'4 黄',5:'5 紫',6:'6 青',7:'7 深緑(灰)',8:'8 赤',9:'9 補助線色'};
const LT_NAMES={1:'1 実線',2:'2 点線1',3:'3 点線2',4:'4 点線3',5:'5 一点鎖1',6:'6 一点鎖2',7:'7 二点鎖1',8:'8 二点鎖2',9:'9 補助線種'};
const selOpts=(names,val)=>`<option value="">（指定なし）</option>`+Object.entries(names).map(([k,v])=>`<option value="${k}" ${String(val)===k?'selected':''}>${v}</option>`).join('');
const selLC=(attr,val)=>`<select data-d="${attr}">${selOpts(LC_NAMES,val)}</select>`;
const selLT=(attr,val)=>`<select data-d="${attr}">${selOpts(LT_NAMES,val)}</select>`;
const selLG=(attr,val)=>`<select data-d="${attr}"><option value="">（指定なし）</option>${HEX.map(h=>`<option value="${h}" ${val!==undefined&&val!==''&&Number(val).toString(16).toUpperCase()===h?'selected':''}>${h}</option>`).join('')}</select>`;
const selLY=(attr,val)=>`<select data-d="${attr}"><option value="">（指定なし）</option>${HEX.map((h,i)=>`<option value="${i}" ${String(val)===String(i)?'selected':''}>${h}</option>`).join('')}</select>`;
let ST={profiles:[],drawings:[],presets:{},papers:[]},P=null,D=null;
const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('on');setTimeout(()=>t.classList.remove('on'),2200)};
const api=async(u,o={})=>{const r=await fetch(u,{headers:o.body&&!(o.body instanceof FormData)?{'Content-Type':'application/json'}:{},...o});const j=await r.json().catch(()=>({}));if(!r.ok||j.error){throw new Error(j.error||r.statusText)}return j};
$$('nav a').forEach(a=>a.onclick=()=>{$$('nav a').forEach(x=>x.classList.remove('on'));a.classList.add('on');$$('section').forEach(s=>s.classList.remove('on'));$('#t-'+a.dataset.t).classList.add('on');if(a.dataset.t==='json')$('#jsonArea').value=JSON.stringify(collect(),null,1)});
async function loadState(){ST=await api('/api/state');$('#homeHint').textContent=ST.home;LTD=ST.linetype_defaults||{};LTN=ST.linetype_names||{};
 const sel=$('#profSel');const cur=sel.value;sel.innerHTML=ST.profiles.map(p=>`<option value="${p.name}">${p.name}${p.company?' — '+p.company:''}</option>`).join('');
 if(cur&&ST.profiles.some(p=>p.name===cur))sel.value=cur;
 for(const id of ['#paper','#frPaper','#drwPaper']){$(id).innerHTML=ST.papers.map(p=>`<option>${p}</option>`).join('')}
 $('#presetSel').innerHTML=Object.entries(ST.presets).map(([k,v])=>`<option value="${k}">${k} — ${v}</option>`).join('');
 $('#drwSel').innerHTML=ST.drawings.map(d=>`<option>${d}</option>`).join('');
 $('#frameLgSel').innerHTML='<option value="none">（枠は取り込まない）</option>'+HEX.map(h=>`<option value="${h}">グループ ${h}</option>`).join('');
 if(sel.value)await loadProfile(sel.value);else newProfile();}
function newProfile(){const n=prompt('プロファイル名（英数字・日本語可）','mycompany');if(!n)return;P={name:n,group_names:{},group_scales:{},layer_names:{},defaults:{},frame:{lg:'F',style:'strip',fields:{}}};fill();}
async function loadProfile(n){P=await api('/api/profile/'+encodeURIComponent(n));fill();}
function layerEditor(root,gn,gs,ln,editableScale=true){root.innerHTML='';const t=document.createElement('table');t.innerHTML='<thead><tr><th style="width:60px">グループ</th><th>グループ名</th><th style="width:110px">縮尺 1/</th><th style="width:70px"></th></tr></thead>';const tb=document.createElement('tbody');
 HEX.forEach(h=>{const tr=document.createElement('tr');tr.innerHTML=`<td><b>${h}</b></td><td><input type="text" data-g="${h}" value="${gn[h]||''}"></td><td><input type="number" step="any" data-s="${h}" value="${gs[h]??''}" ${editableScale?'':'disabled'}></td><td><button data-x="${h}">レイヤ ▾</button></td>`;tb.appendChild(tr);
  const tr2=document.createElement('tr');tr2.style.display='none';tr2.innerHTML=`<td></td><td colspan="3"><div class="grid16">${HEX.map(l=>`<input type="text" placeholder="${h}-${l}" data-l="${h}-${l}" value="${ln[h+'-'+l]||''}">`).join('')}</div></td>`;tb.appendChild(tr2);
  tr.querySelector('button').onclick=()=>{tr2.style.display=tr2.style.display==='none'?'':'none'}});
 t.appendChild(tb);root.appendChild(t);}
function readLayerEditor(root){const gn={},gs={},ln={};root.querySelectorAll('[data-g]').forEach(i=>{if(i.value.trim())gn[i.dataset.g]=i.value.trim()});root.querySelectorAll('[data-s]').forEach(i=>{if(i.value!=='')gs[i.dataset.s]=parseFloat(i.value)});root.querySelectorAll('[data-l]').forEach(i=>{if(i.value.trim())ln[i.dataset.l]=i.value.trim()});return {gn,gs,ln}}
function fill(){$('#company').value=P.company||'';$('#desc').value=P.description||'';$('#paper').value=P.paper||'A3';$('#scale').value=P.scale||'';$('#font').value=P.font||'';
 layerEditor($('#layerEditor'),P.group_names||{},P.group_scales||{},P.layer_names||{});
 const tb=$('#defTable tbody');tb.innerHTML='';TYPES.forEach(([k,label])=>{const d=(P.defaults||{})[k]||{};
  const extra=k==='wall'?`壁厚 mm <input type="number" data-d="${k}.thickness" value="${d.thickness??''}"> 　壁芯を描く <input type="checkbox" data-d="${k}.core" ${d.core?'checked':''}> 壁芯レイヤ ${selLY(k+'.core_ly',d.core_ly)} 壁芯線色 ${selLC(k+'.core_lc',d.core_lc)}<br>建具の グループ ${selLG(k+'.opening_lg',d.opening_lg)} レイヤ ${selLY(k+'.opening_ly',d.opening_ly)} 線色 ${selLC(k+'.opening_lc',d.opening_lc)}`
   :k==='opening'?`枠外 mm <input type="number" data-d="${k}.frame" value="${d.frame??''}">`:'';
  tb.insertAdjacentHTML('beforeend',`<tr><td>${label}<span class="chip">${k}</span></td><td>${selLG(k+'.lg',d.lg)}</td><td>${selLY(k+'.ly',d.ly)}</td><td>${selLC(k+'.lc',d.lc)}</td><td>${selLT(k+'.lt',d.lt)}</td><td class="hint">${extra}</td></tr>`)});
 const pb=$('#pipeTable tbody');pb.innerHTML='';PIPES.forEach(s=>{const v=(P.pipe_layers||{})[s]||[];pb.insertAdjacentHTML('beforeend',`<tr><td>${s}</td><td><select data-p="${s}.0"><option value="">（指定なし）</option>${HEX.map(h=>`<option value="${h}" ${v[0]!==undefined&&Number(v[0]).toString(16).toUpperCase()===h?'selected':''}>${h}</option>`).join('')}</select></td><td><select data-p="${s}.1"><option value="">（指定なし）</option>${HEX.map((h,i)=>`<option value="${i}" ${String(v[1])===String(i)?'selected':''}>${h}</option>`).join('')}</select></td></tr>`)});
 const f=P.frame||{};$('#frStyle').value=f.style||'strip';$('#frLg').value=f.lg??'F';$('#frMargin').value=f.margin??16;$('#frBottom').value=f.bottom??11.5;$('#frHeight').value=f.height??19;$('#frBorder').checked=!!f.border;$('#frCompany').value=(f.fields||{}).company||'';
 $('#frCompanyH').value=f.company_height??5;$('#frTitleH').value=f.title_height??3;$('#frValueH').value=f.value_height??2.5;$('#frLabelH').value=f.label_height??2;
 $('#frTplInfo').textContent=P.frame_template?`テンプレート取込済: ${P.frame_template.paper} から ${P.frame_template.entities.length} 要素（元グループ ${P.frame_template.source_lg??'-'}, 1/${P.frame_template.source_scale??'-'}）`:'テンプレート未取込（基本タブで .jww をドロップ、または Jw_cad から外部変形で送って保存）';
 const lg=(P.frame||{}).logo;$('#logoInfo').textContent=lg?`ロゴ設定済: ${lg.source||''}（${lg.polylines.length} 図形 / ${lg.points||'-'} 点 / 幅 ${lg.width_mm} mm）。ロゴがあると会社名の文字は出しません`:'ロゴ未設定（会社名の文字を表示）';
 const pt=$('#penTable tbody');pt.innerHTML='';const DEF={1:[0,192,192],2:[0,0,0],3:[0,192,0],4:[192,192,0],5:[192,0,192],6:[0,0,255],7:[192,192,192],8:[255,0,128],9:[192,192,192]};
 for(let n=1;n<=9;n++){const rgb=((P.pen_colors||{})[n])||DEF[n];const hex='#'+rgb.map(v=>v.toString(16).padStart(2,'0')).join('');const pcl=(P.print_colors||{})[n]||{};const pw=pcl.width??pcl.width_index??'';const prr=pcl.point_radius??(pcl.width===undefined?pcl.width_mm:undefined)??'';const wu=(P.line_width_unit||{}).raw;
  const wl=(wu!==undefined&&wu<0)?`× 1/${-wu} mm${pw!==''?` = ${(pw/(-wu)).toFixed(2)} mm`:''}`:'ドット';
  pt.insertAdjacentHTML('beforeend',`<tr><td>${n}</td><td><input type="color" data-pen="${n}" value="${hex}"></td><td class="hint">${rgb.join(',')}</td><td><input type="number" step="1" data-pw="${n}" value="${pw}"> <span class="hint">${wl}</span></td><td><input type="number" step="0.05" data-prr="${n}" value="${prr}"></td></tr>`)}
 const tt=$('#ttTable tbody');tt.innerHTML='';const TT=P.text_types||{};const dw=[2,2.5,3,4,5,6,7,8,9,10],dc=[1,1,2,2,3,3,4,4,5,5];
 for(let n=1;n<=10;n++){const t=TT[n]||{width:dw[n-1],height:dw[n-1],spacing:0,pen:dc[n-1]};tt.insertAdjacentHTML('beforeend',`<tr><td>${n}</td><td><input type="number" step="0.1" data-tt="${n}.width" value="${t.width}"></td><td><input type="number" step="0.1" data-tt="${n}.height" value="${t.height}"></td><td><input type="number" step="0.1" data-tt="${n}.spacing" value="${t.spacing}"></td><td><input type="number" data-tt="${n}.pen" value="${t.pen}"></td></tr>`)}
 $('#frPaper').value=P.paper||'A3';$('#frScale').value=P.scale||50;$('#frImg').src='';fillLinetypes();}
function collect(){const o={...P};o.company=$('#company').value;o.description=$('#desc').value;o.paper=$('#paper').value;o.scale=parseFloat($('#scale').value)||undefined;o.font=$('#font').value||undefined;
 const {gn,gs,ln}=readLayerEditor($('#layerEditor'));o.group_names=gn;o.group_scales=gs;o.layer_names=ln;
 const defs={};$$('[data-d]').forEach(i=>{const [t,k]=i.dataset.d.split('.');const v=i.type==='checkbox'?i.checked:i.value;if(v===''||v===false||v==null)return;defs[t]=defs[t]||{};defs[t][k]=i.type==='checkbox'?true:(k==='lg'||k==='opening_lg')?parseInt(v,16):parseFloat(v)});o.defaults=defs;
 const pl={};$$('[data-p]').forEach(i=>{const [s,idx]=i.dataset.p.split('.');if(i.value==='')return;pl[s]=pl[s]||[0,0];pl[s][+idx]=idx==='0'?parseInt(i.value,16):parseInt(i.value)});o.pipe_layers=pl;
 o.frame={...(P.frame||{}),style:$('#frStyle').value,lg:$('#frLg').value||'F',margin:parseFloat($('#frMargin').value),bottom:parseFloat($('#frBottom').value),height:parseFloat($('#frHeight').value),border:$('#frBorder').checked,
  company_height:parseFloat($('#frCompanyH').value)||5,title_height:parseFloat($('#frTitleH').value)||3,value_height:parseFloat($('#frValueH').value)||2.5,label_height:parseFloat($('#frLabelH').value)||2,
  fields:{...((P.frame||{}).fields||{}),company:$('#frCompany').value||undefined}};
 const pc={};$$('[data-pen]').forEach(i=>{const h=i.value;pc[i.dataset.pen]=[1,3,5].map(k=>parseInt(h.substr(k,2),16))});o.pen_colors=pc;
 const pr={...(P.print_colors||{})};const wuc=(P.line_width_unit||{}).raw;
 $$('[data-pw]').forEach(i=>{if(i.value==='')return;const n=i.dataset.pw;const c={...(pr[n]||{})};delete c.width_index;c.width=parseInt(i.value);if(wuc!==undefined&&wuc<0){c.width_mm=+(c.width/(-wuc)).toFixed(4)}else{delete c.width_mm}pr[n]=c});
 $$('[data-prr]').forEach(i=>{if(i.value==='')return;const n=i.dataset.prr;pr[n]={...(pr[n]||{}),point_radius:parseFloat(i.value)}});o.print_colors=pr;
 const tt={};$$('[data-tt]').forEach(i=>{const [n,k]=i.dataset.tt.split('.');tt[n]=tt[n]||{};tt[n][k]=parseFloat(i.value)});o.text_types=tt;o.linetypes=JSON.parse(JSON.stringify(LT));o.print_dpi=+$('#ltDpi').value;return o}
$('#exportJwf').onclick=async e=>{e.preventDefault();try{await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(collect())});window.location=`/api/profile/${encodeURIComponent(P.name)}/export_jwf?download=1`}catch(x){toast('エラー: '+x.message)}};
$('#save').onclick=async()=>{try{P=collect();await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(P)});toast('保存しました');await loadState()}catch(e){toast('エラー: '+e.message)}};
$('#profSel').onchange=e=>loadProfile(e.target.value);$('#newProf').onclick=newProfile;
$('#dupProf').onclick=()=>{const n=prompt('複製先の名前',P.name+'_copy');if(!n)return;P={...collect(),name:n};fill();toast('保存を押すと作成されます')};
$('#delProf').onclick=async()=>{if(!confirm(`プロファイル ${P.name} を削除しますか？`))return;await api('/api/profile/'+encodeURIComponent(P.name),{method:'DELETE'});toast('削除しました');$('#profSel').value='';await loadState()};
$('#applyPreset').onclick=async()=>{try{await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(collect())});P=await api('/api/profile/'+encodeURIComponent(P.name)+'/from_preset',{method:'POST',body:JSON.stringify({preset:$('#presetSel').value})});fill();toast('プリセットを反映しました')}catch(e){toast('エラー: '+e.message)}};
function drop(el,handler){['dragenter','dragover'].forEach(ev=>el.addEventListener(ev,e=>{e.preventDefault();el.classList.add('hover')}));['dragleave','drop'].forEach(ev=>el.addEventListener(ev,e=>{e.preventDefault();el.classList.remove('hover')}));el.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)handler(f)});el.onclick=()=>{const i=document.createElement('input');i.type='file';i.onchange=()=>i.files[0]&&handler(i.files[0]);i.click()}}
drop($('#dropJwf'),async f=>{try{await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(collect())});const fd=new FormData();fd.append('file',f);P=await api('/api/profile/'+encodeURIComponent(P.name)+'/import_jwf',{method:'POST',body:fd});fill();toast('jwf を取り込みました')}catch(e){toast('エラー: '+e.message)}});
drop($('#dropJww'),async f=>{try{await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(collect())});const fd=new FormData();fd.append('file',f);fd.append('frame_lg',$('#frameLgSel').value);fd.append('frame_texts',$('#frameTextsSel').value);P=await api('/api/profile/'+encodeURIComponent(P.name)+'/import_jww',{method:'POST',body:fd});fill();toast('jww を取り込みました')}catch(e){toast('エラー: '+e.message)}});
drop($('#dropLogo'),async f=>{try{await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(collect())});const fd=new FormData();fd.append('file',f);fd.append('width_mm',$('#logoW').value);fd.append('threshold',$('#logoThr').value);fd.append('invert',$('#logoInv').checked?'1':'');fd.append('simplify_px',$('#logoSimp').value);const r=await api('/api/profile/'+encodeURIComponent(P.name)+'/logo',{method:'POST',body:fd});await loadProfile(P.name);toast(`ロゴを取り込みました（${r.polylines} 図形）`);$('#frPrev').click()}catch(e){toast('エラー: '+e.message)}});
$('#logoDel').onclick=async()=>{try{await api('/api/profile/'+encodeURIComponent(P.name)+'/logo',{method:'DELETE'});await loadProfile(P.name);toast('ロゴを外しました')}catch(e){toast('エラー: '+e.message)}};
$('#frPrev').onclick=()=>{$('#frImg').src=`/api/preview/frame/${encodeURIComponent(P.name)}?paper=${$('#frPaper').value}&scale=${$('#frScale').value}&t=${Date.now()}`};
$('#jsonApply').onclick=()=>{try{P=JSON.parse($('#jsonArea').value);fill();toast('反映しました（保存で確定）')}catch(e){toast('JSON エラー: '+e.message)}};
$('#drwLoad').onclick=async()=>{try{D=await api('/api/drawing/'+encodeURIComponent($('#drwSel').value));$('#drwPaper').value=D.paper;$('#drwScale').value=D.main_scale;$('#drwDesc').value=D.description||'';$('#drwInfo').textContent=`要素 ${D.entity_count} / プロファイル ${D.profile||'なし'}`;layerEditor($('#drwLayerEditor'),D.group_names_all,D.group_scales_all,D.layer_names);$('#drwImg').src=`/api/preview/drawing/${encodeURIComponent(D.name)}?t=${Date.now()}`}catch(e){toast('エラー: '+e.message)}};
$('#drwSave').onclick=async()=>{if(!D)return;try{const {gn,gs,ln}=readLayerEditor($('#drwLayerEditor'));await api('/api/drawing/'+encodeURIComponent(D.name),{method:'PUT',body:JSON.stringify({paper:$('#drwPaper').value,main_scale:parseFloat($('#drwScale').value),description:$('#drwDesc').value,group_names:gn,group_scales:gs,layer_names:ln})});toast('図面を保存しました');$('#drwLoad').click()}catch(e){toast('エラー: '+e.message)}};
$('#drwApply').onclick=async()=>{if(!D)return;try{await api('/api/drawing/'+encodeURIComponent(D.name)+'/apply_profile',{method:'POST',body:JSON.stringify({profile:P.name,frame:$('#drwApplyFrame').checked})});toast('適用しました');$('#drwLoad').click()}catch(e){toast('エラー: '+e.message)}};
$('#drwSaveProf').onclick=async()=>{if(!D)return;const n=prompt('新しいプロファイル名',D.name+'_profile');if(!n)return;try{await api('/api/drawing/'+encodeURIComponent(D.name)+'/save_as_profile',{method:'POST',body:JSON.stringify({profile:n})});toast('プロファイルを作成しました');await loadState();$('#profSel').value=n;await loadProfile(n)}catch(e){toast('エラー: '+e.message)}};
// ---- line types (線種) ------------------------------------------------------------
let LTD={},LTN={},LT={};
const ltKind=k=>k[0]==='R'?'random':k[0]==='L'?'long':k==='09'?'aux':'normal';
const hexToPat=(h,rnd)=>{const v=parseInt(h,16)>>>0;let s='';for(let i=0;i<32;i++){const b=(v>>>(31-i))&1;s+=rnd?(b?"'":","):(b?'-':' ')}return s};
const patToHex=p=>{let v=0;for(let i=0;i<32;i++){if("-'".includes(p[i]||' '))v=(v|(1<<(31-i)))>>>0}return v.toString(16).padStart(8,'0')};
function ltRuns(pat,unit){unit=Math.max(1,Math.min(32,unit|0));let c=[...pat.slice(0,unit)].map(ch=>ch==='-');
 if(c.every(b=>b))return[[true,unit]];if(!c.some(b=>b))return[[false,unit]];
 for(let p=1;p<=unit;p++){if(unit%p===0&&c.every((b,i)=>b===c[i%p])){c=c.slice(0,p);break}}
 const n=c.length;let s=0;for(let i=0;i<n;i++){if(c[i]&&!c[(i-1+n)%n]){s=i;break}}
 const r=c.slice(s).concat(c.slice(0,s));const out=[];for(const b of r){if(out.length&&out[out.length-1][0]===b)out[out.length-1][1]++;else out.push([b,1])}
 let best=0;out.forEach((x,j)=>{const y=out[best];if(x[0]&&(!y[0]||x[1]>y[1]))best=j});return out.slice(best).concat(out.slice(0,best))}
function ltPreview(k,lt,dpi,ps,zoom){const kind=ltKind(k),W=460,mm=W/zoom,dot=25.4/dpi*ps;let g='';
 for(let i=0;i<=mm;i++){const x=i*zoom,h=i%10===0?10:i%5===0?7:4;g+=`<line x1="${x}" y1="36" x2="${x}" y2="${36-h}" stroke="#aab" stroke-width="1"/>`;if(i%10===0)g+=`<text x="${x+2}" y="47" font-size="9" fill="#889">${i}mm</text>`}
 if(kind==='aux'){const r=ltRuns(hexToPat(lt.hex),lt.unit||4);let x=0;while(x<W){for(const [on,n] of r){const w=n*(lt.pitch||1)*2;if(on)g+=`<line x1="${x}" y1="14" x2="${Math.min(W,x+w)}" y2="14" stroke="#c0c" stroke-width="2"/>`;x+=w;if(x>=W)break}}
  return [`<svg width="${W}" height="50">${g}</svg>`,'補助線種は画面表示だけで、印刷されません']}
 if(kind==='random'){const pat=hexToPat(lt.hex,true),st=(lt.print_pitch||1)*dot,am=(lt.print_amp||1)*dot;let pts=[],x=0,y=0,i=0;
  while(x<=W){pts.push(`${x.toFixed(1)},${(14-y*zoom).toFixed(1)}`);y+=pat[i%32]==="'"?am:-am;y=Math.max(-3,Math.min(3,y));x+=st*zoom;i++}
  g+=`<polyline points="${pts.join(' ')}" fill="none" stroke="#111" stroke-width="1.2"/>`;
  return [`<svg width="${W}" height="50">${g}</svg>`,`1 文字ごとに ${st.toFixed(3)} mm 進み、${am.toFixed(3)} mm 上下に振れる（形は目安）`]}
 const r=ltRuns(hexToPat(lt.hex),lt.unit||32),pp=lt.print_pitch||10;let x=0;
 while(x<W){for(const [on,n] of r){const len=n*pp*dot*zoom;if(on)g+=`<line x1="${x.toFixed(2)}" y1="14" x2="${Math.min(W,x+len).toFixed(2)}" y2="14" stroke="#111" stroke-width="2"/>`;x+=len;if(x>=W)break}}
 const parts=r.map(([on,n])=>`${on?'線':'空き'} ${(n*pp*dot).toFixed(2)}`),cyc=r.reduce((a,x)=>a+x[1]*pp*dot,0);
 return [`<svg width="${W}" height="50">${g}</svg>`,`${parts.join(' / ')} mm　（1 区切り ${cyc.toFixed(2)} mm）`]}
function fillLinetypes(){LT={};for(const k of Object.keys(LTD)){LT[k]={...LTD[k],...((P&&P.linetypes||{})[k]||{})}}if(P&&P.print_dpi)$('#ltDpi').value=String(P.print_dpi);renderLinetypes()}
function renderLinetypes(){const tb=$('#ltTable tbody');if(!tb)return;tb.innerHTML='';const dpi=+$('#ltDpi').value,ps=+$('#ltScale').value,zoom=+$('#ltZoom').value;$('#ltZoomV').textContent=`1 mm = ${zoom} px`;
 for(const k of Object.keys(LT)){const lt=LT[k],kind=ltKind(k),rnd=kind==='random',pat=hexToPat(lt.hex,rnd);
  const cells=[...pat].map((ch,i)=>`<span class="ltc ${"-'".includes(ch)?'on':''} ${(!rnd&&i<(lt.unit||32))?'u':''}" data-k="${k}" data-i="${i}" title="${i+1} 文字目"></span>`).join('');
  let ctl;
  if(rnd)ctl=`<td class="hint">—</td><td>振幅 <input type="number" min="1" max="16" data-lt="${k}.amp" value="${lt.amp}"><br>ピッチ <input type="number" min="1" max="16" data-lt="${k}.pitch" value="${lt.pitch}"></td><td>振幅 <input type="number" min="1" max="16" data-lt="${k}.print_amp" value="${lt.print_amp}"><br>ピッチ <input type="number" min="1" max="160" data-lt="${k}.print_pitch" value="${lt.print_pitch}"></td>`;
  else ctl=`<td><select data-lt="${k}.unit">${[1,2,4,8,16,32].map(u=>`<option ${u==lt.unit?'selected':''}>${u}</option>`).join('')}</select></td><td><input type="number" min="1" max="16" data-lt="${k}.pitch" value="${lt.pitch}"></td><td>${kind==='aux'?'<span class="hint">印刷しない</span>':`<input type="number" min="1" max="160" data-lt="${k}.print_pitch" value="${lt.print_pitch}">`}</td>`;
  const [svg,txt]=ltPreview(k,lt,dpi,ps,zoom);
  tb.insertAdjacentHTML('beforeend',`<tr><td><b>${LTN[k]||k}</b></td><td><div class="ltcells">${cells}</div><code class="ltpat">${rnd?pat:pat.replace(/ /g,'·')}</code></td>${ctl}<td>${svg}<div class="hint">${txt}</div></td></tr>`)}
 $$('.ltc').forEach(c=>c.onclick=()=>{const k=c.dataset.k,i=+c.dataset.i,rnd=ltKind(k)==='random';const p=[...hexToPat(LT[k].hex,rnd)];p[i]="-'".includes(p[i])?' ':'-';LT[k].hex=patToHex(p.join(''));renderLinetypes()});
 $$('[data-lt]').forEach(inp=>inp.onchange=()=>{const [k,f]=inp.dataset.lt.split('.');LT[k][f]=parseInt(inp.value);renderLinetypes()})}
['#ltDpi','#ltScale'].forEach(id=>$(id).onchange=renderLinetypes);$('#ltZoom').oninput=renderLinetypes;
$('#ltReset').onclick=()=>{if(!confirm('線種を Jw_cad の初期値に戻しますか？（保存を押すまで確定しません）'))return;LT=JSON.parse(JSON.stringify(LTD));renderLinetypes()};
$('#ltTest').onclick=async()=>{try{P=collect();await api('/api/profile/'+encodeURIComponent(P.name),{method:'PUT',body:JSON.stringify(P)});const r=await api('/api/profile/'+encodeURIComponent(P.name)+'/linetype_test',{method:'POST',body:JSON.stringify({dpi:+$('#ltDpi').value})});alert(`線種テスト用の図形を用意しました。\nJw_cad で 外部変形 → JWMCP_import.bat → 置く位置をクリック。\n印刷倍率 100% で印刷し、点線の 1 区切りを目盛と比べてください。\n（${r.outbox}）`)}catch(e){toast('エラー: '+e.message)}};
loadState();
</script></body></html>
"""
