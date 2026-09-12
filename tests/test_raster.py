import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw  # noqa: E402

from jwmcp import profiles  # noqa: E402
from jwmcp.model import Drawing, primitives  # noqa: E402
from jwmcp.raster import trace_image, trace_to_entities  # noqa: E402


def _logo(tmp_path):
    im = Image.new("RGB", (200, 100), "white")
    dr = ImageDraw.Draw(im)
    dr.rectangle([10, 10, 90, 90], fill="black")            # square with a hole
    dr.rectangle([35, 35, 65, 65], fill="white")
    dr.ellipse([110, 10, 190, 90], fill="black")            # disc
    p = tmp_path / "logo.png"
    im.save(p)
    return p


def test_trace_shapes(tmp_path):
    res = trace_image(str(_logo(tmp_path)), width_mm=40)
    assert res["px"] == [200, 100] and abs(res["height_mm"] - 20) < 1e-9
    assert res["count"] == 3 and sum(1 for p in res["polylines"] if p["hole"]) == 1
    outer_sq = max(res["polylines"], key=lambda p: p["area_mm2"] if not p["hole"] and p["points"][0][0] < 20 else 0)
    xs = [q[0] for q in outer_sq["points"]]; ys = [q[1] for q in outer_sq["points"]]
    assert abs(min(xs) - 2.0) < 0.3 and abs(max(xs) - 18.0) < 0.3 and abs(min(ys) - 2.0) < 0.3   # 10px = 2mm, y up
    ents = trace_to_entities(res, x=100, y=200, scale=2, lg=3)
    assert ents[0]["type"] == "polyline" and ents[0]["closed"] and ents[0]["lg"] == 3
    assert min(q[0] for e in ents for q in e["points"]) >= 100


def test_logo_in_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    profiles.update_profile("lg", paper="A3", scale=50, frame={"lg": "F", "style": "strip", "fields": {"company": "X"}})
    r = profiles.set_logo("lg", str(_logo(tmp_path)), 40)
    assert r["polylines"] == 3
    fe = profiles.frame_entity(profiles.load_profile("lg"), "A3")
    d = Drawing("d", scale=50); d.group_scales[15] = 1.0; d.add([fe])
    prims = list(primitives(d.entities[0], 1.0))
    logo_lines = [p for p in prims if p.get("logo")]
    assert logo_lines and not any(p["type"] == "text" and p["text"] == "X" for p in prims)   # logo replaces the text
    xs = [v for p in logo_lines for v in (p["x1"], p["x2"])]; ys = [v for p in logo_lines for v in (p["y1"], p["y2"])]
    assert min(xs) > 194 - 77 and max(xs) < 194                      # inside the logo cell (77 mm wide, right edge 194)
    assert min(ys) > -137 and max(ys) < -118                          # inside the 19 mm strip
    assert profiles.clear_logo("lg")["removed"]
