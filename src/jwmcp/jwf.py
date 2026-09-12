"""Reader for Jw_cad environment settings files (.jwf / Jw_win.jwf).

Only the parts that matter for drawing exchange are interpreted; everything else is kept in `raw`.
  S_COMM_0   paper size (3rd token, e.g. A3)
  LCOLLOR_n  screen colour of 線色 n (r g b [flag])
  PCOLLOR_n  printer colour of 線色 n (r g b width_index width_mm)
  MWIDE/MHIGH/MDIST/MPEN   文字種 1..10 width / height / spacing / pen colour
  MHEN       default font ("$<ＭＳ ゴシック>")
  LAYSCALE   default scale denominator of layer groups 0..F
  LAYNAM_g   "group name,layer0 name,...,layer15 name"
  LTYPE_nn   line type bit patterns
"""
from __future__ import annotations

import re
from pathlib import Path


def _nums(tokens: list[str]) -> list[float]:
    out = []
    for t in tokens:
        try:
            out.append(float(t))
        except ValueError:
            break
    return out


def parse_jwf(path: str) -> dict:
    p = Path(path).expanduser()
    data = p.read_bytes()
    try:
        text = data.decode("cp932")
    except UnicodeDecodeError:
        text = data.decode("cp932", errors="replace")
    raw: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        raw[k.strip()] = v.strip()

    out: dict = {"source": str(p), "raw_keys": len(raw), "raw": raw}

    if "S_COMM_0" in raw:
        toks = raw["S_COMM_0"].split()
        if len(toks) >= 3 and re.fullmatch(r"[AB]\d|[2-5]A|\d+m", toks[2]):
            out["paper"] = toks[2]

    pens: dict[int, list[int]] = {}
    for n in range(1, 10):
        key = f"LCOLLOR_{n}"
        if key in raw:
            v = _nums(raw[key].split())
            if len(v) >= 3:
                pens[n] = [int(v[0]), int(v[1]), int(v[2])]
    if "LCOLLOR_G" in raw and 9 not in pens:
        v = _nums(raw["LCOLLOR_G"].split())
        if len(v) >= 3:
            pens[9] = [int(v[0]), int(v[1]), int(v[2])]
    out["pen_colors"] = pens

    prints: dict[int, dict] = {}
    for n in range(1, 10):
        key = f"PCOLLOR_{n}"
        if key in raw:
            v = _nums(raw[key].split())
            if len(v) >= 3:
                d = {"rgb": [int(v[0]), int(v[1]), int(v[2])]}
                if len(v) >= 4:
                    d["width_index"] = int(v[3])
                if len(v) >= 5:
                    d["width_mm"] = v[4]
                prints[n] = d
    out["print_colors"] = prints

    w = _nums(raw.get("MWIDE", "").split()); h = _nums(raw.get("MHIGH", "").split())
    d = _nums(raw.get("MDIST", "").split()); c = _nums(raw.get("MPEN", "").split())
    if len(w) >= 10 and len(h) >= 10:
        out["text_types"] = {n + 1: {"width": w[n], "height": h[n], "spacing": d[n] if n < len(d) else 0.0,
                                     "pen": int(c[n]) if n < len(c) else 1} for n in range(10)}
    if "MHEN" in raw:
        m = re.search(r"\$<(.+?)>", raw["MHEN"])
        if m:
            out["font"] = m.group(1)

    if "LAYSCALE" in raw:
        v = _nums(raw["LAYSCALE"].split())
        if len(v) >= 16:
            out["group_scales"] = {f"{i:X}": v[i] for i in range(16)}

    group_names: dict[str, str] = {}
    layer_names: dict[str, str] = {}
    for g in range(16):
        key = f"LAYNAM_{g:X}"
        if key in raw:
            fields = raw[key].split(",")
            if fields and fields[0].strip():
                group_names[f"{g:X}"] = fields[0].strip()
            for li, nm in enumerate(fields[1:17]):
                if nm.strip():
                    layer_names[f"{g:X}-{li:X}"] = nm.strip()
    out["group_names"] = group_names
    out["layer_names"] = layer_names

    lts = {}
    for n in range(2, 10):
        key = f"LTYPE_{n:02d}"
        if key in raw:
            toks = raw[key].split()
            lts[n] = {"pattern_hex": toks[0], "params": _nums(toks[1:])}
    out["linetypes"] = lts
    return out


