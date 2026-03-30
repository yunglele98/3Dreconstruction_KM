#!/usr/bin/env python3
"""Build material presets for intersection assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "intersections"
IN_CSV = DIR / "intersection_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "intersection_material_presets.json"
OUT_CSV = DIR / "intersection_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "signalized" in k:
        return "traffic_signal_metal", "#5A5F66", "#DADDE0", 0.45
    if "dangerous" in k:
        return "warning_signage", "#3F4449", "#F2C94C", 0.55
    if "cross" in k:
        return "crossing_marking", "#3A3B3E", "#F5F5F5", 0.62
    return "intersection_standard", "#3D4044", "#D8D8D8", 0.6


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = sorted({r["intersection_key"] for r in rows})
    presets = []
    for k in keys:
        family, base, accent, rough = preset(k)
        presets.append(
            {
                "intersection_key": k,
                "material_family": family,
                "base_color": base,
                "accent_color": accent,
                "roughness": rough,
                "metallic": 0.55 if "metal" in family else 0.18,
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
