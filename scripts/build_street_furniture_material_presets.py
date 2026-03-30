#!/usr/bin/env python3
"""Build material presets for street furniture assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "street_furniture"
IN_CSV = DIR / "street_furniture_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "street_furniture_material_presets.json"
OUT_CSV = DIR / "street_furniture_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "shelter" in k:
        return "steel_glass", "#7E858B", "#AFC5D6", 0.42
    if "terrace" in k:
        return "wood_metal_mix", "#8A6A4A", "#4E545A", 0.62
    if "mural" in k:
        return "painted_panel", "#D9D9D9", "#2B2B2B", 0.38
    if "sculpture" in k:
        return "cast_metal", "#6D7276", "#C7C7C7", 0.46
    return "urban_installation", "#8B8E90", "#D0D0D0", 0.5


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["furniture_key"] for r in rows})
    presets = []
    for k in keys:
        fam, base, accent, rough = preset(k)
        presets.append(
            {
                "furniture_key": k,
                "material_family": fam,
                "base_color": base,
                "accent_color": accent,
                "roughness": rough,
                "metallic": 0.6 if "metal" in fam else 0.25,
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
