#!/usr/bin/env python3
"""Build Unreal material presets for bike racks."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "bikeracks"
IN_CSV = DIR / "bikerack_instances_unreal_refined_cm.csv"
OUT_JSON = DIR / "bikerack_material_presets.json"
OUT_CSV = DIR / "bikerack_material_presets.csv"


def finish(etat: str) -> tuple[str, float]:
    e = (etat or "").lower()
    if "excellent" in e:
        return "powdercoat_clean", 0.38
    if "bon" in e:
        return "powdercoat_used", 0.48
    if "moyen" in e:
        return "paint_weathered", 0.62
    return "paint_standard", 0.56


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    keys = sorted({r["rack_key"] for r in rows})
    presets = []
    for k in keys:
        sample = next((r for r in rows if r["rack_key"] == k), {})
        fn, rough = finish(sample.get("etat", ""))
        presets.append(
            {
                "rack_key": k,
                "material_family": "painted_steel",
                "finish": fn,
                "base_color": "#5E6368",
                "roughness": rough,
                "metallic": 0.88,
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
