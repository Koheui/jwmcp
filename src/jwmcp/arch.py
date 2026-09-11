"""Architectural / MEP elements that expand into Jw_cad primitives.

Entity schemas (all coordinates real mm; text sizes paper mm):

  wall      {"type":"wall","points":[[x,y],...],"thickness":150,"closed":false,
             "core":true,"core_ly":1,"core_lc":1,"core_extend":300,
             "openings":[{"at":1000,"width":1800,"kind":"door","hinge":"start","side":"+","frame":25}],
             "opening_lg":3,"opening_ly":0,"opening_lc":1}
             at = distance along the centre line from its first point. kind: door | double_door |
             sliding | window | fixed | opening.  side "+" = left of travel direction.
  grid      {"type":"grid","xs":[0,3640],"ys":[0,2730],"x_labels":["X1","X2"],"y_labels":["Y1","Y2"],
             "extend":1500,"bubble":4,"label_height":3,"dims":false,"dim_offset":2500}
  column    {"type":"column","cx","cy","w":600,"h":600,"angle":0,"hatch":true}
  room      {"type":"room","x","y","name":"和室","height":5,"note":"6帖","note_height":3}
  pipe      {"type":"pipe","points":[[x,y],...],"system":"給水","diameter":"25A","label":true,"label_height":2.5}
  equipment {"type":"equipment","kind":"toilet","x","y","angle":0,"w","h","label":"WC"}
"""
from __future__ import annotations

import math
from typing import Iterable

ARCH_TYPES = {"wall", "grid", "column", "room", "pipe", "equipment"}

OPENING_KINDS = {"door", "double_door", "sliding", "window", "fixed", "opening"}

# Jw_cad 線色/線種 conventions per piping system (editable by the caller per entity)
PIPE_SYSTEMS = {
    "給水": {"lc": 6, "lt": 1, "tag": "W"},    # 青 実線
    "給湯": {"lc": 8, "lt": 1, "tag": "H"},    # 赤 実線
    "排水": {"lc": 2, "lt": 1, "tag": "D"},    # 黒 実線 (太)
    "汚水": {"lc": 2, "lt": 1, "tag": "S"},
    "雑排水": {"lc": 2, "lt": 2, "tag": "W"},
    "通気": {"lc": 3, "lt": 3, "tag": "V"},    # 緑 点線
    "ガス": {"lc": 4, "lt": 5, "tag": "G"},    # 黄 一点鎖
    "冷媒": {"lc": 5, "lt": 1, "tag": "R"},    # 紫
    "ドレン": {"lc": 5, "lt": 3, "tag": "DR"},
    "給気": {"lc": 6, "lt": 1, "tag": "SA"},
    "排気": {"lc": 8, "lt": 1, "tag": "EA"},
    "換気": {"lc": 3, "lt": 1, "tag": "EA"},
    "ダクト": {"lc": 7, "lt": 1, "tag": "DUCT"},
    "消火": {"lc": 8, "lt": 6, "tag": "F"},
}

EQUIPMENT_DEFAULT_SIZE = {
    "toilet": (450, 750), "sink": (600, 500), "washbasin": (500, 450), "bath": (1600, 800),
    "kitchen": (1800, 650), "ac_indoor": (900, 250), "ac_outdoor": (800, 300), "fan": (300, 300),
    "cubicle": (2000, 1500), "tank": (1000, 1000), "boiler": (500, 500), "elevator": (1800, 2000),
    "box": (500, 500),
}


class ArchError(ValueError):
    pass


def _f(d, k, default=None):
    v = d.get(k, default)
    if v is None:
        raise ArchError(f"'{k}' is required for {d.get('type')}")
    return float(v)


