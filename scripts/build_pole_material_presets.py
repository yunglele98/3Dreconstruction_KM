#!/usr/bin/env python3
"""Build Unreal material/season presets for poles."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLES = ROOT / "outputs" / "poles"
IN_CSV = POLES / "pole_instances_unreal_refined_cm.csv"
OUT_JSON = POLES / "pole_material_presets.json"
OUT_CSV = POLES / "pole_material_presets.csv"


def finish_from_etat(etat: str) -> tuple[str, float]:
    e = (etat or "").lower()
    if "excellent" in e:
        return "paint_clean", 0.45
    if "bon" in e:
        return "paint_worn", 0.58
    if "moyen" in e:
        return "paint_weathered", 0.72
    return "paint_standard", 0.62


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    by_type = {}
    for r in rows:
        by_type.setdefault(r["pole_key"], []).append(r)

    presets = []
    for key, items in sorted(by_type.items()):
        etat = next((x.get("etat", "") for x in items if x.get("etat")), "")
        finish, rough = finish_from_etat(etat)
        presets.append(
            {
                "pole_key": key,
                "material_family": "galvanized_steel" if "utility" not in key else "wood_or_steel_mix",
                "finish": finish,
                "base_color": "#8E9398",
                "roughness": rough,
                "metallic": 0.85 if "steel" in finish or "paint" in finish else 0.5,
                "seasonal_adjustment": "none",
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
