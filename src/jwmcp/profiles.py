"""Company / user profiles: the one place where layer groups, layer names, scales, pen colours,
text types and the title-block frame are configured.  Stored as JSON under $JWMCP_HOME/profiles/.

Profile schema (all keys optional except name):
{
  "name": "futurestudio", "company": "Future Studio", "description": "...",
  "paper": "A3", "scale": 50,                      # defaults for drawing_new
  "group_names":  {"0": "図面枠", "1": "平面図"},
  "group_scales": {"0": 1, "1": 50},               # denominators; the frame group is 1 (S=1:1)
  "layer_names":  {"1-0": "通り芯", "1-1": "壁"},
  "defaults":     {"wall": {"lg": 1, "ly": 1, "lc": 2}, ...},   # per entity type (same as presets)
  "pipe_layers":  {"給水": [2, 0]},
  "frame": {"lg": "0", "style": "strip", "margin": 16, "bottom": 11.5, "height": 19, ...},  # see arch.frame
  "frame_template": {"paper": "A3", "entities": [...]},   # captured from a .jww, paper-mm coordinates
  "text_types": {"1": {"width": 2, "height": 2, "spacing": 0, "pen": 1}, ...},   # from .jwf
  "pen_colors": {"1": [0,192,192], ...}, "print_colors": {...}, "font": "ＭＳ ゴシック",
  "sources": {"jwf": path, "jww": path}
}
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .model import PAPER_SIZES_MM, ModelError, jwmcp_home
from .presets import PRESETS


def profile_dir() -> Path:
    d = jwmcp_home() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_name(name: str) -> str:
    if not re.fullmatch(r"[\w\-\.ぁ-んァ-ン一-龠々ー]+", name):
        raise ModelError("profile name may contain letters, digits, _ - . and Japanese characters only")
    return name


def profile_path(name: str) -> Path:
    return profile_dir() / f"{_check_name(name)}.json"


def list_profiles() -> list[dict]:
    out = []
    for p in sorted(profile_dir().glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name", p.stem), "company": d.get("company", ""), "description": d.get("description", ""),
                        "paper": d.get("paper"), "scale": d.get("scale"), "groups": len(d.get("group_names", {})),
                        "layers": len(d.get("layer_names", {})), "has_frame": bool(d.get("frame") or d.get("frame_template")),
                        "has_jwf": "text_types" in d, "file": str(p)})
        except Exception as exc:  # pragma: no cover
            out.append({"name": p.stem, "error": str(exc)})
    return out


def load_profile(name: str) -> dict:
    p = profile_path(name)
    if not p.exists():
        raise ModelError(f"profile '{name}' not found; available: {[x['name'] for x in list_profiles()]}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_profile(profile: dict) -> Path:
    name = _check_name(str(profile.get("name", "")))
    profile["updated"] = time.time()
    p = profile_path(name)
    p.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def delete_profile(name: str) -> bool:
    p = profile_path(name)
    if p.exists():
        p.unlink(); return True
    return False


def _norm_key(k: str) -> str:
    k = str(k).upper()
    if "-" in k:
        g, l = k.split("-"); return f"{int(g,16):X}-{int(l,16):X}"
    return f"{int(k,16):X}"


def update_profile(name: str, *, company=None, description=None, paper=None, scale=None,
                   group_names=None, group_scales=None, layer_names=None, defaults=None, frame=None,
                   pipe_layers=None, base_preset=None, create=True) -> dict:
    try:
        prof = load_profile(name)
    except ModelError:
        if not create:
            raise
        prof = {"name": name, "created": time.time()}
    if base_preset:
        if base_preset not in PRESETS:
            raise ModelError(f"unknown preset {base_preset}")
        pr = PRESETS[base_preset]
        prof.setdefault("group_names", {}).update(pr.get("group_names", {}))
        prof.setdefault("layer_names", {}).update(pr.get("layer_names", {}))
        prof.setdefault("defaults", {}).update(pr.get("defaults", {}))
        if "pipe_layers" in pr:
            prof.setdefault("pipe_layers", {}).update(pr["pipe_layers"])
    if company is not None:
        prof["company"] = company
    if description is not None:
        prof["description"] = description
    if paper is not None:
        if paper not in PAPER_SIZES_MM:
            raise ModelError(f"paper must be one of {list(PAPER_SIZES_MM)}")
        prof["paper"] = paper
    if scale is not None:
        prof["scale"] = float(scale)
    if group_names:
        prof.setdefault("group_names", {}).update({_norm_key(k): str(v) for k, v in group_names.items()})
    if group_scales:
        prof.setdefault("group_scales", {}).update({_norm_key(k): float(v) for k, v in group_scales.items()})
    if layer_names:
        prof.setdefault("layer_names", {}).update({_norm_key(k): str(v) for k, v in layer_names.items()})
    if defaults:
        prof.setdefault("defaults", {})
        for t, d in defaults.items():
            prof["defaults"].setdefault(t, {}).update(d)
    if pipe_layers:
        prof.setdefault("pipe_layers", {}).update({k: list(v) for k, v in pipe_layers.items()})
    if frame is not None:
        prof["frame"] = frame
    save_profile(prof)
    return prof


def from_jwf(path: str, name: str, base: dict | None = None) -> dict:
    from .jwf import parse_jwf
    parsed = parse_jwf(path)
    prof = dict(base or {})
    prof["name"] = name
    if parsed.get("paper"):
        prof.setdefault("paper", parsed["paper"])
    if parsed.get("text_types"):
        prof["text_types"] = {str(k): v for k, v in parsed["text_types"].items()}
    if parsed.get("pen_colors"):
        prof["pen_colors"] = {str(k): v for k, v in parsed["pen_colors"].items()}
    if parsed.get("print_colors"):
        prof["print_colors"] = {str(k): v for k, v in parsed["print_colors"].items()}
    if parsed.get("font"):
        prof["font"] = parsed["font"]
    if parsed.get("group_scales"):
        prof.setdefault("group_scales", {})
        for k, v in parsed["group_scales"].items():
            prof["group_scales"].setdefault(k, v)
    if parsed.get("group_names"):
        prof.setdefault("group_names", {}).update(parsed["group_names"])
    if parsed.get("layer_names"):
        prof.setdefault("layer_names", {}).update(parsed["layer_names"])
    # keep a copy of the source next to the profile so a later .jwf export can carry the rest of the
    # user's environment (uploads land in a temp folder that disappears)
    src = Path(path).expanduser()
    keep = profile_dir() / f"{name}.source.jwf"
    try:
        if src.resolve() != keep.resolve():
            keep.write_bytes(src.read_bytes())
        prof.setdefault("sources", {})["jwf"] = str(keep)
        prof["sources"]["jwf_original"] = str(src)
    except OSError:
        prof.setdefault("sources", {})["jwf"] = str(src)
    save_profile(prof)
    return prof


def build_frame_template(entities: list[dict], scale_for, paper: str, *, frame_texts: str = "all",
                         source: str = "") -> dict:
    """Turn real-mm entities (a title block drawn in Jw_cad) into a paper-mm frame template.

    frame_texts: "all" keeps every text (draw the template with empty value cells and any fixed text such
    as the company name at the size you want); "labels" keeps only No./Title/Drawing/Scale/Note style labels.
    Embedded image references (^@BM...) are always dropped.
    """
    ents = []
    for e in entities:
        if e.get("temporary") or e.get("type") in ("block", "solid_circle"):
            continue
        if e["type"] == "text":
            txt = e.get("text", "")
            if txt.startswith("^@"):
                continue
            if frame_texts == "labels" and not _is_label(txt):
                continue
        ents.append(_to_paper(e, scale_for(e)))
    if not ents:
        raise ModelError("no frame entities found")
    return {"paper": paper, "entities": ents, "source": source, "texts": frame_texts, "count": len(ents)}


def from_jww(path: str, name: str, base: dict | None = None, frame_lg: int | None = None,
             keep_default_names: bool = False, frame_texts: str = "all") -> dict:
    """Learn layer-group scales / names and layer names from a .jww; optionally capture the group
    `frame_lg` as a title-block template (converted to paper mm so it can be re-used at S=1:1)."""
    from .jww_read import load
    f = load(path)
    prof = dict(base or {})
    prof["name"] = name
    used_groups = {e["lg"] for e in f.entities}
    gs, gn, ln = prof.setdefault("group_scales", {}), prof.setdefault("group_names", {}), prof.setdefault("layer_names", {})
    for g, sc in f.group_scales.items():
        if g in used_groups or g == frame_lg:
            gs[f"{g:X}"] = sc
    for g, nm in f.group_names.items():
        if nm and (keep_default_names or not re.fullmatch(r"Group[0-9A-F]", nm)):
            gn[f"{g:X}"] = nm
    for key, nm in f.layer_names.items():
        if nm and (keep_default_names or not re.fullmatch(r"[0-9A-F]-[0-9A-F]", nm)):
            ln[key] = nm
    if frame_lg is not None:
        from .model import PAPER_BY_CODE
        paper = PAPER_BY_CODE.get(int(f.header.get("paper_size", 3)), "A3")
        sel = [e for e in f.entities if e["lg"] == frame_lg]
        tpl = build_frame_template(sel, f.scale_of, paper, frame_texts=frame_texts, source=str(Path(path).expanduser()))
        tpl["source_lg"] = f"{frame_lg:X}"; tpl["source_scale"] = f.group_scales.get(frame_lg, 1.0)
        prof["frame_template"] = tpl
        prof.setdefault("frame", {"lg": "F", "style": "template"})
        prof["frame"]["style"] = "template"
    prof.setdefault("sources", {})["jww"] = str(Path(path).expanduser())
    save_profile(prof)
    return prof


def set_logo(name: str, image_path: str, width_mm: float, *, threshold: int | None = None, invert: bool = False,
             simplify_px: float = 1.0, min_area_px: float = 16.0, lc: int = 2, margin: float = 2.0) -> dict:
    """Trace a bitmap logo and store it in profile.frame.logo (polylines in paper mm)."""
    from .raster import trace_image
    prof = load_profile(name)
    res = trace_image(image_path, width_mm, threshold=threshold, invert=invert, simplify_px=simplify_px,
                      min_area_px=min_area_px)
    prof.setdefault("frame", {"lg": "F", "style": "strip"})
    prof["frame"]["logo"] = {"polylines": [{"points": pl["points"], "hole": pl["hole"]} for pl in res["polylines"]],
                             "width_mm": res["width_mm"], "height_mm": res["height_mm"], "source": Path(image_path).name,
                             "lc": lc, "margin": margin, "points": res["points"]}
    save_profile(prof)
    return {"profile": name, "polylines": res["count"], "points": res["points"], "width_mm": res["width_mm"],
            "height_mm": round(res["height_mm"], 2), "threshold": res["threshold"]}


def clear_logo(name: str) -> dict:
    prof = load_profile(name)
    removed = bool(prof.get("frame", {}).pop("logo", None))
    save_profile(prof)
    return {"profile": name, "removed": removed}


def frame_from_job(job, name: str, base: dict | None = None, paper: str | None = None,
                   frame_texts: str = "all") -> dict:
    """Capture the entities of a 外部変形 job (the frame selected in Jw_cad) as the profile's frame template."""
    prof = dict(base or {})
    prof["name"] = name
    if not paper:
        if job.hzs:
            w, h = job.hzs
            for p, (pw, ph) in PAPER_SIZES_MM.items():
                if abs(pw - w) < 2 and abs(ph - h) < 2:
                    paper = p; break
        paper = paper or prof.get("paper") or "A3"
    tpl = build_frame_template(job.entities, lambda e: job.hs[int(e.get("lg", 0))], paper,
                               frame_texts=frame_texts, source=f"外部変形 job ({job.file or 'Jw_cad'})")
    prof["frame_template"] = tpl
    prof.setdefault("frame", {"lg": "F", "style": "template"})
    prof["frame"]["style"] = "template"
    save_profile(prof)
    return prof


