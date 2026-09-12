"""JWC_TEMP.TXT (Jw_cad 外部変形 exchange file) reader and writer.

Format reference: Jw_cad 同梱 jww_smpl.bat, mintleaf.sakura.ne.jp/cad/jwc_temp.html,
jwcad.s-projects.net/external-deformation-*.html.

Reading (Jw_cad -> us): header lines (hq, hk, hs, hcw/hch/hcd/hcc, hn, hpN...) then '#', then
entity lines with attribute state lines (lg/ly/lc/lt/cn) interleaved, then optionally '#' and
layer state lines (REM #gn).

Writing (us -> Jw_cad): the file must NOT contain 'hq'. Coordinates are real mm in the current
write layer group's scale. 'hd' deletes the selected data first (replace semantics).
"""
from __future__ import annotations

import math
import re
from typing import Any

from .model import ModelError, TEXT_KINDS, fnum, normalize_entity, primitives, text_anchor_left

ENCODING = "cp932"
_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def _is_num(tok: str) -> bool:
    return bool(_NUM.match(tok))


def _hex_layer(s: str) -> int:
    return int(s, 16)


class JwcTemp:
    """Parsed JWC_TEMP.TXT."""

    def __init__(self) -> None:
        self.hq = False
        self.file: str | None = None
        self.hk = 0.0
        self.hs: list[float] = [1.0] * 16
        self.hzs: list[float] | None = None
        self.hcw = [2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10]
        self.hch = [2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10]
        self.hcd = [0, 0, 0.5, 0.5, 0.5, 0.5, 1, 1, 1, 1]
        self.hcc = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
        self.hn: list[float] | None = None
        self.bz = False
        self.points: dict[str, dict] = {}
        self.write: dict[str, Any] = {"lg": 0, "ly": 0, "lc": 1, "lt": 1, "cn": 1}
        self.entities: list[dict] = []
        self.group_state: dict[int, dict] = {}
        self.layer_state: dict[str, dict] = {}
        self.unparsed: list[str] = []

    # ------------------------------------------------------------------
    def base_offsets(self) -> dict[int, tuple[float, float]] | None:
        """With `REM #hp` the 外部変形 base point is the paper's lower-left corner, while Jw_cad's drawing
        origin is the paper centre. Returns per-group (dx, dy) = paper half size × group scale, or None
        when the paper size (hzs, needs REM #zs) is unknown."""
        if not self.hzs:
            return None
        w, h = self.hzs
        return {g: (w / 2 * self.hs[g], h / 2 * self.hs[g]) for g in range(16)}

    def to_drawing_coords(self) -> bool:
        """Convert entities / selection range / points from paper-lower-left base to drawing origin."""
        off = self.base_offsets()
        if not off or getattr(self, "_converted", False):
            return False
        from .model import shift_prim
        self.entities = [shift_prim(e, -off[int(e.get("lg", 0))][0], -off[int(e.get("lg", 0))][1]) if e.get("type") != "block" else e
                         for e in self.entities]
        g = self.write.get("lg", 0)
        if self.hn:
            self.hn = [self.hn[0] - off[g][0], self.hn[1] - off[g][1], self.hn[2] - off[g][0], self.hn[3] - off[g][1]]
        for pt in self.points.values():
            pt["x"] -= off[g][0]; pt["y"] -= off[g][1]
        self._converted = True
        return True

    def to_dict(self) -> dict:
        return {
            "hq": self.hq, "file": self.file, "axis_angle": self.hk,
            "coordinates": "drawing_origin (converted from paper lower-left base)" if getattr(self, "_converted", False) else "as_written (relative to the 外部変形 base point)",
            "scales": {f"{i:X}": v for i, v in enumerate(self.hs)},
            "paper_mm": self.hzs, "selection_range": self.hn, "paper_coords": self.bz,
            "text_types": {"width": self.hcw, "height": self.hch, "spacing": self.hcd, "color": self.hcc},
            "points": self.points, "write_settings": self.write,
            "groups": {f"{k:X}": v for k, v in self.group_state.items()},
            "layers": self.layer_state,
            "entity_count": len(self.entities), "entities": self.entities,
            "unparsed": self.unparsed[:50],
        }


