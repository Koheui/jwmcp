"""PNG preview of model primitives (real mm) with matplotlib."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import Arc, Polygon  # noqa: E402

from .model import LINETYPE_DASHES, pen_rgb, primitives, text_anchor_left  # noqa: E402

_JP_FONTS = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Hiragino Maru Gothic ProN", "Noto Sans CJK JP",
             "Noto Sans JP", "IPAexGothic", "IPAGothic", "MS Gothic", "Yu Gothic", "DejaVu Sans"]


def _pick_font() -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    for n in _JP_FONTS:
        if n in names:
            return n
    return "DejaVu Sans"


_FONT = None


def render(entities: Iterable[dict], out_png: str, *, scale_for: Callable[[dict], float],
           bbox: list[float] | None = None, width_px: int = 1600, dpi: int = 100,
           palette: list[int] | None = None, background: str = "white", show_text: bool = True,
           title: str | None = None, margin: float = 0.03,
           background_image: tuple | None = None, overlay_style: bool = False) -> dict:
    """Render entities. `bbox` = [min_x, min_y, max_x, max_y] real mm to crop; otherwise fit all.
    background_image = (png_path, [xmin, xmax, ymin, ymax] in real mm, alpha) draws a scan underneath."""
    global _FONT
    if _FONT is None:
        _FONT = _pick_font()

    prims: list[tuple[dict, float]] = []
    for e in entities:
        sc = scale_for(e)
        if e.get("type") == "dimfigure":
            prims.append(({"type": "line", "x1": e["x1"], "y1": e["y1"], "x2": e["x2"], "y2": e["y2"], "lc": e.get("lc", 1), "lt": e.get("lt", 1)}, sc))
            vt = e.get("value_text")
            if vt and e.get("text"):
                prims.append(({"type": "text", "text": e["text"], "align": "left", "spacing": vt.get("spacing", 0.0),
                               "lc": e.get("lc", 1), **vt}, sc))
            continue
        if e.get("type") in ("block", "solid_circle"):
            continue
        for p in primitives(e, sc):
            prims.append((p, sc))

    # extent
    if bbox:
        x0, y0, x1, y1 = bbox
    else:
        xs, ys = [], []
        for p, sc in prims:
            t = p["type"]
            if t == "line":
                xs += [p["x1"], p["x2"]]; ys += [p["y1"], p["y2"]]
            elif t in ("circle", "arc"):
                r = p["r"] * max(1.0, p.get("flatness", 1.0)); xs += [p["cx"] - r, p["cx"] + r]; ys += [p["cy"] - r, p["cy"] + r]
            elif t == "point":
                xs.append(p["x"]); ys.append(p["y"])
            elif t == "text":
                x, y, L = text_anchor_left(p, sc); xs += [x, x + L]; ys += [y, y + p.get("height", 3.0) * sc]
            elif t == "solid":
                xs += [q[0] for q in p["points"]]; ys += [q[1] for q in p["points"]]
        if not xs:
            x0, y0, x1, y1 = -100, -100, 100, 100
        else:
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    x0 -= w * margin; x1 += w * margin; y0 -= h * margin; y1 += h * margin
    w, h = x1 - x0, y1 - y0

    fig_w_in = width_px / dpi
    fig_h_in = max(fig_w_in * h / w, 1.0)
    if fig_h_in > fig_w_in * 2.5:      # very tall drawings: cap height, keep aspect via limits
        fig_h_in = fig_w_in * 2.5
    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(background); fig.patch.set_facecolor(background)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal", adjustable="datalim"); ax.axis("off")

    if background_image:
        import matplotlib.image as mpimg
        img_path, extent, alpha = background_image
        img = mpimg.imread(img_path)
        ax.imshow(img, extent=extent, alpha=alpha, zorder=0, interpolation="bilinear")
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)

    pt_per_mm = (fig_w_in * 72) / w   # points per real mm at this zoom
    lw_base = 1.1 if overlay_style else 0.6

    # lines grouped by (colour, linetype) into LineCollections
    groups: dict[tuple, list] = {}
    for p, sc in prims:
        if p["type"] == "line":
            groups.setdefault((int(p.get("lc", 1)), int(p.get("lt", 1))), []).append([(p["x1"], p["y1"]), (p["x2"], p["y2"])])
    for (lc, lt), segs in groups.items():
        rgb = tuple(c / 255 for c in pen_rgb(lc, palette))
        dash = LINETYPE_DASHES.get(lt if lt < 10 else lt - 10)
        lw = lw_base * (1.6 if lc == 2 else 1.0)
        col = LineCollection(segs, colors=[rgb], linewidths=lw, linestyles="solid" if dash is None else (0, dash))
        ax.add_collection(col)

    for p, sc in prims:
        t = p["type"]
        rgb = tuple(c / 255 for c in pen_rgb(int(p.get("lc", 1)), palette))
        if t in ("circle", "arc"):
            r = p["r"]; fl = p.get("flatness", 1.0) or 1.0
            if t == "circle":
                th1, th2 = 0.0, 360.0
            else:
                th1, th2 = p["start"], p["end"]
                if th2 < th1:
                    th2 += 360.0
            dash = LINETYPE_DASHES.get(int(p.get("lt", 1)))
            arc = Arc((p["cx"], p["cy"]), 2 * r, 2 * r * fl, angle=p.get("tilt", 0.0), theta1=th1, theta2=th2,
                      edgecolor=rgb, linewidth=lw_base, linestyle="solid" if dash is None else (0, dash))
            ax.add_patch(arc)
        elif t == "point":
            ax.plot([p["x"]], [p["y"]], marker="o", markersize=2.2, color=rgb, linestyle="none")
        elif t == "solid":
            pts = p["points"]
            fc = tuple(c / 255 for c in p["rgb"]) if p.get("rgb") else rgb
            ax.add_patch(Polygon(pts, closed=True, facecolor=fc, edgecolor="none", alpha=0.5))
        elif t == "text" and show_text:
            x, y, L = text_anchor_left(p, sc)
            hmm = p.get("height", 3.0) * sc
            size_pt = max(hmm * pt_per_mm, 1.0)
            if size_pt < 2.0:
                continue   # illegible at this zoom
            ax.text(x, y, p["text"], fontsize=size_pt, rotation=p.get("angle", 0.0), rotation_mode="anchor",
                    ha="left", va="baseline", color=rgb, family=_FONT, clip_on=True)

    if title:
        ax.text(x0 + w * 0.01, y1 - h * 0.01, title, fontsize=9, family=_FONT, ha="left", va="top", color="#444")

    outp = Path(out_png).expanduser()
    outp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(outp), dpi=dpi, facecolor=background)
    plt.close(fig)
    return {"png": str(outp), "bbox_real_mm": [x0, y0, x1, y1], "width_px": width_px,
            "height_px": int(fig_h_in * dpi), "primitives": len(prims), "font": _FONT}
