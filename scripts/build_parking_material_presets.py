#!/usr/bin/env python3
"""Build material presets for parking assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "parking"
IN_CSV = DIR / "parking_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "parking_material_presets.json"
OUT_CSV = DIR / "parking_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "meter" in k:
        return "painted_metal_meter", "#5B6066", "#D6D9DD", 0.45
    if "accessible" in k:
        return "accessible_marking", "#2A78C8", "#FFFFFF", 0.52
    if "paid" in k:
        return "asphalt_paid_lot", "#3E3F42", "#F0D56B", 0.68
    if "private" in k:
        return "asphalt_private", "#444548", "#DADADA", 0.7
    if "lot" in k or "surface" in k:
        return "asphalt_public", "#3A3B3F", "#ECECEC", 0.66
    return "urban_parking_generic", "#50545A", "#D4D4D4", 0.6


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = sorted({r["parking_key"] for r in rows})
    presets = []
    for k in keys:
        family, base, accent, rough = preset(k)
        presets.append(
            {
                "parking_key": k,
                "material_family": family,
                "base_color": base,
                "accent_color": accent,
                "roughness": rough,
                "metallic": 0.58 if "metal" in family or "meter" in family else 0.2,
            }
        )

    OUT_JSON.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(presets[0].keys()) if presets else [])
        w.writeheader()
        w.writerows(presets)

    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
