import math
from pathlib import Path

import pytest

from jwmcp import scan
from jwmcp.model import Drawing, ModelError, normalize_entity, primitives
from jwmcp.render import render

PLAN_PDF = Path.home() / "Desktop/Studio/01_FutureStudio_平面図.pdf"


def _kinds(prims):
    from collections import Counter
    return Counter(p["type"] for p in prims)


def test_wall_straight_with_door():
    e = normalize_entity({"type": "wall", "points": [[0, 0], [5000, 0]], "thickness": 150, "lg": 4, "ly": 0, "lc": 3,
                          "core": True, "core_ly": 1, "core_extend": 300,
                          "openings": [{"at": 1000, "width": 800, "kind": "door", "hinge": "start", "side": "+", "frame": 25}],
                          "opening_lg": 3, "opening_lc": 1})
    prims = list(primitives(e, 100))
    k = _kinds(prims)
    assert k["arc"] == 1
    faces = [p for p in prims if p["type"] == "line" and p.get("lg") == 4 and p.get("ly") == 0]
    # two faces cut into 2 pieces each + 2 end caps = 6
    assert len(faces) == 6
    ys = sorted({round(p["y1"], 3) for p in faces})
    assert ys == [-75.0, 75.0]
    core = [p for p in prims if p.get("core")]
    assert len(core) == 1 and core[0]["x1"] == -300 and core[0]["x2"] == 5300 and core[0]["ly"] == 1 and core[0]["lt"] == 5
    jambs = [p for p in prims if p["type"] == "line" and p.get("lg") == 3 and abs(p["x1"] - p["x2"]) < 1e-9
             and abs(p["y2"] - p["y1"]) <= 200 + 1e-9]
    assert len(jambs) == 2 and {round(p["x1"]) for p in jambs} == {1000, 1800}
    assert all(abs(abs(p["y1"]) - 100) < 1e-9 for p in jambs)   # frame 25 beyond the 75 faces
    arc = [p for p in prims if p["type"] == "arc"][0]
    assert arc["cx"] == 1000 and arc["cy"] == 75 and arc["r"] == 800 and (arc["start"], arc["end"]) == (0.0, 90.0)


def test_wall_corner_miter_and_closed():
    e = normalize_entity({"type": "wall", "points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "thickness": 200, "closed": True})
    prims = list(primitives(e, 100))
    lines = [p for p in prims if p["type"] == "line"]
    assert len(lines) == 8   # 4 outer + 4 inner, no caps
    xs = sorted({round(v) for p in lines for v in (p["x1"], p["x2"])})
    assert xs == [-100, 100, 3900, 4100]


def test_wall_opening_errors():
    with pytest.raises(ModelError):
        list(primitives(normalize_entity({"type": "wall", "points": [[0, 0], [1000, 0]], "openings": [{"at": 500, "width": 800}]}), 100))
    with pytest.raises(ModelError):
        list(primitives(normalize_entity({"type": "wall", "points": [[0, 0], [1000, 0], [1000, 1000]], "openings": [{"at": 800, "width": 400}]}), 100))


def test_grid_column_room_pipe_equipment(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    d = Drawing("t", scale=100)
    d.add([
        {"type": "grid", "xs": [0, 3640, 7280], "ys": [0, 5460], "extend": 1000, "dims": True},
        {"type": "column", "cx": 0, "cy": 0, "w": 600, "h": 600},
        {"type": "room", "x": 1820, "y": 2730, "name": "事務室", "note": "20㎡"},
        {"type": "pipe", "points": [[0, -1000], [7280, -1000], [7280, 3000]], "system": "排水", "diameter": "75A"},
        {"type": "equipment", "kind": "toilet", "x": 500, "y": 500, "angle": 90},
    ])
    prims = d.primitives()
    k = _kinds(prims)
    assert k["circle"] >= 5 + 1 and k["text"] >= 5 + 2 + 1 + 1
    pipe = [p for p in prims if p.get("pipe") == "排水"]
    assert len(pipe) == 2 and pipe[0]["lc"] == 2
    label = [p for p in prims if p["type"] == "text" and p["text"] == "排水 75A"][0]
    assert abs(label["angle"]) < 1e-9
    png = render(d.entities, str(tmp_path / "arch.png"), scale_for=d.scale_of)
    assert Path(png["png"]).stat().st_size > 1000


def test_scan_calibration_math(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    from PIL import Image
    img = tmp_path / "s.png"
    Image.new("RGB", (400, 300), "white").save(img)
    info = scan.open_scan(str(img), scan_id="s")
    assert info["pages"][0]["w"] == 400
    c = scan.calibrate("s", 1, p1=[0, 300], p2=[400, 300], distance_mm=8000, origin_px=[0, 300])
    cal = c["calibration"]
    assert math.isclose(cal["ppm"], 0.05)
    assert scan.px_to_mm(cal, 400, 0) == [8000.0, 6000.0]
    assert scan.mm_to_px(cal, 8000, 6000) == [400.0, 0.0]
    v = scan.view("s", 1, region=[0.25, 0.25, 0.75, 0.75])
    assert v["region_px"] == [100, 75, 300, 225] and "region_mm" in v
    d = Drawing("ov", scale=100)
    d.add([{"type": "rect", "x": 0, "y": 0, "w": 8000, "h": 6000}])
    ov = scan.overlay("s", 1, d.entities, d.scale_of)
    assert Path(ov["png"]).exists()


@pytest.mark.skipif(not PLAN_PDF.exists(), reason="sample PDF not on this machine")
def test_scan_vector_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    info = scan.open_scan(str(PLAN_PDF), dpi=72, scan_id="plan")
    assert info["pages"][0]["vector"] and info["pages"][0]["has_text"]
    c = scan.calibrate("plan", 1, scale=30)
    assert math.isclose(c["mm_per_px"], 25.4 / 72 * 30, rel_tol=1e-3)
    v = scan.vector_lines("plan", 1, min_len_mm=10)
    assert v["count"] > 500
    t = scan.texts("plan", 1)
    assert any("3,360" in x["text"] for x in t["texts"])
