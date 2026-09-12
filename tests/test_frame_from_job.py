from jwmcp import jwc_temp, profiles
from jwmcp.model import Drawing, primitives


def test_frame_from_job_keeps_fixed_texts(tmp_path, monkeypatch):
    monkeypatch.setenv("JWMCP_HOME", str(tmp_path))
    # A title block drawn in Jw_cad on an A3 sheet at 1/50, sent through JWMCP_send.bat (#hp + #zs):
    # coordinates are real mm relative to the paper's lower-left corner.
    s = 50
    lines = [(16, 11.5, 404, 11.5), (404, 11.5, 404, 30.5), (404, 30.5, 16, 30.5), (16, 30.5, 16, 11.5), (300, 11.5, 300, 30.5)]
    body = ["hq", "hzs 420 297", "hs " + " ".join(["50"] * 16), "hn 0 0 1 1", "#", "lg0", "ly0", "lc5", "lt1"]
    body += [f"{x1*s} {y1*s} {x2*s} {y2*s}" for x1, y1, x2, y2 in lines]
    body += ["cn0 2 2 0 1", f'ch {20*s} {27*s} {5*s} 0 "Title', "cn0 6 6 0 2", f'ch {320*s} {18*s} {60*s} 0 "Future Studio']
    j = jwc_temp.parse("\r\n".join(body) + "\r\n")
    assert j.to_drawing_coords()
    prof = profiles.frame_from_job(j, "fs_test")
    tpl = prof["frame_template"]
    assert tpl["paper"] == "A3" and tpl["count"] == 7
    texts = {e["text"]: e for e in tpl["entities"] if e["type"] == "text"}
    assert set(texts) == {"Title", "Future Studio"}
    assert abs(texts["Future Studio"]["height"] - 6.0) < 1e-9          # size drawn in Jw_cad is kept (paper mm)
    xs = [v for e in tpl["entities"] if e["type"] == "line" for v in (e["x1"], e["x2"])]
    assert abs(min(xs) - (16 - 210)) < 1e-6 and abs(max(xs) - (404 - 210)) < 1e-6   # paper mm, origin = paper centre

    # reuse on A1 with a title value; the fixed company text comes from the template, not from fields
    fe = profiles.frame_entity(prof, "A1", {"title": "計画名"})
    d = Drawing("t", scale=100)
    d.group_scales[15] = 1.0
    d.add([fe])
    prims = list(primitives(d.entities[0], 1.0))
    ptexts = [p["text"] for p in prims if p["type"] == "text"]
    assert "Future Studio" in ptexts and "計画名" in ptexts and ptexts.count("Future Studio") == 1
    ys = [v for p in prims if p["type"] == "line" for v in (p["y1"], p["y2"])]
    assert abs(min(ys) - (-594 / 2 + 11.5)) < 1e-6                     # keeps the distance from the bottom edge

    # labels-only mode drops the fixed text
    prof2 = profiles.frame_from_job(j, "fs_labels", frame_texts="labels")
    assert {e["text"] for e in prof2["frame_template"]["entities"] if e["type"] == "text"} == {"Title"}
