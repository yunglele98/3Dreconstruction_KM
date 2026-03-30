#!/usr/bin/env python3
"""Build material presets for vertical hardscape assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "vertical_hardscape"
IN_CSV = DIR / "vertical_hardscape_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "vertical_hardscape_material_presets.json"
OUT_CSV = DIR / "vertical_hardscape_material_presets.csv"


def props(key: str):
    k = (key or "").lower()
    if "curb" in k or "stair" in k:
        return "cast_concrete", "#A8AAA9", 0.72
    if "foundation" in k or "retaining" in k:
        return "aged_concrete", "#8D8F90", 0.84
    if "loading" in k:
        return "hard_edge_concrete", "#969899", 0.78
    return "hardscape_generic", "#8E9091", 0.8


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["hardscape_key"] for r in rows})
    presets = []
    for k in keys:
        fam, color, rough = props(k)
        presets.append(
            {
                "hardscape_key": k,
                "material_family": fam,
                "base_color": color,
                "roughness": rough,
                "normal_intensity": 0.42,
                "edge_wear": 0.65,
            }
        )
    OUT_JSON.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(presets[0].keys()) if presets else [])
        w.writeheader(); w.writerows(presets)
    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