def normalize_arch(d: dict, out: dict) -> dict:
    """Fill / validate arch-specific fields. `out` already has id/type/lg/ly/lc/lt."""
    t = out["type"]
    if t == "wall":
        pts = d.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            raise ArchError("wall needs 'points': [[x,y],...] (centre line, 2+ points)")
        out["points"] = [[float(p[0]), float(p[1])] for p in pts]
        out["thickness"] = _f(d, "thickness", 150.0)
        out["closed"] = bool(d.get("closed", False))
        out["core"] = bool(d.get("core", False))
        out["core_ly"] = int(d.get("core_ly", out["ly"]))
        out["core_lc"] = int(d.get("core_lc", 1))
        out["core_lt"] = int(d.get("core_lt", 5))
        out["core_extend"] = _f(d, "core_extend", 0.0)
        out["opening_lg"] = int(str(d.get("opening_lg", out["lg"])), 16) if isinstance(d.get("opening_lg"), str) else int(d.get("opening_lg", out["lg"]))
        out["opening_ly"] = int(str(d.get("opening_ly", out["ly"])), 16) if isinstance(d.get("opening_ly"), str) else int(d.get("opening_ly", out["ly"]))
        out["opening_lc"] = int(d.get("opening_lc", 1))
        ops = []
        for o in d.get("openings") or []:
            kind = str(o.get("kind", "door")).lower()
            if kind not in OPENING_KINDS:
                raise ArchError(f"opening kind must be one of {sorted(OPENING_KINDS)}")
            ops.append({"at": _f(o, "at"), "width": _f(o, "width", 800.0), "kind": kind,
                        "hinge": str(o.get("hinge", "start")), "side": str(o.get("side", "+")),
                        "frame": float(o.get("frame", 0.0)), "label": o.get("label")})
        out["openings"] = ops
    elif t == "grid":
        out["xs"] = [float(v) for v in d.get("xs") or []]
        out["ys"] = [float(v) for v in d.get("ys") or []]
        if not out["xs"] and not out["ys"]:
            raise ArchError("grid needs xs and/or ys")
        out["x_labels"] = [str(s) for s in (d.get("x_labels") or [f"X{i+1}" for i in range(len(out["xs"]))])]
        out["y_labels"] = [str(s) for s in (d.get("y_labels") or [f"Y{i+1}" for i in range(len(out["ys"]))])]
        out["extend"] = _f(d, "extend", 1500.0)
        out["bubble"] = _f(d, "bubble", 4.0)
        out["label_height"] = _f(d, "label_height", 3.0)
        out["dims"] = bool(d.get("dims", False))
        out["dim_offset"] = _f(d, "dim_offset", 2500.0)
        out["dim_height"] = _f(d, "dim_height", 3.0)
        if d.get("bounds"):
            out["bounds"] = [float(v) for v in d["bounds"]]
        out.setdefault("lt", 5)
    elif t == "column":
        out["cx"] = _f(d, "cx"); out["cy"] = _f(d, "cy")
        out["w"] = _f(d, "w", 600.0); out["h"] = _f(d, "h", out["w"])
        out["angle"] = _f(d, "angle", 0.0)
        out["hatch"] = bool(d.get("hatch", True))
    elif t == "room":
        out["x"] = _f(d, "x"); out["y"] = _f(d, "y")
        out["name"] = str(d.get("name") or d.get("text") or "")
        if not out["name"]:
            raise ArchError("room needs 'name'")
        out["height"] = _f(d, "height", 5.0)
        out["note"] = str(d["note"]) if d.get("note") else None
        out["note_height"] = _f(d, "note_height", 3.0)
    elif t == "pipe":
        pts = d.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            raise ArchError("pipe needs 'points' with 2+ points")
        out["points"] = [[float(p[0]), float(p[1])] for p in pts]
        sys_ = str(d.get("system", "給水"))
        out["system"] = sys_
        conv = PIPE_SYSTEMS.get(sys_, {"lc": out["lc"], "lt": out["lt"], "tag": sys_})
        if "lc" not in d:
            out["lc"] = conv["lc"]
        if "lt" not in d:
            out["lt"] = conv["lt"]
        out["diameter"] = str(d["diameter"]) if d.get("diameter") else None
        out["label"] = bool(d.get("label", True))
        out["label_height"] = _f(d, "label_height", 2.5)
        out["label_offset"] = _f(d, "label_offset", 1.5)
    elif t == "equipment":
        kind = str(d.get("kind", "box")).lower()
        out["kind"] = kind
        out["x"] = _f(d, "x"); out["y"] = _f(d, "y")
        w0, h0 = EQUIPMENT_DEFAULT_SIZE.get(kind, (500, 500))
        out["w"] = _f(d, "w", w0); out["h"] = _f(d, "h", h0)
        out["angle"] = _f(d, "angle", 0.0)
        out["label"] = str(d["label"]) if d.get("label") else None
        out["label_height"] = _f(d, "label_height", 2.5)
    return out


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------

