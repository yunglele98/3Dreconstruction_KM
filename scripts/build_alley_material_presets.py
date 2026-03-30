#!/usr/bin/env python3
"""Build material presets for alley assets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "alleys"
IN_CSV = DIR / "alley_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "alley_material_presets.json"
OUT_CSV = DIR / "alley_material_presets.csv"


def preset(key: str):
    k = (key or "").lower()
    if "gravel" in k:
        return "alley_gravel", "#76706A", "#B9B2AB", 0.84
    if "concrete" in k:
        return "alley_concrete", "#9A9A96", "#CFCFCB", 0.72
    if "green" in k:
        return "alley_green", "#5A5A54", "#6F8C4A", 0.78
    if "degraded" in k:
        return "alley_degraded", "#4A4B4F", "#8D7965", 0.88
    if "service" in k:
        return "alley_service", "#57585C", "#9CA0A6", 0.74
    if "pedestrian" in k:
        return "alley_pedestrian", "#696B70", "#C7C9CC", 0.7
    return "alley_asphalt", "#3F4044", "#D7D7D7", 0.76


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    keys = sorted({r["alley_key"] for r in rows})
    presets = []
    for k in keys:
        family, base, accent, rough = preset(k)
        presets.append(
            {
                "alley_key": k,
                "material_family": family,
                "base_color": base,
                "accent_color": accent,
                "roughness": rough,
                "metallic": 0.12,
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
