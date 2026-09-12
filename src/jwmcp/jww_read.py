"""Read .jww files with ezjww and normalise them into jwmcp model entities (real mm)."""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import ezjww

from .model import PAPER_BY_CODE, bbox_of

MAX_BLOCK_DEPTH = 16


class JwwFile:
    def __init__(self, path: str):
        p = Path(path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"{p} not found")
        self.path = str(p)
        self.drawing = ezjww.readfile(self.path)
        doc: dict = self.drawing.jww_document or {}
        self.doc = doc
        self.header: dict = doc.get("header", {})
        groups = self.header.get("layer_groups") or []
        self.group_scales: dict[int, float] = {i: float(g.get("scale") or 1.0) for i, g in enumerate(groups)}
        self.group_names: dict[int, str] = {i: g.get("name", "") for i, g in enumerate(groups)}
        self.layer_names: dict[str, str] = {}
        self.layer_states: dict[str, int] = {}
        for gi, g in enumerate(groups):
            for li, l in enumerate(g.get("layers") or []):
                self.layer_names[f"{gi:X}-{li:X}"] = l.get("name", "")
                self.layer_states[f"{gi:X}-{li:X}"] = int(l.get("state", 0))
        self.block_defs: dict[int, dict] = {int(b["number"]): b for b in doc.get("block_defs", [])}
        self.entities: list[dict] = []
        self._block_stats = Counter()
        for idx, raw in enumerate(doc.get("entities", [])):
            self.entities.extend(self._normalize(raw, idx))

    # ------------------------------------------------------------------
    def scale_of(self, e: dict) -> float:
        return self.group_scales.get(int(e.get("lg", 0)), 1.0)

    @property
    def main_scale(self) -> float:
        """Scale of the layer group holding most entities (the 'drawing scale')."""
        c = Counter(self.scale_of(e) for e in self.entities)
        return c.most_common(1)[0][0] if c else 1.0

    def unified_entities(self, main_scale: float | None = None) -> list[dict]:
        """Entities rescaled into one real-mm space (main scale), for previews / DXF with mixed-scale groups."""
        from .model import rescale_prim
        ms = main_scale or self.main_scale
        out = []
        for e in self.entities:
            sc = self.scale_of(e)
            k = ms / sc
            if k == 1.0:
                out.append(e); continue
            q = rescale_prim(e, k)
            if e["type"] == "dimfigure" and e.get("value_text"):
                vt = dict(e["value_text"]); vt["x"] *= k; vt["y"] *= k; q["value_text"] = vt
            out.append(q)
        return out

    def _base(self, raw: dict, idx: int | str) -> dict:
        b = raw.get("base") or {}
        return {"id": f"j{idx}", "lg": int(b.get("layer_group", 0)), "ly": int(b.get("layer", 0)),
                "lc": int(b.get("pen_color", 1)), "lt": int(b.get("pen_style", 1)), "flag": int(b.get("flag", 0))}

    def _normalize(self, raw: dict, idx: int | str, xf=None, depth: int = 0) -> list[dict]:
        """xf: optional (ox, oy, sx, sy, rot_rad) transform applied in paper space for block children."""
        t = raw.get("type", "")
        base = self._base(raw, idx)
        s = self.group_scales.get(base["lg"], 1.0)

        def P(x: float, y: float) -> tuple[float, float]:
            if xf:
                ox, oy, sx, sy, rot = xf
                x, y = x * sx, y * sy
                c, si = math.cos(rot), math.sin(rot)
                x, y = ox + x * c - y * si, oy + x * si + y * c
            return (x * s, y * s)

        rot_deg = math.degrees(xf[4]) if xf else 0.0
        out: list[dict] = []
        if t == "LINE":
            x1, y1 = P(raw["start_x"], raw["start_y"]); x2, y2 = P(raw["end_x"], raw["end_y"])
            out.append({**base, "type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        elif t in ("ARC", "CIRCLE"):
            cx, cy = P(raw["center_x"], raw["center_y"])
            r = float(raw.get("radius", 0.0)) * s * (abs(xf[2]) if xf else 1.0)
            fl = float(raw.get("flatness", 1.0) or 1.0)
            tilt = math.degrees(float(raw.get("tilt_angle", 0.0))) + rot_deg
            if raw.get("is_full_circle") or t == "CIRCLE":
                e = {**base, "type": "circle", "cx": cx, "cy": cy, "r": r, "flatness": fl, "tilt": tilt}
            else:
                st = math.degrees(float(raw.get("start_angle", 0.0))) + rot_deg
                en = st + math.degrees(float(raw.get("arc_angle", 0.0)))
                e = {**base, "type": "arc", "cx": cx, "cy": cy, "r": r, "start": st, "end": en, "flatness": fl, "tilt": tilt}
            out.append(e)
        elif t == "TEXT":
            out.append(self._text(raw, base, P, rot_deg))
        elif t == "POINT":
            x, y = P(raw["x"], raw["y"])
            e = {**base, "type": "point", "x": x, "y": y}
            if raw.get("is_temporary"):
                e["temporary"] = True
            if raw.get("code"):
                e["code"] = int(raw["code"]); e["angle"] = float(raw.get("angle", 0.0)); e["scale"] = float(raw.get("scale", 1.0))
            out.append(e)
        elif t == "SOLID":
            pts = [P(raw[f"point{i}_x"], raw[f"point{i}_y"]) for i in (1, 2, 3, 4)]
            pts = [pts[0], pts[1], pts[2], pts[3]]
            e = {**base, "type": "solid", "points": [list(p) for p in pts]}
            if raw.get("color") is not None and base["lc"] == 10:
                v = int(raw["color"]); e["rgb"] = [v & 255, (v >> 8) & 255, (v >> 16) & 255]
            out.append(e)
        elif t == "DIMENSION":
            ln = raw.get("line") or {}
            tx = raw.get("text") or {}
            x1, y1 = P(ln.get("start_x", 0), ln.get("start_y", 0)); x2, y2 = P(ln.get("end_x", 0), ln.get("end_y", 0))
            e = {**base, "type": "dimfigure", "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            if tx:
                te = self._text(tx, base, P, rot_deg)
                e["text"] = te["text"]; e["value_text"] = {k: te[k] for k in ("x", "y", "height", "width", "angle", "spacing") if k in te}
            out.append(e)
        elif t == "BLOCK":
            n = int(raw.get("def_number", -1))
            bd = self.block_defs.get(n)
            ox, oy = float(raw.get("ref_x", 0.0)), float(raw.get("ref_y", 0.0))
            sx, sy = float(raw.get("scale_x", 1.0) or 1.0), float(raw.get("scale_y", 1.0) or 1.0)
            rot = float(raw.get("rotation", 0.0))
            if bd is None or depth >= MAX_BLOCK_DEPTH:
                self._block_stats["unresolved"] += 1
                return out
            # compose with the outer transform (paper space)
            if xf:
                pox, poy = P(ox, oy)
                pox, poy = pox / s, poy / s
                sx, sy, rot = sx * xf[2], sy * xf[3], rot + xf[4]
                ox, oy = pox, poy
            name = raw.get("block_name") or bd.get("name") or f"block{n}"
            for ci, child in enumerate(bd.get("entities", [])):
                for ce in self._normalize(child, f"{idx}b{ci}", (ox, oy, sx, sy, rot), depth + 1):
                    ce["block"] = name
                    ce["lg"], ce["ly"] = base["lg"], base["ly"]   # references live on the reference's layer
                    out.append(ce)
            self._block_stats["expanded"] += 1
        else:
            self._block_stats[f"skipped:{t}"] += 1
        return out

    def _text(self, raw: dict, base: dict, P, rot_deg: float) -> dict:
        x, y = P(raw.get("start_x", 0), raw.get("start_y", 0))
        ex, ey = P(raw.get("end_x", 0), raw.get("end_y", 0))
        tt = int(raw.get("text_type", 0) or 0)
        style = []
        if tt >= 20000:
            style.append("bold"); tt -= 20000
        if tt >= 10000:
            style.append("italic"); tt -= 10000
        e = {**base, "type": "text", "x": x, "y": y, "text": str(raw.get("content", "")),
             "height": float(raw.get("size_y", 3.0)), "width": float(raw.get("size_x", 3.0)),
             "spacing": float(raw.get("spacing", 0.0)), "angle": float(raw.get("angle", 0.0)) + rot_deg,
             "align": "left", "kind": "ch", "extent": [ex - x, ey - y]}
        if tt:
            e["cn"] = tt
        if raw.get("font_name"):
            e["font"] = raw["font_name"]
        if style:
            e["style"] = style
        if base.get("flag", 0) & 0x0010:
            e["kind"] = "cs"
        if base.get("flag", 0) & 0x0020:
            e["kind"] = "cv"
        return e

    # ------------------------------------------------------------------
    def summary(self) -> dict:
        h = self.header
        by_type = Counter(e["type"] for e in self.entities)
        by_layer = Counter(f"{e['lg']:X}-{e['ly']:X}" for e in self.entities)
        by_group = Counter(f"{e['lg']:X}" for e in self.entities)
        groups = []
        for gi in range(16):
            cnt = by_group.get(f"{gi:X}", 0)
            layers = {k: {"name": self.layer_names.get(k, ""), "count": by_layer.get(k, 0), "state": self.layer_states.get(k, 0)}
                      for k in (f"{gi:X}-{li:X}" for li in range(16)) if by_layer.get(k, 0) or self.layer_names.get(k, "")}
            if cnt or self.group_names.get(gi) not in (None, "", f"Group{gi}") or gi == 0:
                groups.append({"lg": f"{gi:X}", "name": self.group_names.get(gi, ""), "scale": self.group_scales.get(gi),
                               "entity_count": cnt, "layers": layers})
        texts = [e["text"] for e in self.entities if e["type"] == "text"]
        return {
            "path": self.path, "size_bytes": os.path.getsize(self.path),
            "jww_version": h.get("version"), "memo": h.get("memo", ""),
            "paper": PAPER_BY_CODE.get(int(h.get("paper_size", 3)), str(h.get("paper_size"))),
            "write_layer_group": h.get("write_layer_group"),
            "entity_count": len(self.entities), "by_type": dict(by_type),
            "groups": groups,
            "blocks": {"definitions": len(self.block_defs), **dict(self._block_stats)},
            "bbox_real_mm": bbox_of(self.entities, self.scale_of),
            "text_sample": texts[:40], "text_count": len(texts),
            "diagnostics": self.doc.get("diagnostics", [])[:10],
        }

    def query(self, *, types: list[str] | None = None, lg: int | None = None, ly: int | None = None,
              bbox: list[float] | None = None, pattern: str | None = None, limit: int = 500, offset: int = 0) -> dict:
        rx = re.compile(pattern) if pattern else None
        sel = []
        for e in self.entities:
            if types and e["type"] not in types:
                continue
            if lg is not None and e["lg"] != lg:
                continue
            if ly is not None and e["ly"] != ly:
                continue
            if rx and not (e["type"] == "text" and rx.search(e["text"])):
                continue
            if bbox:
                from .model import entity_bbox
                b = entity_bbox(e, self.scale_of(e)) if e["type"] != "dimfigure" else (min(e["x1"], e["x2"]), min(e["y1"], e["y2"]), max(e["x1"], e["x2"]), max(e["y1"], e["y2"]))
                if not b or b[2] < bbox[0] or b[0] > bbox[2] or b[3] < bbox[1] or b[1] > bbox[3]:
                    continue
            sel.append(e)
        total = len(sel)
        page = sel[offset: offset + limit]
        return {"total": total, "offset": offset, "returned": len(page), "entities": page}


_cache: dict[tuple[str, float], JwwFile] = {}


def load(path: str) -> JwwFile:
    p = str(Path(path).expanduser())
    key = (p, os.path.getmtime(p))
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = JwwFile(p)
    return _cache[key]


def to_dxf(path: str, out: str, version: str = "AC1024") -> dict:
    d = ezjww.readfile(str(Path(path).expanduser()))
    outp = Path(out).expanduser()
    outp.parent.mkdir(parents=True, exist_ok=True)
    d.saveas(str(outp), target_version=version)
    return {"dxf": str(outp), "size_bytes": outp.stat().st_size}
