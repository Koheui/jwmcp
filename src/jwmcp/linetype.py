"""Jw_cad line types (線種) as defined in the environment file (.jwf), and their printed size.

.jwf format (Sample.jwf annotations):
  LTYPE_02..08 = <hex pattern> <1パターンのドット数 1-32> <画面表示ピッチ 1-16> <プリンタ出力ピッチ 1-160>
  LTYPE_09     = <hex pattern> <1パターンのドット数> <画面表示ピッチ>            (補助線種, not printed)
  LTYPE_R1..R5 = <hex pattern> <画面振幅> <画面ピッチ> <プリンタ振幅> <プリンタピッチ>   (ランダム線)
  LTYPE_L1..L4 = <hex pattern> <1パターンのドット数> <画面表示ピッチ> <プリンタ出力ピッチ> (倍長線種 / ロング線)

The hex value is 32 bits, most significant bit first; in Jw_cad's 基本設定 it is shown as 32 half-width characters,
"-" = a drawn dot, " " = a skipped dot (random lines use "," and "'"). 線種1 is always solid (ffffffff).
One pattern character is drawn as <pitch> dots; the first <1パターンのドット数> characters repeat.

Printed length: characters x printer pitch x (25.4 / dpi) mm, where dpi is the printer dot basis
(300 or 600 in Jw_cad). The exact basis Jw_cad applies to the line-type pitch is not stated in its help,
so the dpi is a parameter and a printable test sheet is provided to confirm it on the real printer.
"""
from __future__ import annotations

import re

# Jw_cad default values (jw_win.jwf shipped with Jw_cad 8.x)
DEFAULTS: dict[str, dict] = {
    "02": {"hex": "aaaaaaaa", "unit": 4, "pitch": 1, "print_pitch": 10},
    "03": {"hex": "c3c3c3c3", "unit": 8, "pitch": 1, "print_pitch": 10},
    "04": {"hex": "e7e7e7e7", "unit": 8, "pitch": 1, "print_pitch": 10},
    "05": {"hex": "f99ff99f", "unit": 16, "pitch": 1, "print_pitch": 10},
    "06": {"hex": "fff99fff", "unit": 32, "pitch": 1, "print_pitch": 10},
    "07": {"hex": "f24ff24f", "unit": 16, "pitch": 1, "print_pitch": 10},
    "08": {"hex": "fff24fff", "unit": 32, "pitch": 1, "print_pitch": 10},
    "09": {"hex": "22222222", "unit": 4, "pitch": 1},
    "R1": {"hex": "ccb2b32a", "amp": 1, "pitch": 3, "print_amp": 1, "print_pitch": 5},
    "R2": {"hex": "ccb2b32a", "amp": 1, "pitch": 4, "print_amp": 1, "print_pitch": 10},
    "R3": {"hex": "ccb2b32a", "amp": 2, "pitch": 5, "print_amp": 2, "print_pitch": 15},
    "R4": {"hex": "ccb2b32a", "amp": 2, "pitch": 6, "print_amp": 2, "print_pitch": 20},
    "R5": {"hex": "ccb2b32a", "amp": 2, "pitch": 7, "print_amp": 2, "print_pitch": 25},
    "L1": {"hex": "fff99fff", "unit": 32, "pitch": 2, "print_pitch": 20},
    "L2": {"hex": "fff24fff", "unit": 32, "pitch": 2, "print_pitch": 20},
    "L3": {"hex": "fffe7fff", "unit": 32, "pitch": 2, "print_pitch": 20},
    "L4": {"hex": "fffe7fff", "unit": 32, "pitch": 4, "print_pitch": 40},
}

NAMES = {
    "02": "線種2 点線1", "03": "線種3 点線2", "04": "線種4 点線3", "05": "線種5 一点鎖1", "06": "線種6 一点鎖2",
    "07": "線種7 二点鎖1", "08": "線種8 二点鎖2", "09": "補助線種",
    "R1": "ランダム線1", "R2": "ランダム線2", "R3": "ランダム線3", "R4": "ランダム線4", "R5": "ランダム線5",
    "L1": "倍長線種1", "L2": "倍長線種2", "L3": "倍長線種3", "L4": "倍長線種4",
}