def _attrs(e, **override):
    a = {k: e[k] for k in ("lg", "ly", "lc", "lt") if k in e}
    a.update(override)
    return a


def _line(x1, y1, x2, y2, a, **extra):
    return {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, **a, **extra}


def _isect(p, u, q, v):
    """Intersection of lines p + s*u and q + t*v; None if parallel."""
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-9:
        return None
    w = (q[0] - p[0], q[1] - p[1])
    s = (w[0] * v[1] - w[1] * v[0]) / den
    return (p[0] + u[0] * s, p[1] + u[1] * s)


def _text(x, y, s, h, ang, a, align="left", kind="ch", **extra):
    return {"type": "text", "x": x, "y": y, "text": s, "height": h, "width": h, "spacing": 0.0,
            "angle": ang, "align": align, "kind": kind, **a, **extra}


def arch_primitives(e: dict, scale: float) -> Iterable[dict]:
    t = e["type"]
    if t == "wall":
        yield from _wall(e, scale)
    elif t == "grid":
        yield from _grid(e, scale)
    elif t == "column":
        yield from _column(e)
    elif t == "room":
        a = _attrs(e)
        yield _text(e["x"], e["y"], e["name"], e["height"], 0.0, a, align="center")
        if e.get("note"):
            yield _text(e["x"], e["y"] - (e["height"] + 1.5) * scale, e["note"], e["note_height"], 0.0, a, align="center")
    elif t == "pipe":
        yield from _pipe(e, scale)
    elif t == "equipment":
        yield from _equipment(e, scale)
    else:
        raise ArchError(f"unknown arch type {t}")


# ---- wall -------------------------------------------------------------------

