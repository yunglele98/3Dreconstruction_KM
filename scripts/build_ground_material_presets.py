#!/usr/bin/env python3
"""Build asphalt/concrete material presets for Unreal ground assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "ground"
IN_CSV = DIR / "ground_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "ground_material_presets.json"
OUT_CSV = DIR / "ground_material_presets.csv"


def family(key: str) -> tuple[str, str, float]:
    k = (key or "").lower()
    if "asphalt" in k or "manhole" in k or "drain" in k:
        return "asphalt", "#4E5053", 0.82
    if "concrete" in k or "curb" in k:
        return "concrete", "#A7A9AC", 0.74
    if "parking" in k or "intersection" in k:
        return "mixed_hardscape", "#6E6F72", 0.79
    return "hardscape_generic", "#7A7C7F", 0.78


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["ground_key"] for r in rows})
    presets = []
    for k in keys:
        fam, color, rough = family(k)
        presets.append(
            {
                "ground_key": k,
                "material_family": fam,
                "base_color": color,
                "roughness": rough,
                "normal_intensity": 0.65 if "asphalt" in fam else 0.45,
                "ao_strength": 0.7,
                "wetness_support": True,
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