KEYS = list(DEFAULTS)


def kind_of(key: str) -> str:
    return "random" if key.startswith("R") else "long" if key.startswith("L") else "aux" if key == "09" else "normal"


def hex_to_pattern(hexstr: str, random_line: bool = False) -> str:
    """32-char string, MSB first. Normal: '-' drawn / ' ' skipped. Random: "'" up / ',' down."""
    v = int(hexstr, 16) & 0xFFFFFFFF
    on, off = ("'", ",") if random_line else ("-", " ")
    return "".join(on if (v >> (31 - i)) & 1 else off for i in range(32))


def pattern_to_hex(pattern: str) -> str:
    p = (pattern + " " * 32)[:32]
    v = 0
    for i, ch in enumerate(p):
        if ch in ("-", "－", "'", "’", "1", "#", "●"):
            v |= 1 << (31 - i)
    return f"{v:08x}"


def runs(pattern: str, unit: int) -> list[tuple[bool, int]]:
    """Cyclic (drawn?, length in characters) runs of one repeat unit, starting at the beginning of a dash."""
    unit = max(1, min(32, int(unit)))
    cyc = [c == "-" for c in pattern[:unit]]
    if all(cyc):
        return [(True, unit)]
    if not any(cyc):
        return [(False, unit)]
    # reduce to the smallest repeating period (e.g. "- - " with unit 4 is really "- ")
    for p in range(1, unit + 1):
        if unit % p == 0 and all(cyc[i] == cyc[i % p] for i in range(unit)):
            cyc = cyc[:p]
            break
    n = len(cyc)
    start = next(i for i in range(n) if cyc[i] and not cyc[i - 1])
    rot = cyc[start:] + cyc[:start]
    out: list[tuple[bool, int]] = []
    for b in rot:
        if out and out[-1][0] == b:
            out[-1] = (b, out[-1][1] + 1)
        else:
            out.append((b, 1))
    # start with the longest dash so a chain line reads "long dash, gap, dot, gap"
    i = max(range(len(out)), key=lambda j: (out[j][0], out[j][1]))
    return out[i:] + out[:i]


def dot_mm(dpi: float) -> float:
    return 25.4 / float(dpi)


def describe(key: str, lt: dict, dpi: float = 600, print_scale: float = 1.0) -> dict:
    """Human-readable sizes: each dash / gap in printed mm and on-screen dots."""
    k = kind_of(key)
    pat = hex_to_pattern(lt["hex"], random_line=(k == "random"))
    out = {"key": key, "name": NAMES.get(key, key), "kind": k, "pattern": pat, "hex": lt["hex"].lower()}
    if k == "random":
        mm = dot_mm(dpi) * print_scale
        out.update({"amplitude_mm": lt.get("print_amp", 1) * mm, "step_mm": lt.get("print_pitch", 1) * mm,
                    "screen_amplitude_px": lt.get("amp", 1), "screen_step_px": lt.get("pitch", 1)})
        return out
    unit = int(lt.get("unit", 32))
    rs = runs(pat, unit)
    pp = lt.get("print_pitch")
    segs = []
    for drawn, n in rs:
        seg = {"drawn": drawn, "chars": n, "screen_px": n * int(lt.get("pitch", 1))}
        if pp is not None:
            seg["print_mm"] = round(n * float(pp) * dot_mm(dpi) * print_scale, 3)
        segs.append(seg)
    out["unit"] = unit
    out["segments"] = segs
    if pp is not None:
        out["cycle_mm"] = round(sum(s["print_mm"] for s in segs), 3)
    out["printed"] = k != "aux"
    return out


def from_jwf_raw(raw: dict[str, str]) -> dict[str, dict]:
    """Parse LTYPE_* values of a .jwf (key -> value string) into structured line types."""
    out: dict[str, dict] = {}
    for key in KEYS:
        v = raw.get(f"LTYPE_{key}")
        if not v:
            continue
        toks = v.split()
        if not toks or not re.fullmatch(r"[0-9a-fA-F]{1,8}", toks[0]):
            continue
        nums = []
        for t in toks[1:]:
            try:
                nums.append(int(float(t)))
            except ValueError:
                break
        lt = {"hex": toks[0].lower().rjust(8, "0")}
        k = kind_of(key)
        if k == "random":
            names = ("amp", "pitch", "print_amp", "print_pitch")
        elif k == "aux":
            names = ("unit", "pitch")
        else:
            names = ("unit", "pitch", "print_pitch")
        for name, val in zip(names, nums):
            lt[name] = val
        out[key] = lt
    return out