FRAME_LABELS = {
    "no": ("no", "no.", "図番", "図面番号", "番号"),
    "title": ("title", "工事名", "物件名", "件名", "プロジェクト"),
    "drawing": ("drawing", "図面名", "図名"),
    "scale": ("scale", "縮尺"),
    "note": ("note", "備考", "注記"),
    "date": ("date", "日付", "年月日"),
    "company": ("company", "設計", "会社名"),
}


def label_key(text: str) -> str | None:
    t = text.strip().lower()
    for key, names in FRAME_LABELS.items():
        if t in names:
            return key
    return None


def _is_label(text: str) -> bool:
    return label_key(text) is not None


def _to_paper(e: dict, sc: float) -> dict:
    """Convert a normalised entity (real mm at scale sc) to paper mm (scale 1)."""
    from .model import rescale_prim
    e2 = {k: v for k, v in e.items() if k not in ("id", "flag", "extent", "block", "style", "base_point", "lg")}
    if e2["type"] == "dimfigure":
        e2 = {"type": "line", "x1": e["x1"], "y1": e["y1"], "x2": e["x2"], "y2": e["y2"], "ly": e["ly"], "lc": e["lc"], "lt": e["lt"]}
    return rescale_prim(e2, 1.0 / sc)


def apply_to_drawing(prof: dict, d) -> None:
    """Push profile group/layer settings into a Drawing (called by drawing_new)."""
    for k, v in prof.get("group_names", {}).items():
        d.group_names[int(k, 16)] = v
    for k, v in prof.get("group_scales", {}).items():
        d.group_scales[int(k, 16)] = float(v)
    for k, v in prof.get("layer_names", {}).items():
        d.layer_names[_norm_key(k)] = v
    d.profile = prof["name"]


def frame_entity(prof: dict, paper: str, fields: dict | None = None, lg: str | int | None = None) -> dict:
    """Build the frame entity for a paper size from the profile's frame settings."""
    fr = dict(prof.get("frame") or {"style": "strip"})
    if lg is not None:
        fr["lg"] = lg
    g = fr.get("lg", "F")
    g = int(g, 16) if isinstance(g, str) else int(g)
    ent = {"type": "frame", "paper": paper, "lg": g, "ly": int(fr.get("ly", 0)),
           "style": fr.get("style", "strip"), "fields": dict(fr.get("fields", {}))}
    for k in ("margin", "bottom", "height", "border", "border_margin", "labels", "lc_outer", "lc_div", "lc_label",
              "lc_value", "label_height", "title_height", "value_height", "company_height", "logo_text", "columns", "logo"):
        if k in fr:
            ent[k] = fr[k]
    if fields:
        ent["fields"].update(fields)
    if ent["style"] == "template":
        tpl = prof.get("frame_template")
        if not tpl:
            raise ModelError("profile has frame.style=template but no frame_template (use profile_from_jww with frame_lg)")
        ent["template"] = tpl
    return ent
