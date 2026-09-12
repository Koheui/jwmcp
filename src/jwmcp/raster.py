"""Bitmap → line data (logo vectorisation) with OpenCV contour tracing.

Output: closed polylines in paper mm (or any unit the caller decides via width_mm), origin at the
lower-left corner of the image, y up. Outer contours and holes are both returned (Jw_cad has no fill
concept for arbitrary polygons, so outlines are what goes into the drawing).
"""
from __future__ import annotations

from pathlib import Path


def trace_image(path: str, width_mm: float, *, threshold: int | None = None, invert: bool = False,
                simplify_px: float = 1.0, min_area_px: float = 16.0, max_points: int = 20000,
                blur: int = 0, upscale: float | None = None) -> dict:
    """upscale: resample factor before tracing (None = automatic so the longer side is ~1200 px; small logos
    trace much cleaner). simplify_px / min_area_px are in *source* pixels."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("opencv-python-headless is required: pip install jwmcp[raster]") from exc

    p = Path(path).expanduser()
    data = np.fromfile(str(p), dtype=np.uint8)          # handles non-ASCII paths on Windows
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read image {p}")
    if img.ndim == 3 and img.shape[2] == 4:              # alpha: composite on white
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        img = (rgb * alpha + 255.0 * (1 - alpha)).astype(np.uint8)
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    if blur and blur > 0:
        k = blur * 2 + 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)
    h0, w0 = gray.shape[:2]
    if upscale is None:
        upscale = max(1.0, min(8.0, 1200.0 / max(w0, h0)))
    if upscale != 1.0:
        gray = cv2.resize(gray, (int(round(w0 * upscale)), int(round(h0 * upscale))), interpolation=cv2.INTER_CUBIC)
    h, w = gray.shape[:2]
    if threshold is None:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)   # ink (dark) = 255
    else:
        _, binary = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY_INV)
    if invert:
        binary = 255 - binary
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    mm_per_px = float(width_mm) / float(w)            # per traced pixel
    src_mm_per_px = float(width_mm) / float(w0)
    eps = max(simplify_px, 0.0) * upscale
    min_area = min_area_px * upscale * upscale
    polys = []
    total_pts = 0
    if hierarchy is not None:
        hierarchy = hierarchy[0]
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            approx = cv2.approxPolyDP(c, eps, True) if eps > 0 else c
            pts = [[float(q[0][0]) * mm_per_px, (h - float(q[0][1])) * mm_per_px] for q in approx]
            if len(pts) < 3:
                continue
            total_pts += len(pts)
            if total_pts > max_points:
                break
            polys.append({"type": "polyline", "points": pts, "closed": True,
                          "hole": bool(hierarchy[i][3] >= 0), "area_mm2": area * mm_per_px * mm_per_px})
    return {"image": str(p), "px": [w0, h0], "width_mm": float(width_mm), "height_mm": h0 * src_mm_per_px,
            "mm_per_px": src_mm_per_px, "upscale": upscale, "polylines": polys, "count": len(polys), "points": total_pts,
            "threshold": "otsu" if threshold is None else threshold}


def trace_to_entities(res: dict, *, x: float = 0.0, y: float = 0.0, scale: float = 1.0, lg: int = 0, ly: int = 0,
                      lc: int = 2, lt: int = 1, tag: str | None = None) -> list[dict]:
    """Polylines → drawing entities placed with lower-left at (x, y), multiplied by scale."""
    out = []
    for pl in res["polylines"]:
        e = {"type": "polyline", "points": [[x + a * scale, y + b * scale] for a, b in pl["points"]], "closed": True,
             "lg": lg, "ly": ly, "lc": lc, "lt": lt}
        if tag:
            e["tag"] = tag
        out.append(e)
    return out
