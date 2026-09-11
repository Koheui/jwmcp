"""MCP tool surface for jwmcp.  Run:  python -m jwmcp   (stdio transport)."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, bridge, jwc_temp, jww_read, scan
from .dxf_out import write_dxf
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
    ents = [e for e in f.entities if lg is None or e["lg"] == lg]
    ents = [e for e in ents if not e.get("temporary")]
    out = out_png or str(_scratch(f"{Path(path).stem}_{int(time.time())}.png"))
    info = render(ents, out, scale_for=f.scale_of, bbox=bbox, width_px=min(width_px, 4000),
                  palette=(f.header.get("palette") or {}).get("pen_colors"), show_text=show_text)
    return [Image(path=out), info]


@app.tool(description="Convert a .jww to DXF (AC1024 by default) using ezjww. Returns the output path.")
def jww_to_dxf(path: str, out: str | None = None, version: str = "AC1024") -> dict:
    out = out or str(Path(path).with_suffix(".dxf"))
    return jww_read.to_dxf(path, out, version)


# ---------------------------------------------------------------------------
# 2. Drawing (agent-authored geometry)
# ---------------------------------------------------------------------------

@app.tool(description="Create (or reset) a named drawing. scale = denominator of the drawing scale (100 for 1/100). "
                      "paper: A0..A4, 2A..5A, 10m/50m/100m. group_names/layer_names set Jw_cad レイヤグループ名/レイヤ名 "
                      "(e.g. group_names={'0':'平面図'}, layer_names={'0-1':'壁','0-2':'柱'}).")
def drawing_new(name: str, scale: float = 100, paper: str = "A3", description: str = "", preset: str | None = None,
                group_names: dict[str, str] | None = None, layer_names: dict[str, str] | None = None,
                group_scales: dict[str, float] | None = None) -> dict:
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
    for k, v in (group_scales or {}).items():
        d.group_scales[int(str(k), 16)] = float(v)
    d.save()
    return d.summary()


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


@app.tool(description="Render a drawing to PNG and return the image (bbox in real mm to zoom).", structured_output=False)
def drawing_preview(name: str, bbox: list[float] | None = None, width_px: int = 1600, out_png: str | None = None) -> list[Any]:
    d = Drawing.load(name)
    out = out_png or str(_scratch(f"{name}_{int(time.time())}.png"))
    info = render(d.entities, out, scale_for=d.scale_of, bbox=bbox, width_px=min(width_px, 4000))
    return [Image(path=out), info]


@app.tool(description="Export a drawing. format: 'dxf' (open in Jw_cad via ファイル>開く, DXF), 'jwc_temp' (外部変形 text that "
                      "JWMCP_import.bat feeds into an open Jw_cad drawing), or 'json'. Returns the output path.")
def drawing_export(name: str, format: str = "dxf", out: str | None = None) -> dict:
    d = Drawing.load(name)
    fmt = format.lower()
    outdir = jwmcp_home() / "exports"; outdir.mkdir(exist_ok=True)
    if fmt == "dxf":
        out = out or str(outdir / f"{name}.dxf")
        return write_dxf(d.entities, out, scale_for=d.scale_of, layer_names=d.layer_names)
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
                                  group_names=group_names, layer_names=layer_names)
    except ModelError as exc:
        return {"error": str(exc)}
    return {**bridge.respond(ex, job_id, text), "entities": len(ents), "deleted_selection": delete_selected}


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
    info = render(j.entities, out, scale_for=lambda e: 1.0, width_px=width_px)
    return [Image(path=out), info]


def main() -> None:
    app.run(transport=os.environ.get("JWMCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
