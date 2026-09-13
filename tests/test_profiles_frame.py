import math
from pathlib import Path

import pytest

from jwmcp import jwc_temp, profiles
from jwmcp.jwf import parse_jwf
from jwmcp.model import Drawing, normalize_entity, primitives

JWF = Path.home() / "Desktop/jww/jw_win.JWF"
KDIC = Path.home() / "Library/CloudStorage/GoogleDrive-cafegolazo@gmail.com/マイドライブ/_Project/20260804_唐津DX/制作/KDICリニューアルプラン_2.jww"


def test_frame_strip_geometry():
    e = normalize_entity({"type": "frame", "paper": "A3", "lg": 15, "fields": {"no": "01", "title": "テスト計画", "drawing": "平面図", "scale": "S=1:50", "note": "備考"}})
    prims = list(primitives(e, 1.0))
    lines = [p for p in prims if p["type"] == "line"]
    texts = [p for p in prims if p["type"] == "text"]
    xs = {round(v, 1) for p in lines for v in (p["x1"], p["x2"])}
    assert -194.0 in xs and 194.0 in xs                     # 16 mm side margins on 420 mm
    ys = {round(v, 1) for p in lines for v in (p["y1"], p["y2"])}
    assert -137.0 in ys and -118.0 in ys                    # bottom 11.5 mm, height 19 mm
    assert {t["text"] for t in texts} >= {"No.", "Title", "Drawing", "Scale", "Note", "01", "テスト計画", "平面図", "S=1:50", "備考"}
    assert all(p["lg"] == 15 for p in prims)
    # A1 version is wider, same height
    e1 = normalize_entity({"type": "frame", "paper": "A1"})
    xs1 = {round(v, 1) for p in primitives(e1, 1.0) if p["type"] == "line" for v in (p["x1"], p["x2"])}
    assert max(xs1) == 841 / 2 - 16


def test_frame_scaled_into_main_scale(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    d = Drawing("f", scale=50, paper="A3")
    d.group_scales[15] = 1.0
    d.add([{"type": "frame", "paper": "A3", "lg": 15}, {"type": "line", "x1": 0, "y1": 0, "x2": 1000, "y2": 0}])
    raw = d.primitives()
    uni = d.primitives(unify_scale=True)
    fr_raw = max(abs(p["x1"]) for p in raw if p.get("frame") and p["type"] == "line")
    fr_uni = max(abs(p["x1"]) for p in uni if p.get("frame") and p["type"] == "line")
    assert math.isclose(fr_raw, 194) and math.isclose(fr_uni, 194 * 50)
    txt = jwc_temp.serialize(d.entities, scale_for=d.scale_of)      # 外部変形: per-group real mm, no rescale
    assert "lgf" in txt and "-194 -137 194 -137" in txt


def test_profile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    prof = profiles.update_profile("test_co", company="Test", paper="A3", scale=50, base_preset="arch_jp",
                                   group_names={"F": "図面枠"}, group_scales={"F": 1}, layer_names={"0-1": "壁(改)"},
                                   frame={"lg": "F", "style": "strip", "fields": {"company": "Test Co."}})
    assert prof["group_scales"]["F"] == 1 and prof["layer_names"]["0-1"] == "壁(改)"
    assert profiles.list_profiles()[0]["has_frame"]
    d = Drawing("p", scale=50, paper="A3")
    profiles.apply_to_drawing(profiles.load_profile("test_co"), d)
    assert d.group_names[15] == "図面枠" and d.group_scales[15] == 1.0 and d.profile == "test_co"
    ids = d.add([{"type": "wall", "points": [[0, 0], [1000, 0]]}])
    assert d.entities[0]["ly"] == 1                       # preset default via profile
    fe = profiles.frame_entity(profiles.load_profile("test_co"), "A4", {"title": "X"})
    assert fe["lg"] == 15 and fe["fields"]["company"] == "Test Co." and fe["fields"]["title"] == "X"


def test_jwc_temp_base_offsets():
    j = jwc_temp.parse("hzs 420 297\nhs 50 50 50 50 50 50 50 50 50 50 50 50 50 50 50 50\nhn 0 0 100 100\nhp1 10500 7425\n#\nlg0\n10500 7425 11500 7425\n")
    assert j.to_drawing_coords()
    e = j.entities[0]
    assert e["x1"] == 0 and e["y1"] == 0 and e["x2"] == 1000
    assert j.points["hp1"] == {"x": 0.0, "y": 0.0}
    off = j.base_offsets()
    txt = jwc_temp.serialize([normalize_entity({"type": "line", "x1": 0, "y1": 0, "x2": 1000, "y2": 0})],
                             scale_for=lambda e: 50.0, offset_for=lambda lg: off[lg])
    assert "10500 7425 11500 7425" in txt


@pytest.mark.skipif(not JWF.exists(), reason="no jw_win.JWF on this machine")
def test_parse_real_jwf(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    p = parse_jwf(str(JWF))
    assert p["paper"] == "A3" and p["pen_colors"][1] == [0, 192, 192] and p["text_types"][3]["height"] == 3.0
    assert p["group_scales"]["0"] == 50 and p["font"] == "ＭＳ ゴシック"
    prof = profiles.from_jwf(str(JWF), "fs")
    assert prof["text_types"]["3"]["width"] == 2.5
    assert prof["print_colors"]["2"]["width"] == 3 and prof["print_colors"]["2"]["point_radius"] == 0.3
    assert prof["line_width_unit"] == {"raw": 100, "mode": "dots"} and prof["linetypes"]["02"]["hex"] == "aaaaaaaa"


@pytest.mark.skipif(not KDIC.exists(), reason="KDIC drawing not on this machine")
def test_profile_from_kdic_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    prof = profiles.from_jww(str(KDIC), "fs", frame_lg=0)
    tpl = prof["frame_template"]
    assert tpl["paper"] == "A3" and tpl["source_scale"] == 50 and len(tpl["entities"]) >= 25
    xs = [v for e in tpl["entities"] if e["type"] == "line" for v in (e["x1"], e["x2"])]
    assert math.isclose(max(xs), 194.0, abs_tol=0.01) and math.isclose(min(xs), -195.2, abs_tol=0.5)
    fe = profiles.frame_entity(prof, "A4")
    d = Drawing("k", scale=50)
    d.group_scales[15] = 1.0
    d.add([fe])
    prims = list(primitives(d.entities[0], 1.0))
    assert any(p["type"] == "text" and p["text"] == "Title" for p in prims)
