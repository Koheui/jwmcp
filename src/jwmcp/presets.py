"""Layer-group / layer presets for new drawings (Jw_cad: 16 groups x 16 layers)."""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    # Generic Japanese architectural plan: one group, layers by discipline
    "arch_jp": {
        "description": "一般的な平面図。グループ0に用途別レイヤ",
        "group_names": {"0": "平面図"},
        "layer_names": {"0-0": "通り芯", "0-1": "壁", "0-2": "柱", "0-3": "建具", "0-4": "設備", "0-5": "家具",
                        "0-6": "室名", "0-7": "寸法", "0-8": "ハッチ", "0-9": "注記", "0-F": "補助線"},
        "defaults": {"wall": {"ly": 1, "lc": 2}, "column": {"ly": 2, "lc": 2}, "grid": {"ly": 0, "lc": 1},
                     "room": {"ly": 6, "lc": 2}, "equipment": {"ly": 4, "lc": 3}, "dimension": {"ly": 7, "lc": 1},
                     "opening": {"lg": 0, "ly": 3, "lc": 1}},
    },
    # Existing-building survey drawing (既存図) with separate groups, as used for renovation work:
    # 0 site, 1 text, 2 structure (red), 3 openings (cyan, frame 25mm), 4 interior walls (green, 90mm, core on ly1 cyan),
    # 5 planning (kept empty in the survey drawing)
    "arch_jp_renovation": {
        "description": "既存図（改修前提）。グループ分け: 0敷地 1記述 2躯体(赤) 3建具(水色) 4内部壁・造作(緑, 壁厚90) 5計画図",
        "group_names": {"0": "敷地情報", "1": "記述", "2": "躯体", "3": "建具", "4": "内部壁・造作", "5": "計画図"},
        "layer_names": {"2-0": "柱・躯体壁", "2-1": "躯体芯", "3-0": "建具", "4-0": "内部壁", "4-1": "壁芯", "4-2": "造作",
                        "1-0": "室名", "1-1": "注記", "0-0": "敷地"},
        "defaults": {"wall": {"lg": 4, "ly": 0, "lc": 3, "thickness": 90, "core": True, "core_ly": 1, "core_lc": 1,
                              "opening_lg": 3, "opening_ly": 0, "opening_lc": 1},
                     "structure_wall": {"lg": 2, "ly": 0, "lc": 8},
                     "column": {"lg": 2, "ly": 0, "lc": 8}, "grid": {"lg": 2, "ly": 1, "lc": 8},
                     "room": {"lg": 1, "ly": 0, "lc": 2}, "text": {"lg": 1, "ly": 1, "lc": 2},
                     "equipment": {"lg": 4, "ly": 2, "lc": 3}, "opening": {"lg": 3, "ly": 0, "lc": 1, "frame": 25}},
    },
    # MEP (給排水・空調換気) overlay on an architectural base
    "mep_jp": {
        "description": "設備図。グループ0建築下図 1給排水 2空調換気 3電気",
        "group_names": {"0": "建築", "1": "給排水衛生", "2": "空調換気", "3": "電気"},
        "layer_names": {"0-0": "壁", "0-1": "建具", "0-2": "室名", "1-0": "給水", "1-1": "給湯", "1-2": "排水", "1-3": "通気",
                        "1-4": "衛生器具", "1-5": "ガス", "2-0": "冷媒", "2-1": "ドレン", "2-2": "ダクト", "2-3": "機器",
                        "2-4": "換気", "3-0": "電灯", "3-1": "コンセント"},
        "defaults": {"pipe": {"lg": 1}, "equipment": {"lg": 1, "ly": 4}},
        "pipe_layers": {"給水": (1, 0), "給湯": (1, 1), "排水": (1, 2), "汚水": (1, 2), "雑排水": (1, 2), "通気": (1, 3),
                        "ガス": (1, 5), "冷媒": (2, 0), "ドレン": (2, 1), "ダクト": (2, 2), "給気": (2, 4), "排気": (2, 4), "換気": (2, 4)},
    },
}


def preset_names() -> dict[str, str]:
    return {k: v["description"] for k, v in PRESETS.items()}
