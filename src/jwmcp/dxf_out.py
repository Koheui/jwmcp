"""DXF export of model entities with ezdxf (Jw_cad can open DXF directly: ファイル > 開く > DXF)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Iterable

import logging

import ezdxf
from ezdxf.enums import TextEntityAlignment

logging.getLogger("ezdxf").setLevel(logging.WARNING)

from .model import LINETYPE_DXF, PAPER_SIZES_MM, PEN_ACI, primitives, text_anchor_left


def layer_name(lg: int, ly: int, names: dict[str, str] | None) -> str:
    key = f"{lg:X}-{ly:X}"
    nm = (names or {}).get(key, "")
    nm = "".join(ch for ch in nm if ch not in '<>/\\":;?*|=`')
    return f"{lg:X}{ly:X}_{nm}" if nm else f"{lg:X}{ly:X}"


def write_dxf(entities: Iterable[dict], out: str, *, scale_for: Callable[[dict], float],
              layer_names: dict[str, str] | None = None, version: str = "R2000",
              paper: str | None = None, main_scale: float | None = None) -> dict:
    """Write a DXF that Jw_cad opens at the right scale.

    Jw_cad has no scale in DXF; with 基本設定「図面範囲を読取る」 it derives paper/scale from the header
    extents, so $EXTMIN/$EXTMAX must be the real drawing extents (ezdxf's default is an invalid sentinel
    that makes Jw_cad pick an absurd scale). R2000 + Shift_JIS keeps Japanese text readable in Jw_cad.
    """
    doc = ezdxf.new(version, setup=True)
    doc.units = ezdxf.units.MM
    if doc.dxfversion < "AC1021":       # pre-2007: text is written in the code page below
        doc.encoding = "cp932"
        doc.header["$DWGCODEPAGE"] = "ANSI_932"
    msp = doc.modelspace()
    layers_made: set[str] = set()
    count = 0
    xs: list[float] = []
    ys: list[float] = []

    def track(*pts):
        for x, y in pts:
            xs.append(float(x)); ys.append(float(y))

    def ensure_layer(p: dict) -> str:
        nm = layer_name(int(p.get("lg", 0)), int(p.get("ly", 0)), layer_names)
        if nm not in layers_made:
            if nm not in doc.layers:
                doc.layers.add(nm, color=PEN_ACI.get(int(p.get("lc", 1)), 7))
            layers_made.add(nm)
        return nm

    def attribs(p: dict) -> dict:
        lt = int(p.get("lt", 1))
        lt = lt - 10 if lt > 10 else lt
        return {"layer": ensure_layer(p), "color": PEN_ACI.get(int(p.get("lc", 1)), 7),
                "linetype": LINETYPE_DXF.get(lt, "CONTINUOUS")}

    for e in entities:
        sc = scale_for(e)
        if e.get("type") == "dimfigure":
            msp.add_line((e["x1"], e["y1"]), (e["x2"], e["y2"]), dxfattribs=attribs(e)); count += 1
            track((e["x1"], e["y1"]), (e["x2"], e["y2"]))
            vt = e.get("value_text")
            if vt and e.get("text"):
                h = vt.get("height", 3.0) * sc
                msp.add_text(e["text"], height=h, dxfattribs={**attribs(e), "rotation": vt.get("angle", 0.0),
                             "width": vt.get("width", vt.get("height", 3.0)) / max(vt.get("height", 3.0), 1e-9)}
                             ).set_placement((vt["x"], vt["y"]), align=TextEntityAlignment.LEFT)
                count += 1
            continue
        if e.get("type") in ("block", "solid_circle"):
            continue
        for p in primitives(e, sc):
            t = p["type"]; a = attribs(p)
            if t == "line":
                msp.add_line((p["x1"], p["y1"]), (p["x2"], p["y2"]), dxfattribs=a)
                track((p["x1"], p["y1"]), (p["x2"], p["y2"]))
            elif t in ("circle", "arc"):
                fl = p.get("flatness", 1.0) or 1.0
                tilt = p.get("tilt", 0.0)
                rr = p["r"] * max(1.0, fl)
                track((p["cx"] - rr, p["cy"] - rr), (p["cx"] + rr, p["cy"] + rr))
                if abs(fl - 1.0) < 1e-9:
                    if t == "circle":
                        msp.add_circle((p["cx"], p["cy"]), p["r"], dxfattribs=a)
                    else:
                        msp.add_arc((p["cx"], p["cy"]), p["r"], p["start"] + tilt, p["end"] + tilt, dxfattribs=a)
                else:
                    major = (p["r"] * math.cos(math.radians(tilt)), p["r"] * math.sin(math.radians(tilt)))
                    if t == "circle":
                        sp, ep = 0.0, math.tau
                    else:
                        sp, ep = math.radians(p["start"]), math.radians(p["end"])
                    msp.add_ellipse((p["cx"], p["cy"]), major_axis=major, ratio=min(fl, 1.0) if fl <= 1 else 1 / fl,
                                    start_param=sp, end_param=ep, dxfattribs=a)
            elif t == "point":
                msp.add_point((p["x"], p["y"]), dxfattribs=a)
                track((p["x"], p["y"]))
            elif t == "solid":
                pts = p["points"]
                if len(pts) == 3:
                    pts = pts + [pts[2]]
                # DXF SOLID vertex order is 1,2,4,3
                msp.add_solid([pts[0], pts[1], pts[3], pts[2]], dxfattribs=a)
                track(*pts)
            elif t == "text":
                x, y, L = text_anchor_left(p, sc)
                h = p.get("height", 3.0) * sc
                wf = p.get("width", p.get("height", 3.0)) / max(p.get("height", 3.0), 1e-9)
                msp.add_text(p["text"], height=h, dxfattribs={**a, "rotation": p.get("angle", 0.0), "width": wf}
                             ).set_placement((x, y), align=TextEntityAlignment.LEFT)
                track((x, y), (x + L, y + h))
            count += 1

    # Header extents: what Jw_cad uses to pick paper size / scale (基本設定「図面範囲を読取る」).
    if paper and main_scale and paper in PAPER_SIZES_MM:
        W, H = PAPER_SIZES_MM[paper]
        ext = ((-W / 2 * main_scale, -H / 2 * main_scale), (W / 2 * main_scale, H / 2 * main_scale))
    elif xs:
        ext = ((min(xs), min(ys)), (max(xs), max(ys)))
    else:
        ext = ((0.0, 0.0), (420.0, 297.0))
    # ezdxf syncs the header $EXTMIN/$EXTMAX/$LIMMIN/$LIMMAX from the modelspace layout on export,
    # so they must be set on the layout (setting the header vars alone is overwritten with sentinels).
    msp.reset_extents((ext[0][0], ext[0][1], 0.0), (ext[1][0], ext[1][1], 0.0))
    msp.reset_limits(ext[0], ext[1])
    doc.header["$EXTMIN"] = (ext[0][0], ext[0][1], 0.0)
    doc.header["$EXTMAX"] = (ext[1][0], ext[1][1], 0.0)
    doc.header["$LIMMIN"] = ext[0]
    doc.header["$LIMMAX"] = ext[1]

    outp = Path(out).expanduser()
    outp.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(outp))
    return {"dxf": str(outp), "entities": count, "layers": sorted(layers_made), "size_bytes": outp.stat().st_size,
            "dxf_version": doc.dxfversion, "encoding": doc.encoding, "extents": ext,
            "paper": paper, "scale": f"1/{main_scale:g}" if main_scale else None,
            "jw_cad_hint": "Jw_cad: 基本設定 > DXF・SXF・JWC の「図面範囲を読取る」を OFF にし、新規図面で用紙と縮尺を上の paper/scale に"
                           "合わせてから DXF を開く（DXF には縮尺が無く、座標は実寸 mm）"}
