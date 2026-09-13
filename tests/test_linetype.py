from pathlib import Path

from jwmcp import jwc_temp, linetype
from jwmcp.jwf import parse_jwf, write_jwf
from jwmcp.model import normalize_entity


def _chars(d):
    return [(s["drawn"], s["chars"]) for s in d["segments"]]


def test_pattern_roundtrip_and_runs():
    # Sample.jwf: ●＿＿●●＿＿● = 99999999, most significant bit first
    assert linetype.hex_to_pattern("99999999")[:8] == "-  --  -"
    assert linetype.pattern_to_hex("-  --  -" * 4) == "99999999"
    p = linetype.hex_to_pattern
    assert linetype.runs(p("aaaaaaaa"), 4) == [(True, 1), (False, 1)]              # reduced to the real period
    assert linetype.runs(p("99999999"), 4) == [(True, 2), (False, 2)]
    assert linetype.runs(p("f99ff99f"), 16) == [(True, 10), (False, 2), (True, 2), (False, 2)]   # longest dash first
    assert linetype.runs(p("f24ff24f"), 16) == [(True, 8), (False, 2), (True, 1), (False, 2), (True, 1), (False, 2)]
    assert linetype.runs("-" * 32, 8) == [(True, 8)]


def test_describe_printed_mm():
    d = linetype.describe("05", linetype.DEFAULTS["05"], dpi=600)
    assert _chars(d) == [(True, 10), (False, 2), (True, 2), (False, 2)]
    assert abs(d["segments"][0]["print_mm"] - 10 * 10 * 25.4 / 600) < 1e-3
    d300 = linetype.describe("02", linetype.DEFAULTS["02"], dpi=300)
    assert _chars(d300) == [(True, 1), (False, 1)] and abs(d300["segments"][0]["print_mm"] - 0.847) < 1e-3
    half = linetype.describe("02", linetype.DEFAULTS["02"], dpi=600, print_scale=0.5)
    assert abs(half["segments"][0]["print_mm"] - 0.212) < 1e-3
    aux = linetype.describe("09", linetype.DEFAULTS["09"])
    assert aux["printed"] is False and "print_mm" not in aux["segments"][0]
    rnd = linetype.describe("R3", linetype.DEFAULTS["R3"], dpi=600)
    assert rnd["kind"] == "random" and abs(rnd["step_mm"] - 15 * 25.4 / 600) < 1e-9


def test_validate():
    ok = {"hex": "ff00ff00", "unit": 16, "pitch": 1, "print_pitch": 10}
    assert linetype.validate("05", ok) == []
    assert linetype.validate("05", {**ok, "unit": 12})
    assert linetype.validate("05", {**ok, "print_pitch": 400})
    assert linetype.validate("05", {**ok, "hex": "xyz"})


def test_jwf_linetypes_and_print_widths(tmp_path):
    src = tmp_path / "t.jwf"
    src.write_bytes(("S_COMM_2 =     0 -100    0    0    0    0    1    0    0\r\n"
                     "LTYPE_02 = 99999999    4    1   10\r\nLTYPE_09 = 22222222    4    1\r\n"
                     "LTYPE_R1 = ccb2b32a    1    3    1    5\r\nLTYPE_L4 = fffe7fff   32    4   40\r\n"
                     "PCOLLOR_2 =    0    0    0   15    0.30\r\n").encode("cp932"))
    p = parse_jwf(str(src))
    assert p["line_width_unit"] == {"raw": -100, "mode": "1/100mm"}
    assert p["print_colors"][2] == {"rgb": [0, 0, 0], "width": 15, "width_mm": 0.15, "point_radius": 0.3}
    lts = p["linetypes"]
    assert lts["02"] == {"hex": "99999999", "unit": 4, "pitch": 1, "print_pitch": 10}
    assert lts["09"] == {"hex": "22222222", "unit": 4, "pitch": 1}
    assert lts["R1"] == {"hex": "ccb2b32a", "amp": 1, "pitch": 3, "print_amp": 1, "print_pitch": 5}
    assert lts["L4"]["print_pitch"] == 40

    prof = {"name": "t", "sources": {"jwf": str(src)},
            "linetypes": {**lts, "05": {"hex": "ff00ff00", "unit": 16, "pitch": 2, "print_pitch": 20}},
            "print_colors": {"2": {"rgb": [0, 0, 0], "width": 20, "point_radius": 0.5}}}
    out = write_jwf(prof, str(tmp_path / "o.jwf"))
    back = parse_jwf(out["jwf"])
    assert back["linetypes"]["05"] == {"hex": "ff00ff00", "unit": 16, "pitch": 2, "print_pitch": 20}
    assert back["linetypes"]["02"] == lts["02"] and back["linetypes"]["R1"] == lts["R1"]
    assert back["print_colors"][2]["width"] == 20 and back["print_colors"][2]["point_radius"] == 0.5
    text = Path(out["jwf"]).read_bytes().decode("cp932")
    assert text.count("LTYPE_02") == 1 and text.count("LTYPE_05") == 1


def test_test_sheet_is_paper_mm():
    ents = linetype.test_sheet_entities(dict(linetype.DEFAULTS), dpi=600, length_mm=100)
    lines = [e for e in ents if e["type"] == "line" and e["lt"] != 1]
    assert sorted(e["lt"] for e in lines) == [2, 3, 4, 5, 6, 7, 8]
    assert all(abs(e["x2"] - e["x1"] - 100) < 1e-9 for e in lines)
    label = next(e["text"] for e in ents if e["type"] == "text" and e["text"].startswith("線種5"))
    assert "線 4.23 / 空き 0.85 / 線 0.85 / 空き 0.85" in label
    txt = jwc_temp.serialize([normalize_entity(e) for e in ents], scale_for=lambda e: 1.0, paper_coords=True)
    assert txt.split("\r\n")[0] == "bz" and "\r\nlt5\r\n" in txt
