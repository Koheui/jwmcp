"""MCP tool surface for jwmcp.  Run:  python -m jwmcp   (stdio transport)."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, bridge, jwc_temp, jww_read, profiles, scan
from .dxf_out import write_dxf
from .jwf import parse_jwf
from .jwf import summary as jwf_summary
from .model import Drawing, ModelError, jwmcp_home, normalize_entity
from .presets import PRESETS, preset_names
from .render import render

INSTRUCTIONS = """jwmcp: Jw_cad (日本の2D CAD) をAIから扱うためのツール群。

座標は常に「実寸mm」(1/100の図面で3,640mmの壁は 3640)。文字の高さ/幅/間隔だけは Jw_cad と同じ「図寸mm」。
属性: lg=レイヤグループ0-15, ly=レイヤ0-15, lc=線色1-9 (2=黒が標準線), lt=線種1-9 (1実線 2点線1 3点線2 4点線3 5一点鎖1 6一点鎖2 7二点鎖1 8二点鎖2 9補助線種)。

4つの経路:
 1. .jww 読取: jww_info / jww_query / jww_texts / jww_preview / jww_to_dxf
 2. 作図: drawing_new(preset=arch_jp など) → drawing_add(entities: wall/grid/column/room/pipe/equipment/line/text...) →
    drawing_preview → drawing_export (dxf / jwc_temp / json)
 3. Jw_cad との往復 (外部変形ブリッジ): gaihen_setup で .bat を生成 → ユーザーが Jw_cad 内で JWMCP_send.bat を実行 →
    gaihen_jobs / gaihen_read で選択図形を受け取り → gaihen_respond で図形を返す (Jw_cad に即反映)。
    gaihen_prepare_import は作図済み drawing を outbox に置き、ユーザーが JWMCP_import.bat で取り込む。
 4. スキャン/PDF → CAD: scan_open → scan_view で読む → scan_calibrate で実寸を決める → 壁厚・建具サイズを指定して
    drawing_add(wall/grid/column/room...) → scan_overlay で原図に重ねて照合 → 2〜3 を経て Jw_cad へ。
    ベクター PDF なら scan_vector_import で線をそのまま取り込める。
"""

app = MCPServer("jwmcp", version=__version__, instructions=INSTRUCTIONS)

_ENTITY_DOC = """entities: list of objects. Common keys: lg, ly (0-15 or hex "0".."F"), lc (1-9), lt (1-9), tag.
  {"type":"line","x1","y1","x2","y2"}
  {"type":"polyline","points":[[x,y],...],"closed":false}
  {"type":"rect","x","y","w","h","angle":0}           (x,y = lower-left)
  {"type":"circle","cx","cy","r"}
  {"type":"arc","cx","cy","r","start","end"}          (deg, CCW)
  {"type":"text","x","y","text","height":3,"width":3,"spacing":0,"angle":0,"align":"left|center|right","font"?,"cn"?}
       height/width/spacing are paper mm (図寸). x,y = baseline anchor (left-bottom unless align).
  {"type":"point","x","y"}
  {"type":"dimension","x1","y1","x2","y2","offset":500,"text"?,"text_height":3,"decimals":0}
       offset = real-mm distance from the measured points to the dimension line (sign = side).
  {"type":"solid","points":[[x,y]x3or4],"rgb":[r,g,b]?}
Architectural (expand to Jw_cad lines/arcs/text):
  {"type":"wall","points":[[x,y],...],"thickness":150,"closed":false,"core":true,"core_ly":1,"core_extend":300,
     "openings":[{"at":1000,"width":800,"kind":"door|double_door|sliding|window|fixed|opening","hinge":"start|end","side":"+|-","frame":25}],
     "opening_lg":3,"opening_ly":0,"opening_lc":1}      at = mm along the centre line; side "+" = left of travel
  {"type":"grid","xs":[0,3640],"ys":[0,2730],"x_labels":["X1","X2"],"y_labels":["Y1","Y2"],"extend":1500,"dims":false}
  {"type":"column","cx","cy","w":600,"h":600,"angle":0,"hatch":true}
  {"type":"room","x","y","name":"和室","height":5,"note":"6帖"}
  {"type":"pipe","points":[[x,y],...],"system":"給水|給湯|排水|通気|ガス|冷媒|ドレン|ダクト|給気|排気","diameter":"25A"}
  {"type":"equipment","kind":"toilet|sink|washbasin|bath|kitchen|ac_indoor|ac_outdoor|fan|cubicle|tank|elevator|box","x","y","w","h","angle","label"}