def _wall(e: dict, scale: float) -> Iterable[dict]:
    pts = [tuple(p) for p in e["points"]]
    if e["closed"] and pts[0] != pts[-1]:
        pts.append(pts[0])
    n_seg = len(pts) - 1
    if n_seg < 1:
        raise ArchError("wall needs at least one segment")
    half = e["thickness"] / 2.0
    a = _attrs(e)
    segs = []
    for i in range(n_seg):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-9:
            continue
        u = ((x2 - x1) / L, (y2 - y1) / L)
        n = (-u[1], u[0])
        segs.append({"p": (x1, y1), "q": (x2, y2), "u": u, "n": n, "L": L, "start": 0.0})
    if not segs:
        raise ArchError("wall points coincide")
    acc = 0.0
    for s in segs:
        s["start"] = acc
        acc += s["L"]
    total = acc
    closed = e["closed"] and len(segs) >= 3

    # corner points on each side (miter)
    def offset_pt(s, key, sign):
        base = s[key]
        return (base[0] + s["n"][0] * sign * half, base[1] + s["n"][1] * sign * half)

    for sign, key in ((+1, "plus"), (-1, "minus")):
        for i, s in enumerate(segs):
            prev_s = segs[i - 1] if (i > 0 or closed) else None
            next_s = segs[(i + 1) % len(segs)] if (i < len(segs) - 1 or closed) else None
            start = offset_pt(s, "p", sign)
            end = offset_pt(s, "q", sign)
            if prev_s is not None:
                c = _isect(offset_pt(prev_s, "p", sign), prev_s["u"], start, s["u"])
                if c is not None:
                    start = c
            if next_s is not None:
                c = _isect(start, s["u"], offset_pt(next_s, "p", sign), next_s["u"])
                if c is not None:
                    end = c
            s[key] = (start, end)

    # openings per segment: list of (o1, o2, opening)
    per_seg: dict[int, list] = {}
    for o in e["openings"]:
        at, w = o["at"], o["width"]
        if at < 0 or at + w > total + 1e-6:
            raise ArchError(f"opening at {at} width {w} exceeds wall length {total:.0f}")
        for i, s in enumerate(segs):
            if s["start"] - 1e-6 <= at < s["start"] + s["L"] - 1e-6:
                o1 = at - s["start"]
                if o1 + w > s["L"] + 1e-6:
                    raise ArchError(f"opening at {at} crosses a wall corner")
                per_seg.setdefault(i, []).append((o1, o1 + w, o))
                break

    oa = {"lg": e["opening_lg"], "ly": e["opening_ly"], "lc": e["opening_lc"], "lt": 1}
    for i, s in enumerate(segs):
        p, u, n = s["p"], s["u"], s["n"]

        def P(d, side):  # point at distance d along seg, offset side*half
            return (p[0] + u[0] * d + n[0] * side * half, p[1] + u[1] * d + n[1] * side * half)

        for key, sign in (("plus", +1), ("minus", -1)):
            (sx, sy), (ex, ey) = s[key]
            # parameters of the corner points along the segment
            ta = (sx - p[0]) * u[0] + (sy - p[1]) * u[1]
            tb = (ex - p[0]) * u[0] + (ey - p[1]) * u[1]
            cuts = sorted(per_seg.get(i, []), key=lambda c: c[0])
            cur = ta
            pieces = []
            for o1, o2, o in cuts:
                pieces.append((cur, o1)); cur = o2
            pieces.append((cur, tb))
            for c1, c2 in pieces:
                if c2 - c1 > 1e-6:
                    x1, y1 = P(c1, sign); x2, y2 = P(c2, sign)
                    yield _line(x1, y1, x2, y2, a)
        # end caps for open walls
        if not closed:
            if i == 0:
                (sx, sy), _ = s["plus"]; (mx, my), _ = s["minus"]
                yield _line(sx, sy, mx, my, a)
            if i == len(segs) - 1:
                _, (ex, ey) = s["plus"]; _, (mx, my) = s["minus"]
                yield _line(ex, ey, mx, my, a)
        # openings
        for o1, o2, o in per_seg.get(i, []):
            fr = o["frame"]
            for d in (o1, o2):
                x1, y1 = P(d, +1); x2, y2 = P(d, -1)
                if fr:
                    x1, y1 = x1 + n[0] * fr, y1 + n[1] * fr
                    x2, y2 = x2 - n[0] * fr, y2 - n[1] * fr
                yield _line(x1, y1, x2, y2, oa)
            w = o2 - o1
            side = 1.0 if o["side"] == "+" else -1.0
            kind = o["kind"]
            if kind == "door":
                hinge_d, other_d = (o1, o2) if o["hinge"] == "start" else (o2, o1)
                hx, hy = P(hinge_d, side)
                lx, ly_ = hx + n[0] * side * w, hy + n[1] * side * w
                yield _line(hx, hy, lx, ly_, oa)
                a_leaf = math.degrees(math.atan2(n[1] * side, n[0] * side))
                dir_to_other = 1.0 if other_d > hinge_d else -1.0
                a_wall = math.degrees(math.atan2(u[1] * dir_to_other, u[0] * dir_to_other))
                st, en = (a_wall, a_leaf) if ((a_leaf - a_wall) % 360) <= 180 else (a_leaf, a_wall)
                yield {"type": "arc", "cx": hx, "cy": hy, "r": w, "start": st, "end": en, "flatness": 1.0, "tilt": 0.0, **oa}
            elif kind == "double_door":
                for hinge_d, dir_ in ((o1, 1.0), (o2, -1.0)):
                    hx, hy = P(hinge_d, side)
                    lx, ly_ = hx + n[0] * side * w / 2, hy + n[1] * side * w / 2
                    yield _line(hx, hy, lx, ly_, oa)
                    a_leaf = math.degrees(math.atan2(n[1] * side, n[0] * side))
                    a_wall = math.degrees(math.atan2(u[1] * dir_, u[0] * dir_))
                    st, en = (a_wall, a_leaf) if ((a_leaf - a_wall) % 360) <= 180 else (a_leaf, a_wall)
                    yield {"type": "arc", "cx": hx, "cy": hy, "r": w / 2, "start": st, "end": en, "flatness": 1.0, "tilt": 0.0, **oa}
            elif kind in ("sliding", "window"):
                off = half / 2
                ov = min(50.0, w * 0.05)
                x1, y1 = P(o1, 0); x1, y1 = x1 + n[0] * off, y1 + n[1] * off
                x2, y2 = P(o1 + w / 2 + ov, 0); x2, y2 = x2 + n[0] * off, y2 + n[1] * off
                yield _line(x1, y1, x2, y2, oa)
                x1, y1 = P(o2 - w / 2 - ov, 0); x1, y1 = x1 - n[0] * off, y1 - n[1] * off
                x2, y2 = P(o2, 0); x2, y2 = x2 - n[0] * off, y2 - n[1] * off
                yield _line(x1, y1, x2, y2, oa)
                if kind == "window":
                    for sgn in (+1, -1):
                        x1, y1 = P(o1, sgn); x2, y2 = P(o2, sgn)
                        yield _line(x1, y1, x2, y2, {**oa, "lt": 1})
            elif kind == "fixed":
                x1, y1 = P(o1, 0); x2, y2 = P(o2, 0)
                yield _line(x1, y1, x2, y2, oa)
                for sgn in (+1, -1):
                    x1, y1 = P(o1, sgn); x2, y2 = P(o2, sgn)
                    yield _line(x1, y1, x2, y2, oa)
            if o.get("label"):
                mx, my = P((o1 + o2) / 2, 0)
                yield _text(mx + n[0] * side * (w + 200), my + n[1] * side * (w + 200), str(o["label"]), 2.5,
                            math.degrees(math.atan2(u[1], u[0])), oa, align="center")

    if e["core"]:
        ca = {"lg": e["lg"], "ly": e["core_ly"], "lc": e["core_lc"], "lt": e["core_lt"]}
        ext = e["core_extend"]
        for i, s in enumerate(segs):
            p, q, u = s["p"], s["q"], s["u"]
            x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
            if not closed and i == 0:
                x1, y1 = x1 - u[0] * ext, y1 - u[1] * ext
            if not closed and i == len(segs) - 1:
                x2, y2 = x2 + u[0] * ext, y2 + u[1] * ext
            yield _line(x1, y1, x2, y2, ca, core=True)