def to_jwf_value(key: str, lt: dict) -> str:
    k = kind_of(key)
    if k == "random":
        vals = [lt.get("amp", 1), lt.get("pitch", 1), lt.get("print_amp", 1), lt.get("print_pitch", 1)]
    elif k == "aux":
        vals = [lt.get("unit", 4), lt.get("pitch", 1)]
    else:
        vals = [lt.get("unit", 32), lt.get("pitch", 1), lt.get("print_pitch", 10)]
    return f"{lt['hex'].lower()}  " + "  ".join(f"{int(v):4d}" for v in vals)


def validate(key: str, lt: dict) -> list[str]:
    errs = []
    if not re.fullmatch(r"[0-9a-f]{8}", str(lt.get("hex", "")).lower()):
        errs.append("パターンは 32 文字（16 進 8 桁）です")
    k = kind_of(key)
    rng = {"unit": (1, 32), "pitch": (1, 16), "print_pitch": (1, 160), "amp": (1, 16), "print_amp": (1, 16)}
    for f, (lo, hi) in rng.items():
        if f in lt and not (lo <= int(lt[f]) <= hi):
            errs.append(f"{f} は {lo}〜{hi} の範囲です")
    if k in ("normal", "long", "aux") and "unit" in lt and 32 % int(lt["unit"]) != 0:
        errs.append("1 パターンのドット数は 32 の約数（1, 2, 4, 8, 16, 32）にしてください")
    return errs


def test_sheet_entities(linetypes: dict[str, dict], dpi: float = 600, length_mm: float = 100.0) -> list[dict]:
    """Entities in paper mm (put them in a layer group at scale 1/1, print at 100%) to check line types on paper:
    each printable line type 2..8 as a line of `length_mm` with the computed dash/gap sizes, plus a mm ruler."""
    ents: list[dict] = []
    x0 = -length_mm / 2
    y = 60.0
    ents.append({"type": "text", "x": x0, "y": y + 12, "text": f"線種テスト  印刷倍率 100% で印刷し、定規で測る（計算は {int(dpi)}dpi 基準）",
                 "height": 3.5, "lc": 2, "lt": 1})
    for key in ("02", "03", "04", "05", "06", "07", "08"):
        lt = linetypes.get(key) or DEFAULTS[key]
        d = describe(key, lt, dpi)
        n = int(key)
        ents.append({"type": "line", "x1": x0, "y1": y, "x2": x0 + length_mm, "y2": y, "lc": 2, "lt": n})
        sizes = " / ".join(("線" if s["drawn"] else "空き") + f" {s['print_mm']:.2f}" for s in d["segments"])
        ents.append({"type": "text", "x": x0 + length_mm + 4, "y": y - 1.2, "text": f"{d['name']}  {sizes} mm", "height": 2.5, "lc": 2, "lt": 1})
        y -= 10.0
    # ruler: 1 mm ticks, longer every 5 and 10 mm
    ry = y - 4
    ents.append({"type": "line", "x1": x0, "y1": ry, "x2": x0 + length_mm, "y2": ry, "lc": 2, "lt": 1})
    for i in range(int(length_mm) + 1):
        h = 4.0 if i % 10 == 0 else 2.5 if i % 5 == 0 else 1.5
        ents.append({"type": "line", "x1": x0 + i, "y1": ry, "x2": x0 + i, "y2": ry + h, "lc": 2, "lt": 1})
        if i % 10 == 0:
            ents.append({"type": "text", "x": x0 + i, "y": ry - 3.5, "text": str(i), "height": 2.0, "lc": 2, "lt": 1, "align": "center"})
    ents.append({"type": "text", "x": x0, "y": ry - 8, "text": "目盛は実線なので必ず正しい長さで印刷されます。点線の 1 区切りを目盛と比べてください",
                 "height": 2.5, "lc": 2, "lt": 1})
    return ents