A drawing created with a preset fills lg/ly/lc per type automatically (see presets_list).
"""


def _scratch(name: str) -> Path:
    d = jwmcp_home() / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _ex() -> Path | None:
    return None  # default exchange (env JWMCP_EXCHANGE or ~/JW_MCP_Exchange)


# ---------------------------------------------------------------------------
# 1. .jww reading
# ---------------------------------------------------------------------------

@app.tool(description="Open a .jww file and return a compact summary: version, paper, layer groups with scale (1/N) "
                      "and layer names/counts, entity counts by type, bounding box (real mm), text sample.")
def jww_info(path: str) -> dict:
    return jww_read.load(path).summary()


@app.tool(description="Query entities of a .jww file (real-mm coordinates). Filter by types "
                      "(line, circle, arc, text, point, solid, dimfigure), layer group lg, layer ly, bbox "
                      "[min_x,min_y,max_x,max_y], or regex pattern on text. Paginate with limit/offset.")
def jww_query(path: str, types: list[str] | None = None, lg: int | None = None, ly: int | None = None,
              bbox: list[float] | None = None, pattern: str | None = None, limit: int = 300, offset: int = 0) -> dict:
    return jww_read.load(path).query(types=types, lg=lg, ly=ly, bbox=bbox, pattern=pattern, limit=min(limit, 2000), offset=offset)


@app.tool(description="List all text strings of a .jww (room names, dimensions, notes) with position, layer and size.")
def jww_texts(path: str, lg: int | None = None, pattern: str | None = None, limit: int = 1000) -> dict:
    f = jww_read.load(path)
    r = f.query(types=["text", "dimfigure"], lg=lg, pattern=pattern, limit=limit)
    items = [{"id": e["id"], "text": e.get("text", ""), "x": round(e.get("x", e.get("x1", 0)), 1), "y": round(e.get("y", e.get("y1", 0)), 1),
              "lg": f"{e['lg']:X}", "ly": f"{e['ly']:X}", "height": e.get("height"), "angle": round(e.get("angle", 0), 2),
              "kind": e.get("kind", "dim")} for e in r["entities"]]
    return {"total": r["total"], "texts": items}


@app.tool(description="Render a .jww (or a region of it) to PNG and return the image. bbox = [min_x,min_y,max_x,max_y] in real mm "
                      "to zoom; lg to show one layer group only. Use this to *see* the drawing.", structured_output=False)
def jww_preview(path: str, bbox: list[float] | None = None, lg: int | None = None, width_px: int = 1600,
                out_png: str | None = None, show_text: bool = True) -> list[Any]:
    f = jww_read.load(path)
    ms = f.main_scale
    ents = [e for e in f.unified_entities(ms) if lg is None or e["lg"] == lg]
    ents = [e for e in ents if not e.get("temporary")]
    out = out_png or str(_scratch(f"{Path(path).stem}_{int(time.time())}.png"))
    info = render(ents, out, scale_for=lambda e: ms, bbox=bbox, width_px=min(width_px, 4000),
                  palette=(f.header.get("palette") or {}).get("pen_colors"), show_text=show_text)
    info["main_scale"] = ms
    return [Image(path=out), info]


@app.tool(description="Convert a .jww to DXF (AC1024 by default) using ezjww. Returns the output path.")
def jww_to_dxf(path: str, out: str | None = None, version: str = "AC1024") -> dict:
    out = out or str(Path(path).with_suffix(".dxf"))
    return jww_read.to_dxf(path, out, version)


# ---------------------------------------------------------------------------
# 2. Drawing (agent-authored geometry)
# ---------------------------------------------------------------------------

@app.tool(description="Create (or reset) a named drawing. scale = denominator of the drawing scale (100 for 1/100). "
                      "paper: A0..A4, 2A..5A, 10m/50m/100m. profile = a saved company profile (profile_list) that supplies "
                      "group/layer names, scales, per-type defaults and the title-block frame; frame=true adds the frame "
                      "(fields = title/no/drawing/scale/note values). preset = built-in layer preset (presets_list). "
                      "group_names/layer_names/group_scales override (e.g. group_names={'0':'平面図'}, layer_names={'0-1':'壁'}).")
def drawing_new(name: str, scale: float | None = None, paper: str | None = None, description: str = "",
                profile: str | None = None, frame: bool = False, fields: dict[str, str] | None = None,
                preset: str | None = None, group_names: dict[str, str] | None = None,
                layer_names: dict[str, str] | None = None, group_scales: dict[str, float] | None = None) -> dict:
    prof = profiles.load_profile(profile) if profile else None
    scale = scale or (prof or {}).get("scale") or 100
    paper = paper or (prof or {}).get("paper") or "A3"
    d = Drawing(name, scale=scale, paper=paper, description=description)
    if preset:
        if preset not in PRESETS:
            return {"error": f"unknown preset {preset}; available: {preset_names()}"}
        d.preset = preset
        for k, v in PRESETS[preset].get("group_names", {}).items():
            d.group_names[int(k, 16)] = v
        for k, v in PRESETS[preset].get("layer_names", {}).items():
            g, l = k.split("-"); d.layer_names[f"{int(g,16):X}-{int(l,16):X}"] = v
    for k, v in (group_names or {}).items():
        d.group_names[int(str(k), 16)] = v
    for k, v in (layer_names or {}).items():
        g, l = str(k).split("-"); d.layer_names[f"{int(g,16):X}-{int(l,16):X}"] = v
    if prof:
        profiles.apply_to_drawing(prof, d)
    for k, v in (group_names or {}).items():
        d.group_names[int(str(k), 16)] = v
    for k, v in (layer_names or {}).items():
        g, l = str(k).split("-"); d.layer_names[f"{int(g,16):X}-{int(l,16):X}"] = v
    for k, v in (group_scales or {}).items():
        d.group_scales[int(str(k), 16)] = float(v)
    if frame:
        fe = profiles.frame_entity(prof or {"frame": {"lg": "F", "style": "strip"}}, d.paper, fields)
        d.group_scales[int(fe["lg"])] = 1.0
        d.group_names.setdefault(int(fe["lg"]), "図面枠")
        d.add([fe])
    d.save()
    return d.summary()


@app.tool(description="Add (or replace) the title-block frame (図面枠) of a drawing at S=1:1 in its own layer group. "
                      "Uses the drawing's profile frame settings (or the built-in strip). fields: no/title/drawing/scale/note/company. "
                      "paper defaults to the drawing's paper.")
def drawing_frame(name: str, fields: dict[str, str] | None = None, paper: str | None = None, lg: str | None = None,
                  border: bool | None = None) -> dict:
    d = Drawing.load(name)
    prof = profiles.load_profile(d.profile) if d.profile else {"frame": {"lg": "F", "style": "strip"}}
    fe = profiles.frame_entity(prof, paper or d.paper, fields, lg)
    if border is not None:
        fe["border"] = border
    d.entities = [e for e in d.entities if e["type"] != "frame"]
    d.group_scales[int(fe["lg"])] = 1.0
    d.group_names.setdefault(int(fe["lg"]), "図面枠")
    ids = d.add([fe])
    d.save()
    return {"frame_id": ids[0], "lg": f"{int(fe['lg']):X}", "paper": fe["paper"], "style": fe["style"], "fields": fe["fields"]}


# ---------------------------------------------------------------------------
# Profiles (company settings: layer groups / layers / scales / pens / text types / frame)
# ---------------------------------------------------------------------------

@app.tool(description="List saved company profiles (layer groups, layer names, scales, pen colours, text types, frame).")
def profile_list() -> dict:
    return {"profiles": profiles.list_profiles(), "dir": str(profiles.profile_dir())}


@app.tool(description="Show one profile in full.")
def profile_show(name: str) -> dict:
    p = profiles.load_profile(name)
    if "frame_template" in p:
        p = {**p, "frame_template": {**p["frame_template"], "entities": f"<{len(p['frame_template']['entities'])} entities>"}}
    return p


@app.tool(description="Create or update a profile. Keys: company, description, paper, scale, group_names {'0':'図面枠'}, "
                      "group_scales {'F':1}, layer_names {'1-0':'通り芯'}, defaults {'wall':{'lg':1,'ly':1,'lc':2}}, "
                      "pipe_layers {'給水':[2,0]}, frame {lg,style,fields,margin,bottom,height,border,...}, base_preset (start from a preset).")
def profile_set(name: str, company: str | None = None, description: str | None = None, paper: str | None = None,
                scale: float | None = None, group_names: dict[str, str] | None = None, group_scales: dict[str, float] | None = None,
                layer_names: dict[str, str] | None = None, defaults: dict[str, dict] | None = None,
                pipe_layers: dict[str, list[int]] | None = None, frame: dict | None = None, base_preset: str | None = None) -> dict:
    try:
        return profiles.update_profile(name, company=company, description=description, paper=paper, scale=scale,
                                       group_names=group_names, group_scales=group_scales, layer_names=layer_names,
                                       defaults=defaults, pipe_layers=pipe_layers, frame=frame, base_preset=base_preset)
    except ModelError as exc:
        return {"error": str(exc)}


@app.tool(description="Vectorise a bitmap (PNG/BMP/JPG) into closed polylines by contour tracing (logos, symbols, north arrows). "
                      "width_mm = width of the result; coordinates start at (0,0) lower-left, y up. Optionally add the result to a "
                      "drawing at x,y (real mm) with scale. threshold: 0-255 (default Otsu); invert for light-on-dark art; "
                      "simplify_px reduces points. Outlines only (no fills).")
def image_trace(path: str, width_mm: float, drawing: str | None = None, x: float = 0, y: float = 0, scale: float = 1.0,
                threshold: int | None = None, invert: bool = False, simplify_px: float = 1.0, min_area_px: float = 16.0,
                lg: int = 0, ly: int = 0, lc: int = 2, tag: str = "trace") -> dict:
    from .raster import trace_image, trace_to_entities
    try:
        res = trace_image(path, width_mm, threshold=threshold, invert=invert, simplify_px=simplify_px, min_area_px=min_area_px)
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}
    out = {k: v for k, v in res.items() if k != "polylines"}
    if drawing:
        d = Drawing.load(drawing)
        ids = d.add(trace_to_entities(res, x=x, y=y, scale=scale, lg=lg, ly=ly, lc=lc, tag=tag))
        d.save()
        out["added"] = len(ids); out["drawing"] = drawing
    else:
        out["polylines"] = res["polylines"][:200]
    return out


@app.tool(description="Trace a logo bitmap and attach it to a profile's title-block frame (drawn as lines in the logo cell, "
                      "fitted to the cell with a margin). width_mm = logo width in paper mm before fitting.")
def profile_set_logo(name: str, image: str, width_mm: float = 40, threshold: int | None = None, invert: bool = False,
                     simplify_px: float = 1.0, min_area_px: float = 16.0, lc: int = 2, margin: float = 2.0) -> dict:
    try:
        return profiles.set_logo(name, image, width_mm, threshold=threshold, invert=invert, simplify_px=simplify_px,
                                 min_area_px=min_area_px, lc=lc, margin=margin)
    except (ModelError, RuntimeError, ValueError) as exc:
        return {"error": str(exc)}


@app.tool(description="Remove the logo from a profile's frame.")
def profile_clear_logo(name: str) -> dict:
    return profiles.clear_logo(name)


@app.tool(description="Read a Jw_cad environment file (.jwf / jw_win.jwf): paper, pen colours, printer widths, 文字種 sizes, font, "
                      "default group scales, layer names.")
def jwf_read(path: str) -> dict:
    return jwf_summary(parse_jwf(path))


@app.tool(description="Write a Jw_cad environment file (.jwf) from a profile: layer-group names, layer names, group scales, "
                      "pen colours, printer widths, 文字種. Load it in Jw_cad (設定 > 環境設定ファイル > 読込) to get the same "
                      "layer names/scales for new drawings. Other settings are copied from the profile's source .jwf.")
def profile_export_jwf(name: str, out: str | None = None, base_jwf: str | None = None) -> dict:
    from .jwf import write_jwf
    try:
        p = profiles.load_profile(name)
    except ModelError as exc:
        return {"error": str(exc)}
    outdir = jwmcp_home() / "exports"; outdir.mkdir(exist_ok=True)
    return write_jwf(p, out or str(outdir / f"{name}.jwf"), base_jwf)


@app.tool(description="Create/update a profile from a .jwf (pen colours, 文字種, font, default group scales, layer names).")
def profile_from_jwf(path: str, name: str) -> dict:
    base = None
    try:
        base = profiles.load_profile(name)
    except ModelError:
        pass
    p = profiles.from_jwf(path, name, base)
    return {"profile": name, "text_types": p.get("text_types"), "pen_colors": p.get("pen_colors"), "font": p.get("font"),
            "group_scales": p.get("group_scales"), "layer_names": p.get("layer_names")}


@app.tool(description="Capture the figures of a 外部変形 job (the title block the user selected in Jw_cad with JWMCP_send.bat) "
                      "as the profile's frame template, then cancel the job so Jw_cad changes nothing. Draw the frame in Jw_cad with "
                      "empty value cells and fixed texts (company name) at the wanted size; frame_texts='labels' keeps only "
                      "No./Title/... labels. paper defaults to the job's paper size.")
def profile_frame_from_job(job_id: str, name: str, paper: str | None = None, frame_texts: str = "all",
                           exchange: str | None = None) -> dict:
    ex = Path(exchange) if exchange else None
    j = bridge.read_job(ex, job_id)
    base = None
    try:
        base = profiles.load_profile(name)
    except ModelError:
        pass
    try:
        p = profiles.frame_from_job(j, name, base, paper=paper, frame_texts=frame_texts)
    except ModelError as exc:
        return {"error": str(exc)}
    bridge.cancel(ex, job_id, "図面枠をプロファイルに保存しました（図面は変更していません）")
    tpl = p["frame_template"]
    return {"profile": name, "frame_template": {k: v for k, v in tpl.items() if k != "entities"}, "job_cancelled": job_id,
            "next": "設定画面の「図面枠」タブでプレビュー、drawing_new(frame=true) で使用"}


@app.tool(description="Create/update a profile from an existing .jww: learns layer-group scales/names and layer names; "
                      "frame_lg captures that group as the title-block template (converted to paper mm, reusable at S=1:1 on any paper). "
                      "frame_texts: 'all' keeps every text of that group, 'labels' keeps only No./Title/Drawing/Scale/Note labels.")
def profile_from_jww(path: str, name: str, frame_lg: int | None = None, frame_texts: str = "all") -> dict:
    base = None
    try:
        base = profiles.load_profile(name)
    except ModelError:
        pass
    p = profiles.from_jww(path, name, base, frame_lg=frame_lg, frame_texts=frame_texts)
    out = {"profile": name, "group_scales": p.get("group_scales"), "group_names": p.get("group_names"), "layer_names": p.get("layer_names")}
    if "frame_template" in p:
        out["frame_template"] = {k: v for k, v in p["frame_template"].items() if k != "entities"} | {"entities": len(p["frame_template"]["entities"])}
    return out


@app.tool(description="List saved drawings.")
def drawing_list() -> dict:
    return {"drawings": Drawing.list_names(), "home": str(jwmcp_home())}


@app.tool(description="List layer presets usable in drawing_new(preset=...) with their group/layer names and per-type defaults.")
def presets_list() -> dict:
    return {"presets": PRESETS}


# ---------------------------------------------------------------------------
# 4. Scanned / PDF drawings -> CAD
# ---------------------------------------------------------------------------

@app.tool(description="Open a scanned drawing (PDF or image) for CAD conversion. Pages are rendered to PNG. Returns page sizes "
                      "and whether the PDF is vector (CAD-exported → scan_vector_import) or raster (read with scan_view).")
def scan_open(path: str, dpi: int = 150, scan_id: str | None = None, pages: list[int] | None = None) -> dict:
    return scan.open_scan(path, dpi=dpi, scan_id=scan_id, pages=pages)


@app.tool(description="List opened scans.")
def scan_list() -> dict:
    return {"scans": scan.list_scans()}


@app.tool(description="Look at a page or a zoomed region of it (region = [x0,y0,x1,y1] in pixels, or fractions 0..1). "
                      "A red pixel ruler is drawn so you can report pixel positions for scan_calibrate / placement.",
          structured_output=False)
def scan_view(scan_id: str, page: int = 1, region: list[float] | None = None, max_px: int = 1600, grid: bool = True) -> list[Any]:
    info = scan.view(scan_id, page, region, max_px, grid)
    return [Image(path=info["png"]), info]


@app.tool(description="Define how pixels map to real mm. Either p1/p2 (pixels) + distance_mm (a known dimension on the scan), "
                      "or px_per_mm, or scale=<denominator> (+paper=A2 for images; PDFs know their physical size). "
                      "origin_px = pixel that becomes (0,0) mm (default: bottom-left corner).")
def scan_calibrate(scan_id: str, page: int = 1, p1: list[float] | None = None, p2: list[float] | None = None,
                   distance_mm: float | None = None, px_per_mm: float | None = None, scale: float | None = None,
                   paper: str | None = None, origin_px: list[float] | None = None) -> dict:
    return scan.calibrate(scan_id, page, p1=p1, p2=p2, distance_mm=distance_mm, px_per_mm=px_per_mm,
                          scale=scale, paper=paper, origin_px=origin_px)


@app.tool(description="Convert pixel positions on a calibrated page to real mm (and back with mm_points).")
def scan_px_to_mm(scan_id: str, page: int = 1, px_points: list[list[float]] | None = None,
                  mm_points: list[list[float]] | None = None) -> dict:
    meta = scan.load_meta(scan_id)
    cal = meta.get("calibration", {}).get(str(page))
    if not cal:
        return {"error": "page not calibrated"}
    return {"mm": [scan.px_to_mm(cal, *p) for p in (px_points or [])],
            "px": [scan.mm_to_px(cal, *p) for p in (mm_points or [])]}


@app.tool(description="Draw a drawing on top of the scan to check alignment (needs calibration). region_px zooms.",
          structured_output=False)
def scan_overlay(scan_id: str, drawing: str, page: int = 1, region_px: list[float] | None = None,
                 width_px: int = 1800, alpha: float = 0.45) -> list[Any]:
    d = Drawing.load(drawing)
    info = scan.overlay(scan_id, page, d.entities, d.scale_of, region_px=region_px, width_px=width_px, alpha=alpha)
    return [Image(path=info["png"]), info]


@app.tool(description="For vector PDFs (exported from CAD): import the page's line work into a drawing as lines (real mm). "
                      "region_px limits the area. Set lg/ly/lc/lt for the imported lines; tag lets you remove them later.")
def scan_vector_import(scan_id: str, drawing: str, page: int = 1, region_px: list[float] | None = None,
                       min_len_mm: float = 1.0, lg: int = 0, ly: int = 0, lc: int = 2, lt: int = 1, tag: str = "vector",
                       include_solids: bool = True, solid_ly: int | None = None) -> dict:
    v = scan.vector_lines(scan_id, page, region_px, min_len_mm)
    d = Drawing.load(drawing)
    ids = d.add([{**ln, "lg": lg, "ly": ly, "lc": lc, "lt": lt, "tag": tag} for ln in v["lines"]])
    n_solid = 0
    if include_solids and v["solids"]:
        n_solid = len(d.add([{**s, "lg": lg, "ly": solid_ly if solid_ly is not None else ly, "tag": tag} for s in v["solids"]]))
    d.save()
    return {"imported_lines": len(ids), "imported_solids": n_solid, "curves": v["curves"], "entity_count": len(d.entities), "bbox": d.bbox()}


@app.tool(description="Text strings embedded in a PDF page with pixel and mm positions (vector PDFs).")
def scan_texts(scan_id: str, page: int = 1) -> dict:
    return scan.texts(scan_id, page)


@app.tool(description="Summary of a drawing (counts, layers, bbox).")
def drawing_info(name: str) -> dict:
    return Drawing.load(name).summary()


@app.tool(description="Add entities to a drawing (batch). Returns the new ids. defaults applies lg/ly/lc/lt to every entity "
                      "that does not set them.\n" + _ENTITY_DOC)
def drawing_add(name: str, entities: list[dict], defaults: dict | None = None) -> dict:
    d = Drawing.load(name)
    try:
        ids = d.add(entities, defaults)
    except ModelError as exc:
        return {"error": str(exc), "added": 0}
    d.save()
    return {"added": len(ids), "ids": ids, "entity_count": len(d.entities), "bbox": d.bbox()}


@app.tool(description="Return entities of a drawing (optionally only those with given ids or tag).")
def drawing_entities(name: str, ids: list[str] | None = None, tag: str | None = None, limit: int = 500, offset: int = 0) -> dict:
    d = Drawing.load(name)
    ents = [e for e in d.entities if (ids is None or e["id"] in set(ids)) and (tag is None or e.get("tag") == tag)]
    return {"total": len(ents), "entities": ents[offset: offset + limit]}


@app.tool(description="Remove entities by id (or every entity with the given tag). Use clear=true to empty the drawing.")
def drawing_remove(name: str, ids: list[str] | None = None, tag: str | None = None, clear: bool = False) -> dict:
    d = Drawing.load(name)
    if clear:
        n = len(d.entities); d.entities = []
    else:
        sel = [e["id"] for e in d.entities if (ids and e["id"] in set(ids)) or (tag and e.get("tag") == tag)]
        n = d.remove(sel)
    d.save()
    return {"removed": n, "entity_count": len(d.entities)}


@app.tool(description="Replace one entity (same id) with new content. Fields not given are taken from the new object only.")
def drawing_update(name: str, id: str, entity: dict) -> dict:
    d = Drawing.load(name)
    for i, e in enumerate(d.entities):
        if e["id"] == id:
            new = normalize_entity({**entity, "id": id})
            d.entities[i] = new
            d.save()
            return {"updated": id, "entity": new}
    return {"error": f"id {id} not found"}


@app.tool(description="Set/rename layer groups, layers and scales of a drawing. group_names={'0':'平面'}, "
                      "layer_names={'0-1':'壁'}, group_scales={'1':'50'}.")
def drawing_layers(name: str, group_names: dict[str, str] | None = None, layer_names: dict[str, str] | None = None,
                   group_scales: dict[str, float] | None = None) -> dict:
    d = Drawing.load(name)
    for k, v in (group_names or {}).items():
        d.group_names[int(str(k), 16)] = v
    for k, v in (layer_names or {}).items():
        g, l = str(k).split("-"); d.layer_names[f"{int(g,16):X}-{int(l,16):X}"] = v
    for k, v in (group_scales or {}).items():
        d.group_scales[int(str(k), 16)] = float(v)
    d.save()
    return d.summary()


@app.tool(description="Render a drawing to PNG and return the image (bbox in real mm to zoom). The paper outline is drawn "
                      "as a grey dotted rectangle so you can judge the layout on the sheet.", structured_output=False)
def drawing_preview(name: str, bbox: list[float] | None = None, width_px: int = 1600, out_png: str | None = None,
                    paper_outline: bool = True) -> list[Any]:
    d = Drawing.load(name)
    out = out_png or str(_scratch(f"{name}_{int(time.time())}.png"))
    ents = d.unified_entities()
    if paper_outline:
        from .model import PAPER_SIZES_MM
        W, H = PAPER_SIZES_MM[d.paper]
        k = d.main_scale
        ents = [{"type": "rect", "x": -W / 2 * k, "y": -H / 2 * k, "w": W * k, "h": H * k, "lg": 0, "ly": 0, "lc": 9, "lt": 3}] + ents
    info = render(ents, out, scale_for=d.scale_for_unified, bbox=bbox, width_px=min(width_px, 4000))
    info["paper"] = d.paper; info["main_scale"] = d.main_scale
    return [Image(path=out), info]


@app.tool(description="Export a drawing. format: 'dxf' (open in Jw_cad via ファイル>開く, DXF), 'jwc_temp' (外部変形 text that "
                      "JWMCP_import.bat feeds into an open Jw_cad drawing), or 'json'. Returns the output path.")
def drawing_export(name: str, format: str = "dxf", out: str | None = None) -> dict:
    d = Drawing.load(name)
    fmt = format.lower()
    outdir = jwmcp_home() / "exports"; outdir.mkdir(exist_ok=True)
    if fmt == "dxf":
        out = out or str(outdir / f"{name}.dxf")
        return {**write_dxf(d.unified_entities(), out, scale_for=d.scale_for_unified, layer_names=d.layer_names,
                            paper=d.paper, main_scale=d.main_scale),
                "model_space": f"real mm at 1/{d.main_scale:g}; other layer groups (e.g. the 1:1 frame) are rescaled to fit"}
    if fmt in ("jwc_temp", "jwc", "gaihen"):
        out = out or str(outdir / f"{name}_jwc_temp.txt")
        text = jwc_temp.serialize(d.entities, scale_for=d.scale_of, group_names=d.group_names, layer_names=d.layer_names)
        Path(out).write_bytes(jwc_temp.encode(text))
        return {"jwc_temp": out, "lines": text.count("\n"), "encoding": "cp932",
                "note": "Jw_cad に取り込むには gaihen_prepare_import(name) を使うか、このファイルを JWC_TEMP.TXT として外部変形で読ませる"}
    if fmt == "json":
        out = out or str(outdir / f"{name}.json")
        Path(out).write_text(__import__("json").dumps(d.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return {"json": out}
    return {"error": "format must be dxf | jwc_temp | json"}


@app.tool(description="Import the entities of a .jww file (optionally filtered by lg/ly/types/bbox) into a drawing so they can be "
                      "edited, re-exported or sent back to Jw_cad.")
def drawing_import_jww(name: str, path: str, lg: int | None = None, ly: int | None = None, types: list[str] | None = None,
                       bbox: list[float] | None = None, tag: str | None = None) -> dict:
    d = Drawing.load(name)
    f = jww_read.load(path)
    r = f.query(types=types, lg=lg, ly=ly, bbox=bbox, limit=1_000_000)
    added = 0
    for e in r["entities"]:
        if e["type"] in ("dimfigure", "block", "solid_circle") or e.get("temporary"):
            continue
        e2 = {k: v for k, v in e.items() if k not in ("id", "flag", "extent", "block", "style", "base_point")}
        if tag:
            e2["tag"] = tag
        try:
            d.add([e2]); added += 1
        except ModelError:
            continue
    for gi, sc in f.group_scales.items():
        d.group_scales[gi] = sc
    d.save()
    return {"imported": added, "entity_count": len(d.entities)}


# ---------------------------------------------------------------------------
# 3. 外部変形 bridge
# ---------------------------------------------------------------------------

@app.tool(description="Create the exchange folder and the three 外部変形 .bat files (JWMCP_send / send_all / import). "
                      "exchange = folder on this machine (default ~/JW_MCP_Exchange or $JWMCP_EXCHANGE). "
                      "win_exchange = the SAME folder as seen from the Windows PC running Jw_cad "
                      "(e.g. 'G:\\\\マイドライブ\\\\JW_MCP_Exchange'). wait = seconds the .bat waits for a response.")
def gaihen_setup(exchange: str | None = None, win_exchange: str | None = None, wait: int = 900) -> dict:
    return bridge.setup(Path(exchange) if exchange else None, win_exchange, wait)


@app.tool(description="Bridge status: exchange folder, pending jobs from Jw_cad, unconsumed responses.")
def gaihen_status(exchange: str | None = None) -> dict:
    return bridge.status(Path(exchange) if exchange else None)


@app.tool(description="List jobs sent from Jw_cad (each = one 外部変形 run waiting for a response).")
def gaihen_jobs(exchange: str | None = None) -> dict:
    return {"jobs": bridge.list_jobs(Path(exchange) if exchange else None)}


@app.tool(description="Read one job: scales per layer group, selection range, picked points, write settings, layer names "
                      "and the selected entities (real mm). Use limit/offset for big selections.")
def gaihen_read(job_id: str, exchange: str | None = None, limit: int = 500, offset: int = 0) -> dict:
    j = bridge.read_job(Path(exchange) if exchange else None, job_id)
    d = j.to_dict()
    ents = d.pop("entities")
    d["entities"] = ents[offset: offset + limit]
    d["returned"] = len(d["entities"]); d["offset"] = offset
    return d


@app.tool(description="Answer a job: the entities are drawn into the open Jw_cad drawing as soon as the .bat sees the file. "
                      "Give either entities (see drawing_add schema) or drawing=<name>. delete_selected=true removes the "
                      "originally selected figures first (replace). notice shows a message in Jw_cad. "
                      "Coordinates are real mm in the job's layer group scales (gaihen_read → scales).")
def gaihen_respond(job_id: str, entities: list[dict] | None = None, drawing: str | None = None,
                   delete_selected: bool = False, notice: str | None = None, exchange: str | None = None) -> dict:
    ex = Path(exchange) if exchange else None
    j = bridge.read_job(ex, job_id)
    scale_for = lambda e: j.hs[int(e.get("lg", 0))] if 0 <= int(e.get("lg", 0)) < 16 else 1.0
    group_names = layer_names = None
    if drawing:
        d = Drawing.load(drawing)
        ents = d.entities
        scale_for = d.scale_of
        group_names, layer_names = d.group_names, d.layer_names
    else:
        ents = [normalize_entity(e, {"lg": j.write.get("lg", 0), "ly": j.write.get("ly", 0),
                                     "lc": j.write.get("lc", 1), "lt": j.write.get("lt", 1)}) for e in (entities or [])]
    try:
        text = jwc_temp.serialize(ents, scale_for=scale_for, delete_selected=delete_selected, notice=notice,
                                  group_names=group_names, layer_names=layer_names,
                                  offset_for=bridge.response_offset_for(j))
    except ModelError as exc:
        return {"error": str(exc)}
    return {**bridge.respond(ex, job_id, text), "entities": len(ents), "deleted_selection": delete_selected,
            "coordinates": "drawing origin → converted back to the job's base point" if bridge.response_offset_for(j) else "as given"}


@app.tool(description="Cancel a job: Jw_cad reports 未実行 and changes nothing.")
def gaihen_cancel(job_id: str, reason: str = "", exchange: str | None = None) -> dict:
    return bridge.cancel(Path(exchange) if exchange else None, job_id, reason)


@app.tool(description="Place a drawing (or raw entities) in outbox/IMPORT.txt. The user then runs JWMCP_import.bat inside Jw_cad "
                      "and the geometry appears in the open drawing with layer/colour/linetype attributes.")
def gaihen_prepare_import(drawing: str | None = None, entities: list[dict] | None = None, notice: str | None = None,
                          exchange: str | None = None) -> dict:
    if drawing:
        d = Drawing.load(drawing)
        text = jwc_temp.serialize(d.entities, scale_for=d.scale_of, notice=notice, group_names=d.group_names, layer_names=d.layer_names)
        n = len(d.entities)
    else:
        ents = [normalize_entity(e) for e in (entities or [])]
        text = jwc_temp.serialize(ents, notice=notice)
        n = len(ents)
    return {**bridge.prepare_import(Path(exchange) if exchange else None, text), "entities": n}


@app.tool(description="Parse any JWC_TEMP.TXT-format file (e.g. one saved manually from Jw_cad) into entities.")
def jwc_temp_parse(path: str, limit: int = 500, offset: int = 0) -> dict:
    j = jwc_temp.parse(jwc_temp.decode(Path(path).expanduser().read_bytes()))
    d = j.to_dict(); ents = d.pop("entities"); d["entities"] = ents[offset: offset + limit]
    return d


@app.tool(description="Render a job's selected entities to PNG and return the image.", structured_output=False)
def gaihen_preview(job_id: str, exchange: str | None = None, width_px: int = 1400) -> list[Any]:
    j = bridge.read_job(Path(exchange) if exchange else None, job_id)
    out = str(_scratch(f"job_{job_id}.png"))
    info = render(j.entities, out, scale_for=lambda e: j.hs[int(e.get("lg", 0))], width_px=width_px)
    return [Image(path=out), info]


def main() -> None:
    app.run(transport=os.environ.get("JWMCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
