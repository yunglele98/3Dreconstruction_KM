#!/usr/bin/env python3
"""Build material presets for alley+garage assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "alley_garages"
IN_CSV = DIR / "alley_garage_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "alley_garage_material_presets.json"
OUT_CSV = DIR / "alley_garage_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "garage_structured" in k:
        return "concrete_parking_struct", "#B9B7B0", "#2F2F2F", 0.74
    if "garage_row" in k or "garage_single" in k or "garage_residential" in k:
        return "painted_rollup_metal", "#868C92", "#3A3C40", 0.62
    if "graffiti" in k:
        return "painted_alley_wall", "#8A7A6A", "#B94141", 0.58
    if "chainlink" in k:
        return "chainlink_metal", "#7C8085", "#B7BDC3", 0.48
    if "green" in k:
        return "mixed_asphalt_green", "#4A4B46", "#6F8B52", 0.8
    if "concrete" in k:
        return "alley_concrete", "#979793", "#C7C7C2", 0.72
    if "gravel" in k:
        return "alley_gravel", "#756C64", "#AFA79E", 0.86
    return "alley_asphalt", "#3F4044", "#D7D7D7", 0.78


def main() -> int:
    rows = list(csv.DictReader(IN_CSV.open("r", encoding="utf-8", newline="")))
    keys = sorted({r["alley_garage_key"] for r in rows})
    presets = []
    for k in keys:
        family, base, accent, rough = preset(k)
        presets.append({
            "alley_garage_key": k,
            "material_family": family,
            "base_color": base,
            "accent_color": accent,
            "roughness": rough,
            "metallic": 0.55 if "metal" in family or "chainlink" in family else 0.15,
        })

    OUT_JSON.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(presets[0].keys()) if presets else [])
        w.writeheader(); w.writerows(presets)
    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