def write_jwf(profile: dict, out: str, base_jwf: str | None = None) -> dict:
    """Write a Jw_cad environment file carrying the profile's layer-group names / layer names / scales,
    pen colours, printer widths and text types. Load it in Jw_cad (設定 > 環境設定ファイル > 読込) or save it as
    Jw_win.jwf next to Jw_win.exe. Lines the profile does not define are copied from `base_jwf` (the file the
    profile was imported from, when available) so nothing else in the user's environment changes."""
    base_path = base_jwf or (profile.get("sources") or {}).get("jwf")
    lines: list[str] = []
    if base_path and Path(base_path).expanduser().exists():
        raw = Path(base_path).expanduser().read_bytes()
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError:
            text = raw.decode("cp932", errors="replace")
        lines = text.splitlines()
    new: dict[str, str] = {}
    gs = profile.get("group_scales") or {}
    if gs:
        cur = {}
        for ln in lines:
            if ln.strip().startswith("LAYSCALE"):
                cur = {f"{i:X}": v for i, v in enumerate(_nums(ln.split("=", 1)[1].split()))}
        vals = [str(int(gs.get(f"{i:X}", cur.get(f"{i:X}", 1)))) if float(gs.get(f"{i:X}", cur.get(f"{i:X}", 1))).is_integer()
                else str(gs.get(f"{i:X}", cur.get(f"{i:X}", 1))) for i in range(16)]
        new["LAYSCALE"] = " ".join(vals)
    gn = profile.get("group_names") or {}
    ln_ = profile.get("layer_names") or {}
    if gn or ln_:
        for g in range(16):
            key = f"{g:X}"
            fields = [gn.get(key, "")] + [ln_.get(f"{key}-{l:X}", "") for l in range(16)]
            new[f"LAYNAM_{key}"] = ",".join(fields)
    for n, rgb in (profile.get("pen_colors") or {}).items():
        if 1 <= int(n) <= 8 and len(rgb) == 3:
            new[f"LCOLLOR_{int(n)}"] = f"{int(rgb[0]):3d}  {int(rgb[1]):3d}  {int(rgb[2]):3d}    1"
    for n, d in (profile.get("print_colors") or {}).items():
        if 1 <= int(n) <= 8 and d.get("rgb"):
            r, g, b = d["rgb"]
            new[f"PCOLLOR_{int(n)}"] = f"{int(r):3d}  {int(g):3d}  {int(b):3d}    {int(d.get('width_index', 1))}    {float(d.get('width_mm', 0.3)):.2f}"
    tt = profile.get("text_types") or {}
    if len(tt) >= 10:
        rows = [tt[str(n)] if str(n) in tt else tt.get(n, {}) for n in range(1, 11)]
        new["MWIDE"] = "  ".join(f"{float(r.get('width', 2)):.1f}" for r in rows)
        new["MHIGH"] = "  ".join(f"{float(r.get('height', 2)):.1f}" for r in rows)
        new["MDIST"] = "  ".join(f"{float(r.get('spacing', 0)):.1f}" for r in rows)
        new["MPEN"] = "  ".join(f"{int(r.get('pen', 1))}" for r in rows)
    out_lines: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        s = ln.strip()
        if "=" in s and not s.startswith("#"):
            k = s.split("=", 1)[0].strip()
            if k in new:
                out_lines.append(f"{k} = {new[k]}")
                seen.add(k)
                continue
        out_lines.append(ln)
    for k, v in new.items():
        if k not in seen:
            out_lines.append(f"{k} = {v}")
    if not lines:
        out_lines.insert(0, f"# jwmcp profile '{profile.get('name')}' — Jw_cad 環境設定ファイル（設定 > 環境設定ファイル > 読込）")
    outp = Path(out).expanduser()
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_bytes(("\r\n".join(out_lines) + "\r\n").encode("cp932", errors="replace"))
    return {"jwf": str(outp), "keys_written": sorted(new), "based_on": base_path,
            "how_to_apply": "Jw_cad: 設定 > 環境設定ファイル > 読込 でこのファイルを選ぶ（新規図面から有効。Jw_win.exe の隣に Jw_win.jwf として置けば起動時に自動）"}


def pen_palette_colorref(pen_colors: dict) -> list[int]:
    """Build the 10-entry COLORREF palette used by the renderer from parsed pen colours."""
    from .model import DEFAULT_PEN_COLORREF
    pal = list(DEFAULT_PEN_COLORREF)
    for n, rgb in pen_colors.items():
        n = int(n)
        if 1 <= n <= 9 and len(rgb) == 3:
            r, g, b = rgb
            pal[n] = int(r) | (int(g) << 8) | (int(b) << 16)
    return pal


def summary(parsed: dict) -> dict:
    return {k: v for k, v in parsed.items() if k != "raw"}
