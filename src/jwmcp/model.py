"""Drawing model shared by every layer of jwmcp.

Conventions (these are the Jw_cad conventions, restated once here):
  * Coordinates are **real millimetres** (実寸). A 1/100 plan with a 3,640 mm wall stores 3640.
    Paper coordinates (図寸) are converted at the edges (jww_read, jwc_temp with `bz`).
  * Text sizes (height / width / spacing) are **paper millimetres** (図寸), exactly like Jw_cad's
    文字種設定. The rendered size on the drawing is size × scale.
  * Attributes: lg = layer group 0..15, ly = layer 0..15, lc = 線色 1..9 (10 = solid custom colour),
    lt = 線種 1..9 (11..19 = ランダム線/倍長線種).
  * Angles are degrees, counter-clockwise, X axis = 0.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Iterable

from .arch import ARCH_TYPES, ArchError, arch_primitives, normalize_arch

# ---------------------------------------------------------------------------
# Jw_cad constant tables
# ---------------------------------------------------------------------------

# Default screen palette as COLORREF (0x00BBGGRR) - index 0 background, 1..8 線色, 9 補助線色/グレー
DEFAULT_PEN_COLORREF = [16777215, 12632064, 0, 49152, 49344, 12583104, 16711680, 8421376, 8388863, 12632256]

LINETYPE_NAMES = {
    1: "実線", 2: "点線1", 3: "点線2", 4: "点線3",
    5: "一点鎖1", 6: "一点鎖2", 7: "二点鎖1", 8: "二点鎖2", 9: "補助線種",
}

# Matplotlib dash patterns (in points) per 線種
LINETYPE_DASHES = {
    1: None, 2: (1, 2), 3: (2, 2), 4: (3, 3),
    5: (6, 2, 1, 2), 6: (10, 3, 2, 3), 7: (6, 2, 1, 2, 1, 2), 8: (10, 3, 2, 3, 2, 3), 9: (1, 1),
}

# DXF linetype names (ezdxf setup=True defines these)
LINETYPE_DXF = {
    1: "CONTINUOUS", 2: "DOT", 3: "DOT2", 4: "DOTX2",
    5: "DASHDOT", 6: "DASHDOT2", 7: "DIVIDE", 8: "DIVIDE2", 9: "HIDDEN",
}

# AutoCAD colour index per 線色 (visual approximation of Jw_cad defaults)
PEN_ACI = {1: 4, 2: 7, 3: 3, 4: 2, 5: 6, 6: 5, 7: 130, 8: 1, 9: 8, 10: 7}

PAPER_SIZES_MM = {  # Jw_cad 図面サイズ番号 -> (width, height) landscape
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210),
    "2A": (1682, 1189), "3A": (2378, 1682), "4A": (3364, 2378), "5A": (4756, 3364),
    "10m": (10000, 7071), "50m": (50000, 35355), "100m": (100000, 70711),
}
PAPER_CODE = {"A0": 0, "A1": 1, "A2": 2, "A3": 3, "A4": 4, "2A": 8, "3A": 9, "4A": 10, "5A": 11,
              "10m": 12, "50m": 13, "100m": 14}
PAPER_BY_CODE = {v: k for k, v in PAPER_CODE.items()}

TEXT_KINDS = {"ch", "cv", "cs", "cr", "co", "cp", "ct", "ck", "cz", "c2"}

from .arch import ARCH_TYPES, ArchError, arch_primitives, normalize_arch  # noqa: E402

ENTITY_TYPES = {"line", "polyline", "rect", "circle", "arc", "text", "point", "dimension", "solid"} | ARCH_TYPES


def colorref_to_rgb(v: int) -> tuple[int, int, int]:
    return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)


def pen_rgb(lc: int, palette: list[int] | None = None) -> tuple[int, int, int]:
    pal = palette or DEFAULT_PEN_COLORREF
    if 0 <= lc < len(pal):
        return colorref_to_rgb(pal[lc])
    return (0, 0, 0)


# ---------------------------------------------------------------------------
# Text metrics (Jw_cad: full-width char = 1 width, half-width = 0.5 width)
# ---------------------------------------------------------------------------

def char_units(s: str) -> float:
    units = 0.0
    for ch in s:
        units += 1.0 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 0.5
    return units


def text_length_paper(s: str, width: float, spacing: float) -> float:
    """Length of a string along its baseline in paper mm."""
    n = len(s)
    if n == 0:
        return 0.0
    return char_units(s) * width + spacing * (n - 1)


# ---------------------------------------------------------------------------
# Number formatting shared by jwc_temp / dxf
# ---------------------------------------------------------------------------

def fnum(v: float, digits: int = 6) -> str:
    if v is None:
        return "0"
    if abs(v) < 10 ** (-digits):
        v = 0.0
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def format_dimension_value(mm: float, decimals: int = 0, comma: bool = True) -> str:
    if decimals <= 0:
        v = int(round(mm))
        return f"{v:,}" if comma else str(v)
    s = f"{mm:,.{decimals}f}" if comma else f"{mm:.{decimals}f}"
    return s


# ---------------------------------------------------------------------------
# Entity normalisation
# ---------------------------------------------------------------------------

class ModelError(ValueError):
    pass


def _f(d: dict, key: str, default: float | None = None) -> float:
    if key not in d or d[key] is None:
        if default is None:
            raise ModelError(f"'{key}' is required for entity type '{d.get('type')}'")
        return float(default)
    try:
        return float(d[key])
    except (TypeError, ValueError):
        raise ModelError(f"'{key}' must be a number, got {d[key]!r}")


def _i(d: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = d.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ModelError(f"'{key}' must be an integer, got {v!r}")
    if not (lo <= v <= hi):
        raise ModelError(f"'{key}' must be in {lo}..{hi}, got {v}")
    return v


def _layer_int(v: Any) -> int:
    """Accept 0..15 or hex chars '0'..'F' for lg / ly."""
    if isinstance(v, str):
        v = v.strip()
        if re.fullmatch(r"[0-9a-fA-F]", v):
            return int(v, 16)
    return int(v)


def normalize_entity(e: dict, defaults: dict | None = None) -> dict:
    """Validate a user-supplied entity dict and fill defaults. Returns a new dict."""
    if not isinstance(e, dict):
        raise ModelError(f"entity must be an object, got {type(e).__name__}")
    t = str(e.get("type", "")).lower()
    if t not in ENTITY_TYPES:
        raise ModelError(f"unknown entity type {t!r}; expected one of {sorted(ENTITY_TYPES)}")
    d = dict(defaults or {})
    d.update(e)
    d["type"] = t
    out: dict[str, Any] = {
        "id": str(d.get("id") or uuid.uuid4().hex[:8]),
        "type": t,
        "lg": _layer_int(d.get("lg", 0)),
        "ly": _layer_int(d.get("ly", 0)),
        "lc": _i(d, "lc", 1, 1, 10),
        "lt": _i(d, "lt", 1, 1, 19),
    }
    if not (0 <= out["lg"] <= 15 and 0 <= out["ly"] <= 15):
        raise ModelError("lg / ly must be 0..15 (or hex 0..F)")
    for k in ("z", "tag"):
        if d.get(k) is not None:
            out[k] = d[k]

    if t in ARCH_TYPES:
        try:
            return normalize_arch(d, out)
        except ArchError as exc:
            raise ModelError(str(exc)) from exc
    if t == "line":
        for k in ("x1", "y1", "x2", "y2"):
            out[k] = _f(d, k)
    elif t == "polyline":
        pts = d.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            raise ModelError("polyline needs 'points': [[x,y], ...] with 2+ points")
        out["points"] = [[float(p[0]), float(p[1])] for p in pts]
        out["closed"] = bool(d.get("closed", False))
    elif t == "rect":
        out["x"] = _f(d, "x"); out["y"] = _f(d, "y")
        out["w"] = _f(d, "w"); out["h"] = _f(d, "h")
        out["angle"] = _f(d, "angle", 0.0)
    elif t == "circle":
        out["cx"] = _f(d, "cx"); out["cy"] = _f(d, "cy"); out["r"] = _f(d, "r")
        if out["r"] <= 0:
            raise ModelError("circle radius must be > 0")
        out["flatness"] = _f(d, "flatness", 1.0)
        out["tilt"] = _f(d, "tilt", 0.0)
    elif t == "arc":
        out["cx"] = _f(d, "cx"); out["cy"] = _f(d, "cy"); out["r"] = _f(d, "r")
        out["start"] = _f(d, "start"); out["end"] = _f(d, "end")
        out["flatness"] = _f(d, "flatness", 1.0)
        out["tilt"] = _f(d, "tilt", 0.0)
    elif t == "text":
        out["x"] = _f(d, "x"); out["y"] = _f(d, "y")
        text = d.get("text")
        if text is None or str(text) == "":
            raise ModelError("text entity needs non-empty 'text'")
        out["text"] = str(text).replace("\r", "").replace("\n", " ")
        out["height"] = _f(d, "height", 3.0)
        out["width"] = _f(d, "width", out["height"])
        out["spacing"] = _f(d, "spacing", 0.0)
        out["angle"] = _f(d, "angle", 0.0)
        out["align"] = str(d.get("align", "left")).lower()
        if out["align"] not in ("left", "center", "right"):
            raise ModelError("text align must be left|center|right")
        kind = str(d.get("kind", "ch")).lower()
        if kind not in TEXT_KINDS:
            raise ModelError(f"text kind must be one of {sorted(TEXT_KINDS)}")
        out["kind"] = kind
        if d.get("font"):
            out["font"] = str(d["font"])
        if d.get("cn") is not None:
            out["cn"] = _i(d, "cn", 0, 1, 10)
    elif t == "point":
        out["x"] = _f(d, "x"); out["y"] = _f(d, "y")
        if d.get("code") is not None:
            out["code"] = int(d["code"]); out["scale"] = _f(d, "scale", 1.0); out["angle"] = _f(d, "angle", 0.0)
    elif t == "dimension":
        for k in ("x1", "y1", "x2", "y2"):
            out[k] = _f(d, k)
        out["offset"] = _f(d, "offset", 500.0)
        out["extension"] = _f(d, "extension", 2.0)   # paper mm 突出
        out["gap"] = _f(d, "gap", 0.0)                 # real mm gap from measured point
        out["text_height"] = _f(d, "text_height", 3.0)
        out["text_gap"] = _f(d, "text_gap", 1.0)       # paper mm between line and value
        out["decimals"] = int(d.get("decimals", 0))
        out["comma"] = bool(d.get("comma", True))
        if d.get("text") is not None:
            out["text"] = str(d["text"])
        out["endpoints"] = str(d.get("endpoints", "point"))  # point | none
    elif t == "solid":
        pts = d.get("points")
        if not isinstance(pts, list) or len(pts) not in (3, 4):
            raise ModelError("solid needs 'points' with 3 or 4 [x,y]")
        out["points"] = [[float(p[0]), float(p[1])] for p in pts]
        if d.get("rgb") is not None:
            r, g, b = d["rgb"]
            out["rgb"] = [int(r), int(g), int(b)]
            out["lc"] = 10
    return out


# ---------------------------------------------------------------------------
# Compound -> primitive expansion
# ---------------------------------------------------------------------------

def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (x * c - y * s, x * s + y * c)


def _attrs(e: dict) -> dict:
    return {k: e[k] for k in ("lg", "ly", "lc", "lt") if k in e}


def primitives(e: dict, scale: float) -> Iterable[dict]:
    """Yield line/circle/arc/text/point/solid primitives for an entity.

    `scale` is the denominator of the entity's layer group (1/100 -> 100). It is needed to turn
    paper-mm text sizes into real-mm geometry for dimensions.
    """
    t = e["type"]
    a = _attrs(e)
    if t in ("line", "circle", "arc", "text", "point", "solid"):
        yield e
    elif t == "polyline":
        pts = e["points"]
        seq = pts + ([pts[0]] if e.get("closed") and pts[0] != pts[-1] else [])
        for (x1, y1), (x2, y2) in zip(seq, seq[1:]):
            yield {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "curve": e.get("id", "pl"), **a}
    elif t == "rect":
        x, y, w, h, ang = e["x"], e["y"], e["w"], e["h"], e.get("angle", 0.0)
        corners = [(0, 0), (w, 0), (w, h), (0, h)]
        pts = []
        for cx, cy in corners:
            rx, ry = _rot(cx, cy, ang)
            pts.append((x + rx, y + ry))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            yield {"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, **a}
    elif t == "dimension":
        yield from _dimension_primitives(e, scale)
    elif t in ARCH_TYPES:
        try:
            yield from arch_primitives(e, scale)
        except ArchError as exc:
            raise ModelError(str(exc)) from exc
    else:
        raise ModelError(f"cannot expand entity type {t}")


def _dimension_primitives(e: dict, scale: float) -> Iterable[dict]:
    a = _attrs(e)
    x1, y1, x2, y2 = e["x1"], e["y1"], e["x2"], e["y2"]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L == 0:
        raise ModelError("dimension points coincide")
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    off = e["offset"]
    ext = e["extension"] * scale
    gap = e["gap"]
    sgn = 1.0 if off >= 0 else -1.0
    # dimension line
    q1 = (x1 + nx * off, y1 + ny * off)
    q2 = (x2 + nx * off, y2 + ny * off)
    yield {"type": "line", "x1": q1[0], "y1": q1[1], "x2": q2[0], "y2": q2[1], "dim": True, **a}
    # extension lines
    for (px, py), (qx, qy) in ((( x1, y1), q1), ((x2, y2), q2)):
        sx, sy = px + nx * gap * sgn, py + ny * gap * sgn
        ex, ey = qx + nx * ext * sgn, qy + ny * ext * sgn
        yield {"type": "line", "x1": sx, "y1": sy, "x2": ex, "y2": ey, "dim": True, **a}
    if e.get("endpoints", "point") == "point":
        yield {"type": "point", "x": q1[0], "y": q1[1], "dim": True, **a}
        yield {"type": "point", "x": q2[0], "y": q2[1], "dim": True, **a}
    # value text, centred above the dimension line (on the +n side of it)
    value = e.get("text") or format_dimension_value(L, e.get("decimals", 0), e.get("comma", True))
    th = e["text_height"]
    tlen = text_length_paper(value, th, 0.0) * scale
    ang = math.degrees(math.atan2(uy, ux))
    # keep text readable: flip if it would be upside-down
    tux, tuy, tnx, tny = ux, uy, nx, ny
    if ang > 90 or ang <= -90:
        ang += 180
        tux, tuy = -ux, -uy
        tnx, tny = -nx, -ny
    mx, my = (q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2
    tg = e["text_gap"] * scale
    bx = mx - tux * tlen / 2 + tnx * tg
    by = my - tuy * tlen / 2 + tny * tg
    yield {"type": "text", "x": bx, "y": by, "text": value, "height": th, "width": th,
           "spacing": 0.0, "angle": ang, "align": "left", "kind": "cs", "dim": True, **a}


_COORD_KEYS = ("x1", "y1", "x2", "y2", "cx", "cy", "x", "y", "r")


def rescale_prim(p: dict, k: float) -> dict:
    """Multiply every coordinate (and radius) of a primitive by k. Text sizes (paper mm) are untouched."""
    if k == 1.0:
        return p
    q = dict(p)
    for key in _COORD_KEYS:
        if key in q and isinstance(q[key], (int, float)):
            q[key] = q[key] * k
    if "points" in q:
        q["points"] = [[a * k, b * k] for a, b in q["points"]]
    if "extent" in q and isinstance(q["extent"], list):
        q["extent"] = [v * k for v in q["extent"]]
    return q


def shift_prim(p: dict, dx: float, dy: float) -> dict:
    """Translate a primitive."""
    if dx == 0 and dy == 0:
        return p
    q = dict(p)
    for kx, ky in (("x1", "y1"), ("x2", "y2"), ("cx", "cy"), ("x", "y")):
        if kx in q and isinstance(q[kx], (int, float)):
            q[kx] = q[kx] + dx; q[ky] = q[ky] + dy
    if "points" in q:
        q["points"] = [[a + dx, b + dy] for a, b in q["points"]]
    return q


def text_anchor_left(e: dict, scale: float) -> tuple[float, float, float]:
    """Return (x, y, length_real) of the left-bottom anchor for a text entity honouring align."""
    length = text_length_paper(e["text"], e.get("width", e.get("height", 3.0)), e.get("spacing", 0.0)) * scale
    ang = math.radians(e.get("angle", 0.0))
    ux, uy = math.cos(ang), math.sin(ang)
    x, y = e["x"], e["y"]
    al = e.get("align", "left")
    if al == "center":
        x -= ux * length / 2; y -= uy * length / 2
    elif al == "right":
        x -= ux * length; y -= uy * length
    return x, y, length


def entity_bbox(e: dict, scale: float) -> tuple[float, float, float, float] | None:
    t = e["type"]
    if t == "line":
        xs, ys = (e["x1"], e["x2"]), (e["y1"], e["y2"])
    elif t in ("circle", "arc"):
        r = e["r"] * max(1.0, e.get("flatness", 1.0))
        xs, ys = (e["cx"] - r, e["cx"] + r), (e["cy"] - r, e["cy"] + r)
    elif t == "text":
        x, y, L = text_anchor_left(e, scale)
        ang = math.radians(e.get("angle", 0.0))
        h = e.get("height", 3.0) * scale
        pts = [(x, y), (x + math.cos(ang) * L, y + math.sin(ang) * L),
               (x - math.sin(ang) * h, y + math.cos(ang) * h)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    elif t == "point":
        xs, ys = (e["x"],), (e["y"],)
    elif t == "solid":
        xs, ys = [p[0] for p in e["points"]], [p[1] for p in e["points"]]
    elif t == "dimfigure":
        xs, ys = (e["x1"], e["x2"]), (e["y1"], e["y2"])
    elif t in ("block", "solid_circle"):
        if "cx" in e:
            r = e.get("r", 0.0)
            xs, ys = (e["cx"] - r, e["cx"] + r), (e["cy"] - r, e["cy"] + r)
        else:
            return None
    else:
        boxes = [b for b in (entity_bbox(p, scale) for p in primitives(e, scale)) if b]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_of(entities: Iterable[dict], scale_for) -> dict | None:
    boxes = []
    for e in entities:
        b = entity_bbox(e, scale_for(e))
        if b:
            boxes.append(b)
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return {"min_x": x0, "min_y": y0, "max_x": x1, "max_y": y1, "width": x1 - x0, "height": y1 - y0}


# ---------------------------------------------------------------------------
# Drawing container with JSON persistence
# ---------------------------------------------------------------------------

def jwmcp_home() -> Path:
    p = Path(os.environ.get("JWMCP_HOME", Path.home() / ".jwmcp"))
    p.mkdir(parents=True, exist_ok=True)
    return p


class Drawing:
    """A drawing the agent is building. Persisted as JSON under $JWMCP_HOME/drawings."""

    def __init__(self, name: str, scale: float = 100.0, paper: str = "A3", description: str = ""):
        if not re.fullmatch(r"[\w\-\.ぁ-んァ-ン一-龠々ー]+", name):
            raise ModelError("drawing name may contain letters, digits, _ - . and Japanese characters only")
        if paper not in PAPER_SIZES_MM:
            raise ModelError(f"paper must be one of {list(PAPER_SIZES_MM)}")
        self.name = name
        self.paper = paper
        self.description = description
        self.preset: str | None = None
        self.profile: str | None = None
        self.main_scale: float = float(scale)
        self.group_scales: dict[int, float] = {i: float(scale) for i in range(16)}
        self.group_names: dict[int, str] = {}
        self.layer_names: dict[str, str] = {}   # "lg-ly" -> name
        self.entities: list[dict] = []
        self.created = time.time()
        self.updated = self.created

    # -- persistence --------------------------------------------------------
    @staticmethod
    def path_for(name: str) -> Path:
        d = jwmcp_home() / "drawings"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{name}.json"

    def save(self) -> Path:
        self.updated = time.time()
        p = self.path_for(self.name)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    @classmethod
    def load(cls, name: str) -> "Drawing":
        p = cls.path_for(name)
        if not p.exists():
            raise ModelError(f"drawing '{name}' does not exist (create it with drawing_new)")
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def list_names(cls) -> list[str]:
        d = jwmcp_home() / "drawings"
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def to_dict(self) -> dict:
        return {
            "name": self.name, "paper": self.paper, "description": self.description, "preset": self.preset,
            "profile": self.profile, "main_scale": self.main_scale,
            "group_scales": {str(k): v for k, v in self.group_scales.items()},
            "group_names": {str(k): v for k, v in self.group_names.items()},
            "layer_names": self.layer_names, "entities": self.entities,
            "created": self.created, "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Drawing":
        dr = cls(d["name"], paper=d.get("paper", "A3"), description=d.get("description", ""))
        dr.preset = d.get("preset")
        dr.profile = d.get("profile")
        dr.main_scale = float(d.get("main_scale", 100.0))
        dr.group_scales = {int(k): float(v) for k, v in d.get("group_scales", {}).items()} or dr.group_scales
        dr.group_names = {int(k): v for k, v in d.get("group_names", {}).items()}
        dr.layer_names = dict(d.get("layer_names", {}))
        dr.entities = list(d.get("entities", []))
        dr.created = d.get("created", time.time()); dr.updated = d.get("updated", dr.created)
        return dr

    # -- editing -------------------------------------------------------------
    def scale_of(self, e: dict) -> float:
        return self.group_scales.get(int(e.get("lg", 0)), 100.0)

    def preset_defaults(self, e: dict) -> dict:
        """Layer/colour defaults from the drawing's preset / profile for this entity type (empty if none)."""
        p: dict = {}
        if self.preset:
            from .presets import PRESETS
            p = dict(PRESETS.get(self.preset) or {})
        if self.profile:
            try:
                from .profiles import load_profile
                prof = load_profile(self.profile)
                merged_defaults = {**p.get("defaults", {})}
                for t_, d_ in prof.get("defaults", {}).items():
                    merged_defaults[t_] = {**merged_defaults.get(t_, {}), **d_}
                p = {**p, "defaults": merged_defaults, "pipe_layers": {**p.get("pipe_layers", {}), **prof.get("pipe_layers", {})}}
            except ModelError:
                pass
        if not p:
            return {}
        t = str(e.get("type", "")).lower()
        dflt = dict(p.get("defaults", {}).get(t, {}))
        if t == "pipe" and "pipe_layers" in p:
            lg_ly = p["pipe_layers"].get(str(e.get("system", "給水")))
            if lg_ly:
                dflt["lg"], dflt["ly"] = lg_ly
        if t == "wall" and e.get("structural") and "structure_wall" in p.get("defaults", {}):
            dflt.update(p["defaults"]["structure_wall"])
        return dflt

    def add(self, items: list[dict], defaults: dict | None = None) -> list[str]:
        new = [normalize_entity(e, {**self.preset_defaults(e), **(defaults or {})}) for e in items]  # validate all first
        self.entities.extend(new)
        return [e["id"] for e in new]

    def remove(self, ids: Iterable[str]) -> int:
        ids = set(ids)
        before = len(self.entities)
        self.entities = [e for e in self.entities if e["id"] not in ids]
        return before - len(self.entities)

    def primitives(self, unify_scale: bool = False) -> list[dict]:
        """Expand to primitives. unify_scale=True rescales every layer group into the main scale's real-mm
        space (what a single-model-space format like DXF, or a picture, needs when groups differ in scale)."""
        out = []
        for e in self.entities:
            sc = self.scale_of(e)
            k = (self.main_scale / sc) if (unify_scale and sc != self.main_scale) else 1.0
            for p in primitives(e, sc):
                out.append(rescale_prim(p, k) if k != 1.0 else p)
        return out

    def unified_entities(self) -> list[dict]:
        """Primitive entities in main-scale space, usable by render()/write_dxf() with a constant scale."""
        return self.primitives(unify_scale=True)

    def scale_for_unified(self, e: dict) -> float:
        return self.main_scale

    def bbox(self) -> dict | None:
        return bbox_of(self.entities, self.scale_of)

    def summary(self) -> dict:
        from collections import Counter
        by_type = Counter(e["type"] for e in self.entities)
        by_layer = Counter(f"{e['lg']:X}-{e['ly']:X}" for e in self.entities)
        return {
            "name": self.name, "paper": self.paper, "description": self.description,
            "scales": {f"{k:X}": v for k, v in self.group_scales.items() if k in self.group_names or any(int(e["lg"]) == k for e in self.entities) or k == 0},
            "group_names": {f"{k:X}": v for k, v in self.group_names.items()},
            "layer_names": self.layer_names,
            "entity_count": len(self.entities), "by_type": dict(by_type), "by_layer": dict(by_layer),
            "bbox": self.bbox(), "file": str(self.path_for(self.name)),
        }