# ---- grid -------------------------------------------------------------------

def _grid(e: dict, scale: float) -> Iterable[dict]:
    a = _attrs(e)
    xs, ys = e["xs"], e["ys"]
    ext = e["extend"]
    r = e["bubble"] * scale
    if e.get("bounds"):
        x0, y0, x1, y1 = e["bounds"]
    else:
        x0 = min(xs) if xs else min(ys); x1 = max(xs) if xs else max(ys)
        y0 = min(ys) if ys else min(xs); y1 = max(ys) if ys else max(xs)
        if not xs:
            x0, x1 = x0, x1
    ta = {**a, "lt": 1}
    for x, lab in zip(xs, e["x_labels"]):
        yield _line(x, y0 - ext, x, y1 + ext, a, grid=True)
        cy = y0 - ext - r
        yield {"type": "circle", "cx": x, "cy": cy, "r": r, "flatness": 1.0, "tilt": 0.0, **ta}
        yield _text(x, cy - e["label_height"] * scale / 2, lab, e["label_height"], 0.0, ta, align="center")
    for y, lab in zip(ys, e["y_labels"]):
        yield _line(x0 - ext, y, x1 + ext, y, a, grid=True)
        cx = x0 - ext - r
        yield {"type": "circle", "cx": cx, "cy": y, "r": r, "flatness": 1.0, "tilt": 0.0, **ta}
        yield _text(cx, y - e["label_height"] * scale / 2, lab, e["label_height"], 0.0, ta, align="center")
    if e["dims"]:
        from .model import _dimension_primitives
        off = e["dim_offset"]
        for xa, xb in zip(xs, xs[1:]):
            d = {"type": "dimension", "x1": xa, "y1": y0, "x2": xb, "y2": y0, "offset": -off, "extension": 2.0, "gap": 0.0,
                 "text_height": e["dim_height"], "text_gap": 1.0, "decimals": 0, "comma": True, "endpoints": "point", **ta}
            yield from _dimension_primitives(d, scale)
        for ya, yb in zip(ys, ys[1:]):
            d = {"type": "dimension", "x1": x0, "y1": ya, "x2": x0, "y2": yb, "offset": off, "extension": 2.0, "gap": 0.0,
                 "text_height": e["dim_height"], "text_gap": 1.0, "decimals": 0, "comma": True, "endpoints": "point", **ta}
            yield from _dimension_primitives(d, scale)


# ---- column -----------------------------------------------------------------

