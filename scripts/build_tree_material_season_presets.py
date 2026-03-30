#!/usr/bin/env python3
"""Create material + seasonal preset mapping for Unreal trees."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "outputs" / "trees"
IN_CSV = TREES / "tree_instances_unreal_refined_cm.csv"
OUT_JSON = TREES / "tree_material_season_presets.json"
OUT_CSV = TREES / "tree_material_season_presets.csv"

CONIFER_TOKENS = ("spruce", "pine", "cedar", "fir", "thuja", "picea", "pinus", "abies", "juniper")


def is_conifer(species_key: str) -> bool:
    k = (species_key or "").lower()
    return any(t in k for t in CONIFER_TOKENS)


def main() -> int:
    with IN_CSV.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    species = sorted({r["species_key"] for r in rows})

    presets = []
    for sk in species:
        conif = is_conifer(sk) or sk == "unknown_evergreen"
        presets.append(
            {
                "species_key": sk,
                "material_family": "conifer" if conif else "deciduous",
                "bark_tint": "#6B4F3A" if conif else "#7A5A40",
                "leaf_tint_summer": "#3A6B2E" if conif else "#4F7F35",
                "leaf_tint_march": "#365C2C" if conif else "#7A6A4A",
                "leaf_off_in_march": False if conif else True,
                "roughness": 0.78 if conif else 0.72,
                "subsurface": 0.05 if conif else 0.08,
            }
        )

    payload = {
        "season": "March (Toronto)",
        "rules": {
            "deciduous_default": "leaf_off",
            "conifer_default": "leaf_on",
        },
        "presets": presets,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(presets[0].keys()) if presets else [])
        writer.writeheader()
        writer.writerows(presets)

    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
