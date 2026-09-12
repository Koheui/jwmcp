import json

import pytest

httpx = pytest.importorskip("httpx")
from starlette.testclient import TestClient  # noqa: E402

from jwmcp.model import Drawing  # noqa: E402
from jwmcp.settings_ui import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    return TestClient(app)


def test_ui_roundtrip(client):
    assert "jwmcp 設定" in client.get("/").text
    st = client.get("/api/state").json()
    assert st["profiles"] == [] and "arch_jp" in st["presets"] and "A3" in st["papers"]

    prof = {"name": "acme", "company": "ACME", "paper": "A2", "scale": 100, "group_names": {"0": "平面", "F": "枠"},
            "group_scales": {"F": 1}, "layer_names": {"0-1": "壁"}, "defaults": {"wall": {"lg": 0, "ly": 1, "lc": 2}},
            "frame": {"lg": "F", "style": "strip", "fields": {"company": "ACME"}}}
    assert client.put("/api/profile/acme", json=prof).json() == {"saved": "acme"}
    got = client.get("/api/profile/acme").json()
    assert got["company"] == "ACME" and got["layer_names"]["0-1"] == "壁"
    r = client.post("/api/profile/acme/from_preset", json={"preset": "mep_jp"}).json()
    assert r["group_names"]["1"] == "給排水衛生" and r["group_names"]["0"] == "建築"   # preset overrides names it defines

    png = client.get("/api/preview/frame/acme?paper=A1&scale=100")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and len(png.content) > 1000

    d = Drawing("job1", scale=100, paper="A3")
    d.add([{"type": "line", "x1": 0, "y1": 0, "x2": 1000, "y2": 0}])
    d.save()
    assert client.get("/api/drawing/job1").json()["paper"] == "A3"
    r = client.put("/api/drawing/job1", json={"paper": "A2", "group_names": {"1": "設備"}, "group_scales": {"1": 50},
                                              "layer_names": {"1-0": "給水"}})
    assert r.json() == {"saved": "job1"}
    d2 = Drawing.load("job1")
    assert d2.paper == "A2" and d2.group_names[1] == "設備" and d2.group_scales[1] == 50 and d2.layer_names["1-0"] == "給水"

    r = client.post("/api/drawing/job1/apply_profile", json={"profile": "acme", "frame": True}).json()
    assert r == {"applied": "acme"}
    d3 = Drawing.load("job1")
    assert d3.profile == "acme" and any(e["type"] == "frame" for e in d3.entities) and d3.group_scales[15] == 1.0
    assert client.get("/api/preview/drawing/job1").status_code == 200

    r = client.post("/api/drawing/job1/save_as_profile", json={"profile": "from_job1"}).json()
    assert r["name"] == "from_job1" and r["paper"] == "A2"
    assert client.delete("/api/profile/from_job1").json() == {"deleted": True}
    assert client.get("/api/profile/nope").status_code == 404