def _column(e: dict) -> Iterable[dict]:
    a = _attrs(e)
    cx, cy, w, h, ang = e["cx"], e["cy"], e["w"], e["h"], e["angle"]
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def R(x, y):
        return (cx + x * c - y * s, cy + x * s + y * c)

    corners = [R(-w / 2, -h / 2), R(w / 2, -h / 2), R(w / 2, h / 2), R(-w / 2, h / 2)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        yield _line(x1, y1, x2, y2, a)
    if e["hatch"]:
        yield _line(*corners[0], *corners[2], a)
        yield _line(*corners[1], *corners[3], a)


# ---- pipe -------------------------------------------------------------------

def _pipe(e: dict, scale: float) -> Iterable[dict]:
    a = _attrs(e)
    pts = e["points"]
    best = None
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        yield _line(x1, y1, x2, y2, a, pipe=e["system"])
        L = math.hypot(x2 - x1, y2 - y1)
        if best is None or L > best[0]:
            best = (L, x1, y1, x2, y2)
    if e["label"] and best:
        L, x1, y1, x2, y2 = best
        tag = PIPE_SYSTEMS.get(e["system"], {}).get("tag", e["system"])
        label = f"{e['system']} {e['diameter']}" if e.get("diameter") else e["system"]
        label = f"{label}"
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        nx, ny = -uy, ux
        if ang > 90 or ang <= -90:
            ang += 180; nx, ny = -nx, -ny
        off = e["label_offset"] * scale
        mx, my = (x1 + x2) / 2 + nx * off, (y1 + y2) / 2 + ny * off
        yield _text(mx, my, label, e["label_height"], ang, {**a, "lt": 1}, align="center")


# ---- equipment ---------------------------------------------------------------

def _equipment(e: dict, scale: float) -> Iterable[dict]:
    a = _attrs(e)
    cx, cy, w, h, ang = e["x"], e["y"], e["w"], e["h"], e["angle"]
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def R(x, y):
        return (cx + x * c - y * s, cy + x * s + y * c)

    kind = e["kind"]
    corners = [R(-w / 2, -h / 2), R(w / 2, -h / 2), R(w / 2, h / 2), R(-w / 2, h / 2)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        yield _line(x1, y1, x2, y2, a)
    if kind == "toilet":
        ex, ey = R(0, h * 0.15)
        yield {"type": "circle", "cx": ex, "cy": ey, "r": w * 0.38, "flatness": 0.7, "tilt": ang + 90, **a}
    elif kind in ("sink", "washbasin"):
        ex, ey = R(0, 0)
        yield {"type": "circle", "cx": ex, "cy": ey, "r": min(w, h) * 0.32, "flatness": 1.0, "tilt": 0.0, **a}
    elif kind == "bath":
        inner = [R(-w / 2 + 80, -h / 2 + 80), R(w / 2 - 80, -h / 2 + 80), R(w / 2 - 80, h / 2 - 80), R(-w / 2 + 80, h / 2 - 80)]
        for (x1, y1), (x2, y2) in zip(inner, inner[1:] + inner[:1]):
            yield _line(x1, y1, x2, y2, a)
    elif kind == "kitchen":
        ex, ey = R(-w * 0.25, 0)
        yield {"type": "circle", "cx": ex, "cy": ey, "r": h * 0.3, "flatness": 1.0, "tilt": 0.0, **a}
        for dx in (w * 0.15, w * 0.32):
            ex, ey = R(dx, 0)
            yield {"type": "circle", "cx": ex, "cy": ey, "r": h * 0.14, "flatness": 1.0, "tilt": 0.0, **a}
    elif kind in ("ac_indoor", "ac_outdoor", "fan"):
        yield _line(*corners[0], *corners[2], a)
        yield _line(*corners[1], *corners[3], a)
    elif kind in ("cubicle", "tank", "boiler", "elevator"):
        yield _line(*corners[0], *corners[2], a)
        yield _line(*corners[1], *corners[3], a)
    label = e.get("label") or {"toilet": "WC", "sink": "SK", "washbasin": "L", "bath": "BATH", "kitchen": "K",
                               "ac_indoor": "AC", "ac_outdoor": "OU", "fan": "FAN", "cubicle": "CUB", "tank": "TANK",
                               "boiler": "BOILER", "elevator": "EV"}.get(kind)
    if label:
        lx, ly_ = R(0, -h / 2 - e["label_height"] * scale * 1.3)
        tang = ang % 360
        if 90 < tang <= 270:      # keep the label readable
            tang -= 180
        yield _text(lx, ly_, label, e["label_height"], tang, {**a, "lt": 1}, align="center")
