"""Scanned / PDF drawings: page rendering, zoomed views, mm calibration, overlay check, vector import.

Uses pdfplumber + pypdfium2 (MIT / BSD-Apache) so the project can be published under MIT.

A scan lives under $JWMCP_HOME/scans/<id>/ with meta.json:
  {"source": path, "pages": [{"n":1,"png":..., "w":px, "h":px, "dpi":150, "pt_w":..,"pt_h":.., "vector": bool}],
   "calibration": {"1": {"ppm": px_per_mm, "ox": px, "oy": px}}}
Calibration maps pixel (px, py) -> real mm: x = (px - ox) / ppm ; y = (oy - py) / ppm  (y up).
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from .model import jwmcp_home


def _scan_dir(scan_id: str) -> Path:
    d = jwmcp_home() / "scans" / scan_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(scan_id: str) -> Path:
    return _scan_dir(scan_id) / "meta.json"


def load_meta(scan_id: str) -> dict:
    p = _meta_path(scan_id)
    if not p.exists():
        raise FileNotFoundError(f"scan '{scan_id}' not found (use scan_open first)")
    return json.loads(p.read_text(encoding="utf-8"))


def save_meta(scan_id: str, meta: dict) -> None:
    _meta_path(scan_id).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def list_scans() -> list[dict]:
    root = jwmcp_home() / "scans"
    out = []
    if root.exists():
        for d in sorted(root.iterdir()):
            if (d / "meta.json").exists():
                m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                out.append({"id": m["id"], "source": m["source"], "pages": len(m["pages"]),
                            "calibrated_pages": sorted(m.get("calibration", {}).keys())})
    return out


def open_scan(path: str, dpi: int = 150, scan_id: str | None = None, pages: list[int] | None = None) -> dict:
    src = Path(path).expanduser()
    if not src.exists():
        raise FileNotFoundError(str(src))
    sid = scan_id or re.sub(r"[^\w\-]+", "_", src.stem)[:60]
    d = _scan_dir(sid)
    meta = {"id": sid, "source": str(src), "created": time.time(), "pages": [], "calibration": {}}
    if src.suffix.lower() == ".pdf":
        import pdfplumber
        with pdfplumber.open(str(src)) as pdf:
            for i, pg in enumerate(pdf.pages):
                n = i + 1
                if pages and n not in pages:
                    continue
                im = pg.to_image(resolution=dpi).original.convert("RGB")
                out = d / f"p{n}.png"
                im.save(str(out))
                n_vec = len(pg.lines) + len(pg.rects) + len(pg.curves)
                meta["pages"].append({"n": n, "png": str(out), "w": im.width, "h": im.height, "dpi": dpi,
                                      "pt_w": float(pg.width), "pt_h": float(pg.height),
                                      "vector": n_vec > 20, "drawings": n_vec, "has_text": len(pg.chars) > 0})
    else:
        from PIL import Image
        im = Image.open(str(src)).convert("RGB")
        out = d / "p1.png"
        im.save(str(out))
        meta["pages"].append({"n": 1, "png": str(out), "w": im.width, "h": im.height, "dpi": dpi,
                              "pt_w": None, "pt_h": None, "vector": False, "drawings": 0, "has_text": False})
    save_meta(sid, meta)
    return summary(meta)


def summary(meta: dict) -> dict:
    return {"id": meta["id"], "source": meta["source"],
            "pages": [{k: p[k] for k in ("n", "w", "h", "dpi", "vector", "has_text")} for p in meta["pages"]],
            "calibration": meta.get("calibration", {}),
            "hint": "scan_view で拡大して読み、scan_calibrate で実寸を決めてから drawing_add で部品を置き、scan_overlay で重ねて確認。"
                    "vector=true の PDF は scan_vector_import で線をそのまま取り込める"}


def _page(meta: dict, n: int) -> dict:
    for p in meta["pages"]:
        if p["n"] == n:
            return p
    raise ValueError(f"page {n} not in scan {meta['id']}")


def view(scan_id: str, page: int = 1, region: list[float] | None = None, max_px: int = 1600,
         grid: bool = True) -> dict:
    """Crop a region (pixels, or fractions 0..1 of the page) and return a PNG path. Draws a pixel ruler
    so the model can report pixel coordinates back for calibration / placement."""
    from PIL import Image, ImageDraw
    meta = load_meta(scan_id)
    pg = _page(meta, page)
    im = Image.open(pg["png"]).convert("RGB")
    W, H = im.size
    if region:
        x0, y0, x1, y1 = region
        if max(region) <= 1.0:
            x0, x1, y0, y1 = x0 * W, x1 * W, y0 * H, y1 * H
        x0, y0 = max(0, int(x0)), max(0, int(y0)); x1, y1 = min(W, int(x1)), min(H, int(y1))
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise ValueError("region is empty")
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    crop = im.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    k = min(1.0, max_px / max(cw, ch))
    if k < 1.0:
        crop = crop.resize((max(1, int(cw * k)), max(1, int(ch * k))), Image.LANCZOS)
    if grid:
        dr = ImageDraw.Draw(crop)
        step = _nice_step((x1 - x0) / 8)
        sx = crop.width / (x1 - x0)
        sy = crop.height / (y1 - y0)
        gx = math.ceil(x0 / step) * step
        while gx < x1:
            px = (gx - x0) * sx
            dr.line([(px, 0), (px, crop.height)], fill=(255, 0, 0), width=1)
            dr.text((px + 2, 2), str(int(gx)), fill=(255, 0, 0))
            gx += step
        gy = math.ceil(y0 / step) * step
        while gy < y1:
            py = (gy - y0) * sy
            dr.line([(0, py), (crop.width, py)], fill=(255, 0, 0), width=1)
            dr.text((2, py + 2), str(int(gy)), fill=(255, 0, 0))
            gy += step
    out = _scan_dir(scan_id) / f"view_p{page}_{x0}_{y0}_{x1}_{y1}.png"
    crop.save(str(out))
    cal = meta.get("calibration", {}).get(str(page))
    info = {"png": str(out), "page": page, "region_px": [x0, y0, x1, y1], "page_px": [W, H], "view_px": list(crop.size),
            "ruler": "赤線の数字はページ内ピクセル座標 (左上原点, y下向き)。calibrate 済みなら scan_px_to_mm で実寸に変換"}
    if cal:
        info["region_mm"] = [px_to_mm(cal, x0, y1), px_to_mm(cal, x1, y0)]
    return info


def _nice_step(v: float) -> float:
    if v <= 0:
        return 100
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        if m * e >= v:
            return m * e
    return 10 * e


def px_to_mm(cal: dict, px: float, py: float) -> list[float]:
    return [(px - cal["ox"]) / cal["ppm"], (cal["oy"] - py) / cal["ppm"]]


def mm_to_px(cal: dict, x: float, y: float) -> list[float]:
    return [cal["ox"] + x * cal["ppm"], cal["oy"] - y * cal["ppm"]]


def calibrate(scan_id: str, page: int = 1, *, p1: list[float] | None = None, p2: list[float] | None = None,
              distance_mm: float | None = None, px_per_mm: float | None = None, paper: str | None = None,
              scale: float | None = None, origin_px: list[float] | None = None, origin_mm: list[float] | None = None) -> dict:
    """Three ways: (a) two pixel points + real distance, (b) explicit px_per_mm, (c) paper + drawing scale
    (uses the page's physical size: e.g. A2 sheet at 1/100 -> 1 px = 25.4/dpi paper-mm -> x100 real mm)."""
    meta = load_meta(scan_id)
    pg = _page(meta, page)
    if p1 and p2 and distance_mm:
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if d <= 0 or distance_mm <= 0:
            raise ValueError("p1/p2 must differ and distance_mm > 0")
        ppm = d / distance_mm
        method = "two_points"
    elif px_per_mm:
        ppm = float(px_per_mm); method = "px_per_mm"
    elif scale:
        from .model import PAPER_SIZES_MM
        if pg.get("pt_w"):
            paper_w_mm = pg["pt_w"] * 25.4 / 72.0
        elif paper and paper in PAPER_SIZES_MM:
            pw, ph = PAPER_SIZES_MM[paper]
            paper_w_mm = pw if pg["w"] >= pg["h"] else ph
        else:
            raise ValueError("scale needs a PDF page (physical size known) or paper=A2 etc. for images")
        px_per_paper_mm = pg["w"] / paper_w_mm
        ppm = px_per_paper_mm / float(scale)
        method = f"paper_scale(1/{scale:g})"
    else:
        raise ValueError("give p1+p2+distance_mm, or px_per_mm, or scale (+paper for images)")
    ox, oy = (origin_px or [0, pg["h"]])
    if origin_mm:
        ox -= origin_mm[0] * ppm; oy += origin_mm[1] * ppm
    cal = {"ppm": ppm, "ox": float(ox), "oy": float(oy), "method": method}
    meta.setdefault("calibration", {})[str(page)] = cal
    save_meta(scan_id, meta)
    return {"page": page, "calibration": cal, "mm_per_px": 1 / ppm,
            "page_extent_mm": {"min": px_to_mm(cal, 0, pg["h"]), "max": px_to_mm(cal, pg["w"], 0)}}


def overlay(scan_id: str, page: int, entities: list[dict], scale_for, out_png: str | None = None,
            region_px: list[float] | None = None, width_px: int = 1800, alpha: float = 0.45) -> dict:
    """Render entities on top of the scan (needs calibration)."""
    from .render import render
    meta = load_meta(scan_id)
    pg = _page(meta, page)
    cal = meta.get("calibration", {}).get(str(page))
    if not cal:
        raise ValueError("calibrate the page first (scan_calibrate)")
    W, H = pg["w"], pg["h"]
    x0, y0, x1, y1 = region_px or [0, 0, W, H]
    mm_min = px_to_mm(cal, x0, y1); mm_max = px_to_mm(cal, x1, y0)
    out = out_png or str(_scan_dir(scan_id) / f"overlay_p{page}_{int(time.time())}.png")
    extent = [px_to_mm(cal, 0, 0)[0], px_to_mm(cal, W, 0)[0], px_to_mm(cal, 0, H)[1], px_to_mm(cal, 0, 0)[1]]
    info = render(entities, out, scale_for=scale_for, bbox=[mm_min[0], mm_min[1], mm_max[0], mm_max[1]],
                  width_px=width_px, margin=0.0, background_image=(pg["png"], extent, alpha), overlay_style=True)
    info["region_px"] = [x0, y0, x1, y1]
    return info


def _pdf_page(meta: dict, page: int):
    import pdfplumber
    if not meta["source"].lower().endswith(".pdf"):
        raise ValueError("this needs a PDF source")
    pdf = pdfplumber.open(meta["source"])
    return pdf, pdf.pages[page - 1]


def vector_lines(scan_id: str, page: int = 1, region_px: list[float] | None = None, min_len_mm: float = 1.0,
                 include_curves: bool = True) -> dict:
    """Extract vector paths from a PDF page (CAD-exported PDFs) as real-mm line segments (needs calibration)."""
    meta = load_meta(scan_id)
    pg = _page(meta, page)
    cal = meta.get("calibration", {}).get(str(page))
    if not cal:
        raise ValueError("calibrate the page first (scan_calibrate; for PDFs scale=<denominator> is enough)")
    pdf, p = _pdf_page(meta, page)
    k = pg["w"] / pg["pt_w"]     # px per pt

    def to_mm(x, top):
        return px_to_mm(cal, x * k, top * k)

    def inside(x, top):
        if not region_px:
            return True
        return region_px[0] <= x * k <= region_px[2] and region_px[1] <= top * k <= region_px[3]

    segs = []
    n_curves = 0

    def add(a, b):
        if inside(*a) or inside(*b):
            segs.append((to_mm(*a), to_mm(*b)))

    def bezier(p0, p1, p2, p3, n=8):
        prev = p0
        for i in range(1, n + 1):
            t = i / n
            x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
            y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
            add(prev, (x, y)); prev = (x, y)

    objs = list(p.lines) + list(p.rects) + (list(p.curves) if include_curves else [])
    n_fills = 0
    solids: list[dict] = []

    def _rgb(col):
        if col is None:
            return None
        if isinstance(col, (int, float)):
            v = int(round(float(col) * 255)); return [v, v, v]
        col = list(col)
        if len(col) == 1:
            v = int(round(col[0] * 255)); return [v, v, v]
        if len(col) == 3:
            return [int(round(c * 255)) for c in col]
        if len(col) == 4:   # CMYK
            c, m, y, k_ = col
            return [int(round(255 * (1 - c) * (1 - k_))), int(round(255 * (1 - m) * (1 - k_))), int(round(255 * (1 - y) * (1 - k_)))]
        return None

    for obj in objs:
        if obj.get("fill"):
            # Filled shapes are Jw_cad ソリッド exported as triangles/quads (with a hairline stroke of the same
            # colour). Their edges are not drawing lines: keep them as solids instead.
            n_fills += 1
            pts = [op[1] for op in (obj.get("path") or []) if op[0] in ("m", "l")]
            if len(pts) in (3, 4) and any(inside(*q) for q in pts):
                s = {"type": "solid", "points": [[round(v, 2) for v in to_mm(*q)] for q in pts]}
                rgb = _rgb(obj.get("non_stroking_color"))
                if rgb:
                    s["rgb"] = rgb
                solids.append(s)
            continue
        path = obj.get("path")
        if not path:   # older pdfplumber: fall back to pts as a single polyline
            pts = obj.get("pts") or []
            for a, b in zip(pts, pts[1:]):
                add(a, b)
            continue
        start = cur = None
        for op in path:
            kind = op[0]
            if kind == "m":
                start = cur = op[1]
            elif kind == "l" and cur is not None:
                add(cur, op[1]); cur = op[1]
            elif kind == "c" and cur is not None:
                bezier(cur, op[1], op[2], op[3]); cur = op[3]; n_curves += 1
            elif kind == "v" and cur is not None:      # first control point = current point
                bezier(cur, cur, op[1], op[2]); cur = op[2]; n_curves += 1
            elif kind == "y" and cur is not None:      # second control point = end point
                bezier(cur, op[1], op[2], op[2]); cur = op[2]; n_curves += 1
            elif kind == "h" and cur is not None and start is not None:
                add(cur, start); cur = start
    pdf.close()
    out = []
    for (x1, y1), (x2, y2) in segs:
        if math.hypot(x2 - x1, y2 - y1) >= min_len_mm:
            out.append({"type": "line", "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2)})
    return {"lines": out, "solids": solids, "count": len(out), "curves": n_curves, "fills": n_fills}


def texts(scan_id: str, page: int = 1) -> dict:
    """Text strings with mm positions from a PDF page (vector PDFs only)."""
    meta = load_meta(scan_id)
    pg = _page(meta, page)
    cal = meta.get("calibration", {}).get(str(page))
    if not meta["source"].lower().endswith(".pdf"):
        return {"texts": [], "count": 0, "note": "image scan: no embedded text (read it with scan_view)"}
    pdf, p = _pdf_page(meta, page)
    k = pg["w"] / pg["pt_w"]
    items = []
    for wd in p.extract_words(keep_blank_chars=False):
        it = {"text": wd["text"], "px": [round((wd["x0"] + wd["x1"]) / 2 * k), round((wd["top"] + wd["bottom"]) / 2 * k)],
              "height_pt": round(wd["bottom"] - wd["top"], 1)}
        if cal:
            it["mm"] = [round(v, 1) for v in px_to_mm(cal, wd["x0"] * k, wd["bottom"] * k)]
        items.append(it)
    pdf.close()
    return {"texts": items, "count": len(items)}
