from pathlib import Path

from jwmcp.jwf import parse_jwf, write_jwf


def test_write_jwf_roundtrip(tmp_path):
    base = tmp_path / "base.jwf"
    base.write_bytes("S_COMM_0 =    1C   35   A3    1    1   900   0    0    0\r\nLAYSCALE = 50 50 50 50 15 20 5 20 50 20 3 50 50 50 50 50\r\n"
                     "LAYNAM_0 = ,,,,,,,,,,,,,,,,\r\nLCOLLOR_1 =   0  192  192    1\r\nZOOM = 0 0 0 0 10 0.5 1.5 900 0\r\n".encode("cp932"))
    prof = {"name": "t", "sources": {"jwf": str(base)},
            "group_names": {"0": "平面図", "F": "図面枠"}, "group_scales": {"0": 100, "F": 1},
            "layer_names": {"0-0": "通り芯", "0-1": "壁", "F-0": "枠"},
            "pen_colors": {"1": [0, 0, 255], "2": [0, 0, 0]},
            "print_colors": {"2": {"rgb": [0, 0, 0], "width_index": 3, "width_mm": 0.35}},
            "text_types": {str(n): {"width": n, "height": n, "spacing": 0.5, "pen": 2} for n in range(1, 11)}}
    r = write_jwf(prof, str(tmp_path / "out.jwf"))
    assert "LAYNAM_0" in r["keys_written"] and "LAYSCALE" in r["keys_written"]
    text = Path(r["jwf"]).read_bytes().decode("cp932")
    assert "ZOOM = 0 0 0 0 10 0.5 1.5 900 0" in text                       # untouched lines copied
    assert "LAYNAM_0 = 平面図,通り芯,壁,,,,,,,,,,,,,," in text
    assert "LAYNAM_F = 図面枠,枠,,,,,,,,,,,,,,," in text
    assert "LAYSCALE = 100 50 50 50 15 20 5 20 50 20 3 50 50 50 50 1" in text   # profile scales override, others kept
    assert "LCOLLOR_1 =   0    0  255    1" in text and "PCOLLOR_2 =   0    0    0    3    0.35" in text
    assert text.count("LAYSCALE") == 1 and "\r\n" in text
    back = parse_jwf(r["jwf"])
    assert back["group_names"]["0"] == "平面図" and back["layer_names"]["0-1"] == "壁" and back["group_scales"]["F"] == 1
    assert back["text_types"][3]["height"] == 3.0 and back["pen_colors"][1] == [0, 0, 255]