def parse(text: str) -> JwcTemp:
    j = JwcTemp()
    state = {"lg": 0, "ly": 0, "lc": 1, "lt": 1, "cn": 1, "cn0": None, "font": None, "cc": 0,
             "pn": None, "z": [], "solid_rgb": None}
    section = 0          # 0 header, 1 entities, 2 layers
    in_pl = False
    pl_id = 0
    pending_hp: str | None = None
    in_msz = False
    in_bl: dict | None = None

    def scale_for(lg: int) -> float:
        return j.hs[lg] if 0 <= lg < 16 else 1.0

    def real(v: float, lg: int) -> float:
        return v * scale_for(lg) if j.bz else v

    def cur_text_size() -> tuple[float, float, float, int, int | None]:
        if state["cn"] == 0 and state["cn0"]:
            w, h, d, c = state["cn0"]
            return w, h, d, c, None
        n = max(1, min(10, int(state["cn"])))
        return (float(j.hcw[n - 1]), float(j.hch[n - 1]), float(j.hcd[n - 1]), int(j.hcc[n - 1]), n)

    def push(e: dict) -> None:
        nonlocal pending_hp
        e.setdefault("lg", state["lg"]); e.setdefault("ly", state["ly"])
        e.setdefault("lc", state["lc"]); e.setdefault("lt", state["lt"])
        if state["z"]:
            e["z"] = list(state["z"]); state["z"] = []
        if in_pl:
            e["curve"] = f"pl{pl_id}"
        if in_msz:
            e["dim"] = True
        if in_bl is not None:
            in_bl["entities"].append(e)
            return
        if pending_hp:
            j.points[pending_hp]["entity"] = e
            pending_hp = None
            return
        j.entities.append(e)

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        s = line.strip()
        if s == "":
            continue
        if s == "#":
            if in_pl:
                in_pl = False
            elif in_bl is not None:
                j.entities.append(in_bl); in_bl = None
            else:
                section = min(section + 1, 2)
            continue
        if s.startswith("#"):
            continue
        toks = s.split()
        head = toks[0]
        lower = head.lower()

        # ---- header / control ------------------------------------------------
        if lower == "hq":
            j.hq = True; continue
        if s.startswith("file="):
            j.file = s[5:].strip(); continue
        if lower == "hk" and len(toks) >= 2:
            j.hk = float(toks[1]); continue
        if lower == "hs":
            vals = [float(t) for t in toks[1:] if _is_num(t)]
            j.hs = (vals + [1.0] * 16)[:16]; continue
        if lower == "hzs" and len(toks) >= 3:
            j.hzs = [float(toks[1]), float(toks[2])]; continue
        if lower in ("hcw", "hch", "hcd", "hcc"):
            vals = [float(t) for t in toks[1:] if _is_num(t)]
            if lower == "hcc":
                vals = [int(v) for v in vals]
            setattr(j, lower, (vals + getattr(j, lower))[:10]); continue
        if lower == "hn" and len(toks) >= 5:
            j.hn = [float(t) for t in toks[1:5]]; continue
        if lower == "bz":
            j.bz = True; continue
        if lower == "b0":
            j.bz = False; continue
        if lower.startswith("hhp"):
            pending_hp = head[1:]; continue
        if lower.startswith("hp") and len(toks) >= 3 and _is_num(toks[1]):
            j.points[head] = {"x": float(toks[1]), "y": float(toks[2])}; continue
        if lower.startswith("hzk"):
            continue

        # ---- attribute state ---------------------------------------------------
        m = re.fullmatch(r"(lg|ly)([0-9a-fA-F])", head)
        if m:
            key, idx = m.group(1), _hex_layer(m.group(2))
            if len(toks) >= 2 and _is_num(toks[1]):
                st = int(float(toks[1]))
                if key == "lg":
                    j.group_state.setdefault(idx, {})["state"] = st
                    state["lg_for_names"] = idx
                else:
                    g = state.get("lg_for_names", state["lg"])
                    j.layer_state.setdefault(f"{g:X}-{idx:X}", {})["state"] = st
                    state["ly_for_names"] = idx
            else:
                state[key] = idx
                if section == 0:
                    j.write[key] = idx
                state["lg_for_names" if key == "lg" else "ly_for_names"] = idx
            continue
        if lower.startswith("lgn"):
            g = state.get("lg_for_names", state["lg"])
            j.group_state.setdefault(g, {})["name"] = s[3:].strip(); continue
        if lower.startswith("lyn"):
            g = state.get("lg_for_names", state["lg"]); l = state.get("ly_for_names", state["ly"])
            j.layer_state.setdefault(f"{g:X}-{l:X}", {})["name"] = s[3:].strip(); continue
        m = re.fullmatch(r"lc(\d+)", head)
        if m:
            state["lc"] = int(m.group(1))
            state["solid_rgb"] = int(float(toks[1])) if state["lc"] == 10 and len(toks) >= 2 else None
            if section == 0:
                j.write["lc"] = state["lc"]
            continue
        m = re.fullmatch(r"lt(\d+)", head)
        if m:
            state["lt"] = int(m.group(1))
            if section == 0:
                j.write["lt"] = state["lt"]
            continue
        m = re.fullmatch(r"lw(\d+)?", head)
        if m:
            continue
        if head.startswith('cn"'):
            font = s[3:]
            if font.startswith("$"):
                font = font[1:]
            state["font"] = font.rstrip("/").strip() or None
            continue
        m = re.fullmatch(r"cn(\d+)", head)
        if m:
            n = int(m.group(1))
            state["cn"] = n
            if n == 0 and len(toks) >= 5:
                state["cn0"] = (float(toks[1]), float(toks[2]), float(toks[3]), int(float(toks[4])))
            if section == 0:
                j.write["cn"] = n
            continue
        m = re.fullmatch(r"cc(\d)", head)
        if m:
            state["cc"] = int(m.group(1)); continue
        if lower == "cc" and len(toks) >= 2:
            state["cc"] = int(float(toks[1])); continue
        m = re.fullmatch(r"pn(\d+)", head)
        if m:
            state["pn"] = int(m.group(1)); continue
        m = re.fullmatch(r"z([1-5])", head)
        if m:
            state["z"].append(int(m.group(1))); continue

        # ---- geometry -------------------------------------------------------------
        lg = state["lg"]
        if lower == "pl":
            in_pl = True; pl_id += 1; continue
        if lower == "msz" or lower == "msg":
            in_msz = True; continue
        if head == "BL" and len(toks) >= 3:
            name = s.split('"', 1)[1] if '"' in s else ""
            in_bl = {"type": "block", "x": real(float(toks[1]), lg), "y": real(float(toks[2]), lg),
                     "name": name, "entities": [], "lg": lg, "ly": state["ly"], "lc": state["lc"], "lt": state["lt"]}
            continue
        if lower == "ci" and len(toks) >= 4:
            cx, cy, r = real(float(toks[1]), lg), real(float(toks[2]), lg), real(float(toks[3]), lg)
            if len(toks) >= 6:
                st, en = float(toks[4]), float(toks[5])
                fl = float(toks[6]) if len(toks) >= 7 else 1.0
                tilt = float(toks[7]) if len(toks) >= 8 else 0.0
                full = abs((en - st) % 360.0) < 1e-9 and abs(en - st) >= 360.0 - 1e-9
                if full or abs(en - st) >= 360.0:
                    push({"type": "circle", "cx": cx, "cy": cy, "r": r, "flatness": fl, "tilt": tilt})
                else:
                    push({"type": "arc", "cx": cx, "cy": cy, "r": r, "start": st, "end": en, "flatness": fl, "tilt": tilt})
            else:
                push({"type": "circle", "cx": cx, "cy": cy, "r": r, "flatness": 1.0, "tilt": 0.0})
            continue
        if lower == "pt" and len(toks) >= 3:
            e = {"type": "point", "x": real(float(toks[1]), lg), "y": real(float(toks[2]), lg)}
            if len(toks) >= 6:
                e["scale"] = float(toks[3]); e["angle"] = float(toks[4]); e["code"] = int(float(toks[5]))
            if state["pn"]:
                e["lc"] = state["pn"]
            push(e); continue
        if lower in TEXT_KINDS and len(toks) >= 5:
            content = s.split('"', 1)[1] if '"' in s else ""
            x, y = real(float(toks[1]), lg), real(float(toks[2]), lg)
            dx, dy = real(float(toks[3]), lg), real(float(toks[4]), lg)
            w, h, d, c, cn = cur_text_size()
            e = {"type": "text", "x": x, "y": y, "text": content, "height": h, "width": w, "spacing": d,
                 "angle": math.degrees(math.atan2(dy, dx)) if (dx or dy) else 0.0, "align": "left",
                 "kind": lower, "lc": c}
            if cn:
                e["cn"] = cn
            if state["font"]:
                e["font"] = state["font"]
            if state["cc"]:
                e["base_point"] = state["cc"]
            e["extent"] = [dx, dy]
            push(e)
            if in_msz and lower == "cs":
                in_msz = False
            continue
        if lower == "sl":
            nums = [float(t) for t in toks[1:] if _is_num(t)]
            if len(nums) in (4, 6, 8):
                pts = [[real(nums[i], lg), real(nums[i + 1], lg)] for i in range(0, len(nums), 2)]
                if len(pts) == 4:   # Jw order: p1, p4, p2, p3 -> reorder to polygon order
                    pts = [pts[0], pts[2], pts[3], pts[1]]
                e = {"type": "solid", "points": pts}
                if state["solid_rgb"] is not None:
                    v = state["solid_rgb"]; e["rgb"] = [v & 255, (v >> 8) & 255, (v >> 16) & 255]
                push(e); continue
        if lower in ("sc", "se", "so", "sg"):
            nums = [float(t) for t in toks[1:] if _is_num(t)]
            if len(nums) >= 3:
                push({"type": "solid_circle", "kind": lower, "cx": real(nums[0], lg), "cy": real(nums[1], lg),
                      "r": real(nums[2], lg), "params": nums[3:]}); continue
        if len(toks) >= 4 and all(_is_num(t) for t in toks[:4]):
            x1, y1, x2, y2 = (real(float(t), lg) for t in toks[:4])
            push({"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2}); continue
        if len(toks) >= 2 and all(_is_num(t) for t in toks[:2]) and in_pl:
            # continuous-line short form is only meaningful when Jw_cad reads; ignore on parse
            continue
        j.unparsed.append(line)
    return j


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def serialize(entities: list[dict], *, scale_for=None, delete_selected: bool = False,
              error: str | None = None, notice: str | None = None,
              group_names: dict[int, str] | None = None, layer_names: dict[str, str] | None = None,
              repeat: bool = False, offset_for=None) -> str:
    """Build the text Jw_cad reads back. Coordinates real mm. Returns str (encode with cp932).
    offset_for(lg) -> (dx, dy) shifts primitives of that layer group (used to convert drawing-absolute
    coordinates back to the 外部変形 base point)."""
    out: list[str] = []
    if error:
        out.append("he" + error.replace("\r", "").replace("\n", " "))
        return "\r\n".join(out) + "\r\n"
    if delete_selected:
        out.append("hd")
    if notice:
        out.append("h#" + notice.replace("\r", "").replace("\n", " "))
    if repeat:
        out.append("hr")
    scale_for = scale_for or (lambda e: 100.0)

    for g, name in sorted((group_names or {}).items()):
        out.append(f"lg{int(g):x}")
        out.append(f"lgn{name}")
    for key, name in sorted((layer_names or {}).items()):
        g, l = key.split("-")
        out.append(f"lg{int(g, 16):x}")
        out.append(f"ly{int(l, 16):x}")
        out.append(f"lyn{name}")

    prims: list[dict] = []
    for e in entities:
        if "id" not in e or e.get("type") not in ("line", "circle", "arc", "text", "point", "solid",
                                                    "polyline", "rect", "dimension"):
            e = normalize_entity(e)
        sc = scale_for(e)
        for p in primitives(e, sc):
            p = dict(p); p["_scale"] = sc
            if offset_for is not None:
                from .model import shift_prim
                dx, dy = offset_for(int(p.get("lg", 0)))
                p = shift_prim(p, dx, dy); p["_scale"] = sc
            prims.append(p)

    order = {"line": 0, "circle": 1, "arc": 1, "point": 2, "solid": 3, "text": 4}
    prims.sort(key=lambda p: (int(p.get("lg", 0)), int(p.get("ly", 0)), int(p.get("lc", 1)), int(p.get("lt", 1)),
                              order.get(p["type"], 9)))

    cur = {"lg": None, "ly": None, "lc": None, "lt": None, "cn": None, "font": None}
    for p in prims:
        lg, ly = int(p.get("lg", 0)), int(p.get("ly", 0))
        lc, lt = int(p.get("lc", 1)), int(p.get("lt", 1))
        if lg != cur["lg"]:
            out.append(f"lg{lg:x}"); cur["lg"] = lg
        if ly != cur["ly"]:
            out.append(f"ly{ly:x}"); cur["ly"] = ly
        if p["type"] == "solid" and p.get("rgb"):
            r, g, b = p["rgb"]
            out.append(f"lc10 {r + g * 256 + b * 65536}"); cur["lc"] = None
        elif lc != cur["lc"]:
            out.append(f"lc{lc}"); cur["lc"] = lc
        if lt != cur["lt"] and p["type"] != "text":
            out.append(f"lt{lt}"); cur["lt"] = lt
        for z in (p.get("z") or []):
            out.append(f"z{int(z)}")

        t = p["type"]
        if t == "line":
            out.append(f"{fnum(p['x1'])} {fnum(p['y1'])} {fnum(p['x2'])} {fnum(p['y2'])}")
        elif t == "circle":
            fl, tilt = p.get("flatness", 1.0), p.get("tilt", 0.0)
            if abs(fl - 1.0) < 1e-9 and abs(tilt) < 1e-9:
                out.append(f"ci {fnum(p['cx'])} {fnum(p['cy'])} {fnum(p['r'])}")
            else:
                out.append(f"ci {fnum(p['cx'])} {fnum(p['cy'])} {fnum(p['r'])} 0 360 {fnum(fl)} {fnum(tilt)}")
        elif t == "arc":
            out.append(f"ci {fnum(p['cx'])} {fnum(p['cy'])} {fnum(p['r'])} {fnum(p['start'])} {fnum(p['end'])} "
                       f"{fnum(p.get('flatness', 1.0))} {fnum(p.get('tilt', 0.0))}")
        elif t == "point":
            if p.get("code"):
                out.append(f"pt {fnum(p['x'])} {fnum(p['y'])} {fnum(p.get('scale', 1.0))} {fnum(p.get('angle', 0.0))} {int(p['code'])}")
            else:
                out.append(f"pt {fnum(p['x'])} {fnum(p['y'])}")
        elif t == "solid":
            pts = p["points"]
            if len(pts) == 3:
                flat = [c for q in pts for c in q]
            else:
                a, b, c, d = pts   # polygon order -> Jw order p1 p4 p2 p3
                flat = [*a, *d, *b, *c]
            out.append("sl " + " ".join(fnum(v) for v in flat))
        elif t == "text":
            sc = p["_scale"]
            h, w, d = float(p.get("height", 3.0)), float(p.get("width", p.get("height", 3.0))), float(p.get("spacing", 0.0))
            cn = p.get("cn")
            key = (cn, w, h, d, lc)
            if key != cur["cn"]:
                out.append(f"cn{cn}" if cn else f"cn0 {fnum(w)} {fnum(h)} {fnum(d)} {lc}")
                cur["cn"] = key
            font = p.get("font")
            if font and font != cur["font"]:
                out.append(f'cn"${font}'); cur["font"] = font
            x, y, L = text_anchor_left(p, sc)
            ang = math.radians(float(p.get("angle", 0.0)))
            dx, dy = math.cos(ang) * L, math.sin(ang) * L
            kind = p.get("kind", "ch")
            out.append(f"{kind} {fnum(x)} {fnum(y)} {fnum(dx)} {fnum(dy)} \"{p['text']}")
        else:
            raise ModelError(f"cannot serialize primitive {t}")
    return "\r\n".join(out) + "\r\n"


def encode(text: str) -> bytes:
    return text.encode(ENCODING, errors="replace")


def decode(data: bytes) -> str:
    for enc in (ENCODING, "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode(ENCODING, errors="replace")
