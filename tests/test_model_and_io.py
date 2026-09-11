import os
from pathlib import Path

import pytest

from jwmcp import bridge, jwc_temp
from jwmcp.dxf_out import write_dxf
from jwmcp.model import Drawing, ModelError, normalize_entity, text_length_paper
from jwmcp.render import render

SAMPLES = [p for p in [Path.home() / "Desktop/jww/木造平面例.jww", Path.home() / "Desktop/Studio/01_FutureStudio_平面図.jww"] if p.exists()]


def test_text_length_units():
    assert text_length_paper("ＤＫ", 4, 0.5) == 8.5
    assert text_length_paper("A1", 4, 0) == 4.0


def test_normalize_rejects_bad():
    with pytest.raises(ModelError):
        normalize_entity({"type": "line", "x1": 0})
    with pytest.raises(ModelError):
        normalize_entity({"type": "circle", "cx": 0, "cy": 0, "r": 0})
    with pytest.raises(ModelError):
        normalize_entity({"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "lg": 16})
    e = normalize_entity({"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "lg": "A", "ly": "f"})
    assert e["lg"] == 10 and e["ly"] == 15


def test_drawing_persist_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    d = Drawing("house", scale=100, paper="A3")
    d.group_names[0] = "平面図"; d.layer_names["0-1"] = "壁"
    ids = d.add([
        {"type": "rect", "x": 0, "y": 0, "w": 7280, "h": 5460, "ly": 1, "lc": 2},
        {"type": "text", "x": 3640, "y": 2730, "text": "リビング", "height": 5, "align": "center", "ly": 7},
        {"type": "dimension", "x1": 0, "y1": 0, "x2": 7280, "y2": 0, "offset": -900, "ly": 10},
        {"type": "circle", "cx": 1000, "cy": 1000, "r": 300, "lt": 3},
        {"type": "solid", "points": [[0, 0], [500, 0], [500, 500], [0, 500]], "rgb": [200, 200, 255]},
    ])
    assert len(ids) == 5
    d.save()
    d2 = Drawing.load("house")
    assert len(d2.entities) == 5 and d2.layer_names["0-1"] == "壁"
    assert d2.bbox()["width"] == 7280

    dxf = write_dxf(d2.entities, str(tmp_path / "h.dxf"), scale_for=d2.scale_of, layer_names=d2.layer_names)
    assert dxf["entities"] >= 10 and "01_壁" in dxf["layers"]
    import ezdxf
    doc = ezdxf.readfile(str(tmp_path / "h.dxf"))
    assert len(list(doc.modelspace())) == dxf["entities"]

    png = render(d2.entities, str(tmp_path / "h.png"), scale_for=d2.scale_of)
    assert Path(png["png"]).stat().st_size > 1000

    txt = jwc_temp.serialize(d2.entities, scale_for=d2.scale_of, group_names=d2.group_names, layer_names=d2.layer_names)
    assert "lgn平面図" in txt and "lyn壁" in txt and "lc10 " in txt and "sl " in txt


def test_bridge_roundtrip(tmp_path):
    ex = tmp_path / "ex"
    info = bridge.setup(ex, r"G:\マイドライブ\JW_MCP_Exchange", wait=5)
    bats = {Path(p).name for p in info["bat_files"]}
    assert bats == {"JWMCP_send.bat", "JWMCP_send_all.bat", "JWMCP_import.bat"}
    raw = (ex / "gaihen" / "JWMCP_send.bat").read_bytes()
    assert raw.startswith(b"REM ") and b"REM #jww" in raw and b"REM #h2" in raw and b"\r\n" in raw
    assert r"G:\マイドライブ\JW_MCP_Exchange".encode("cp932") in raw
    # simulate Jw_cad dropping a job
    job = "20260912_120000_send"
    (ex / "inbox" / f"{job}.txt").write_bytes("hq\r\nhs 100 100\r\nhn 0 0 10 10\r\n#\r\nlg0\r\nly1\r\n0 0 1000 0\r\n".encode("cp932"))
    jobs = bridge.list_jobs(ex)
    assert jobs[0]["id"] == job and jobs[0]["entity_count"] == 1 and jobs[0]["selection_range"] == [0, 0, 10, 10]
    j = bridge.read_job(ex, job)
    assert j.entities[0]["ly"] == 1
    text = jwc_temp.serialize([normalize_entity({"type": "line", "x1": 0, "y1": 0, "x2": 5, "y2": 5})])
    r = bridge.respond(ex, job, text)
    out = ex / "outbox" / f"{job}.txt"
    assert out.exists() and not (ex / "inbox" / f"{job}.txt").exists() and (ex / "done" / f"{job}.txt").exists()
    assert out.read_bytes() == text.encode("cp932")
    with pytest.raises(FileNotFoundError):
        bridge.respond(ex, job, text)
    st = bridge.status(ex)
    assert st["pending_jobs"] == 0 and st["unconsumed_responses"] == [f"{job}.txt"]
    imp = bridge.prepare_import(ex, text)
    assert Path(imp["outbox"]).name == "IMPORT.txt"


@pytest.mark.skipif(not SAMPLES, reason="no sample .jww on this machine")
def test_read_real_jww(tmp_path):
    from jwmcp import jww_read
    for p in SAMPLES:
        f = jww_read.load(str(p))
        s = f.summary()
        assert s["entity_count"] > 100 and s["jww_version"] in (420, 600, 700)
        assert s["bbox_real_mm"]["width"] > 1000     # real mm, not paper mm
        r = f.query(types=["text"], limit=5)
        assert r["returned"] <= 5
        png = render(f.entities, str(tmp_path / (p.stem + ".png")), scale_for=f.scale_of, width_px=800)
        assert Path(png["png"]).stat().st_size > 1000
