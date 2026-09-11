import math

from jwmcp import jwc_temp
from jwmcp.model import Drawing, normalize_entity

SAMPLE = """hq
file=c:\\ore\\hoge.jww
hk 0
hs 1 100 50 50 60 1 1 1 1 50 50 1 50 50 50 1
hcw 2 2.5 3 4 5 6 7 8 9 10
hch 2 2.5 3 4 5 6 7 8 9 10
hcd 0 0 0.5 0.5 0.5 0.5 1 1 1 1
hcc 1 1 2 2 3 3 4 4 5 5
hn -426.36 -351.96 338.02 283.23
hp1 100 200
lg1
ly4
lc3
lt1
cn3
cn"$ＭＳ ゴシック
#
lc5
ci 75.33 115.99 100 180 270 1 180
lc1
ci -60.93 55.37 100
-5 0 5 0
pt 1 2
cn0 4 4 0.5 2
ch -11 0 22 0 "あいうえお
pl
0 0 10 10
10 10 20 -10
#
z3
100 200 300 400
#
lg0 11
lgn一階平面
ly0 11
lyn通り芯
ly1 11
lyn壁
"""


def test_parse_sample():
    j = jwc_temp.parse(SAMPLE)
    assert j.hq and j.file == "c:\\ore\\hoge.jww"
    assert j.hs[1] == 100 and j.hs[0] == 1
    assert j.hn == [-426.36, -351.96, 338.02, 283.23]
    assert j.points["hp1"] == {"x": 100.0, "y": 200.0}
    assert j.write == {"lg": 1, "ly": 4, "lc": 3, "lt": 1, "cn": 3}
    types = [e["type"] for e in j.entities]
    assert types == ["arc", "circle", "line", "point", "text", "line", "line", "line"]
    arc = j.entities[0]
    assert arc["lc"] == 5 and arc["lg"] == 1 and arc["ly"] == 4 and arc["start"] == 180 and arc["end"] == 270
    text = j.entities[4]
    assert text["text"] == "あいうえお" and text["width"] == 4 and text["height"] == 4 and text["spacing"] == 0.5 and text["lc"] == 2
    assert text["font"] == "ＭＳ ゴシック"
    assert j.entities[5]["curve"] == "pl1" and j.entities[6]["curve"] == "pl1"
    assert j.entities[7].get("z") == [3] and "curve" not in j.entities[7]
    assert j.group_state[0] == {"state": 11, "name": "一階平面"}
    assert j.layer_state["0-1"] == {"state": 11, "name": "壁"}
    assert j.unparsed == []


def test_parse_bz_converts_paper_to_real():
    j = jwc_temp.parse("hs 100 50\nbz\n#\nlg1\n0 0 10 0\n")
    e = j.entities[0]
    assert e["x2"] == 500.0 and e["lg"] == 1


def test_serialize_roundtrip():
    ents = [
        {"type": "line", "x1": 0, "y1": 0, "x2": 1000, "y2": 0, "lg": 1, "ly": 2, "lc": 2, "lt": 5},
        {"type": "circle", "cx": 50, "cy": 50, "r": 25},
        {"type": "arc", "cx": 0, "cy": 0, "r": 100, "start": 0, "end": 90},
        {"type": "text", "x": 10, "y": 20, "text": "浴室", "height": 3, "lg": 1, "ly": 2, "lc": 2},
        {"type": "rect", "x": 0, "y": 0, "w": 910, "h": 910},
        {"type": "point", "x": 5, "y": 5},
    ]
    text = jwc_temp.serialize([normalize_entity(e) for e in ents], scale_for=lambda e: 100.0,
                              group_names={1: "平面"}, layer_names={"1-2": "壁"}, delete_selected=True, notice="ok")
    assert "hq" not in text.split("\r\n")
    assert text.startswith("hd\r\nh#ok\r\nlg1\r\nlgn平面\r\nlg1\r\nly2\r\nlyn壁\r\n")
    assert "\r\n0 0 1000 0\r\n" in text
    assert "ci 50 50 25" in text and "ci 0 0 100 0 90 1 0" in text
    assert "cn0 3 3 0 2" in text and 'ch 10 20 600 0 "浴室' in text   # 2 full-width chars * 3mm * 100
    assert text.count("\r\n") == len(text.split("\r\n")) - 1
    j = jwc_temp.parse("hs 100 100\n#\n" + text)
    types = sorted(e["type"] for e in j.entities)
    assert types == sorted(["line", "circle", "arc", "text", "line", "line", "line", "line", "point"])
    t = [e for e in j.entities if e["type"] == "text"][0]
    assert t["text"] == "浴室" and t["lg"] == 1 and t["ly"] == 2 and abs(t["angle"]) < 1e-9
    ln = [e for e in j.entities if e["type"] == "line" and e["x2"] == 1000][0]
    assert ln["lt"] == 5 and ln["lc"] == 2


def test_serialize_error_only():
    assert jwc_temp.serialize([], error="bad") == "hebad\r\n"


def test_dimension_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    d = Drawing("t", scale=100)
    d.add([{"type": "dimension", "x1": 0, "y1": 0, "x2": 3640, "y2": 0, "offset": 800}])
    prims = d.primitives()
    kinds = [p["type"] for p in prims]
    assert kinds.count("line") == 3 and kinds.count("point") == 2 and kinds.count("text") == 1
    t = [p for p in prims if p["type"] == "text"][0]
    assert t["text"] == "3,640" and t["kind"] == "cs"
    # centred: 5 half-width chars = 2.5 units * 3mm * 100 = 750 -> starts at 1820-375
    assert math.isclose(t["x"], 1820 - 375) and math.isclose(t["y"], 800 + 100)
    txt = jwc_temp.serialize(d.entities, scale_for=d.scale_of)
    assert 'cs 1445 900 750 0 "3,640' in txt


def test_encode_cp932():
    assert jwc_temp.encode("lyn壁\r\n") == "lyn壁\r\n".encode("cp932")
    assert jwc_temp.decode("壁".encode("cp932")) == "壁"
