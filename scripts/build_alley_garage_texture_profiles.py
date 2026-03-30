#!/usr/bin/env python3
"""Build alley/garage texture profiles from photo-reference categories."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "outputs" / "alley_garages" / "photo_reference_catalog.csv"
OUT_JSON = ROOT / "outputs" / "alley_garages" / "alley_garage_texture_profiles.json"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "alley_garage_texture_profiles.csv"

# Calibrated from observed Kensington alley/garage photos (March 2026) and tags.
BASE_PROFILES = {
    "asphalt_wet_lane": {
        "base_color": "#3F4347",
        "accent_color": "#70757C",
        "roughness": 0.78,
        "metallic": 0.05,
        "normal_intensity": 0.82,
        "grime_amount": 0.66,
        "wetness": 0.42,
        "decal_density": 0.30,
    },
    "concrete_garage": {
        "base_color": "#A8A7A1",
        "accent_color": "#2E2E2E",
        "roughness": 0.72,
        "metallic": 0.03,
        "normal_intensity": 0.55,
        "grime_amount": 0.34,
        "wetness": 0.10,
        "decal_density": 0.12,
    },
    "rollup_metal_graffiti": {
        "base_color": "#8D939B",
        "accent_color": "#2D3034",
        "roughness": 0.61,
        "metallic": 0.58,
        "normal_intensity": 0.40,
        "grime_amount": 0.52,
        "wetness": 0.16,
        "decal_density": 0.75,
    },
    "graffiti_wall_masonry": {
        "base_color": "#8E7866",
        "accent_color": "#B84444",
        "roughness": 0.64,
        "metallic": 0.02,
        "normal_intensity": 0.68,
        "grime_amount": 0.50,
        "wetness": 0.18,
        "decal_density": 0.90,
    },
    "chainlink_utility": {
        "base_color": "#7D8288",
        "accent_color": "#B8BEC6",
        "roughness": 0.47,
        "metallic": 0.64,
        "normal_intensity": 0.30,
        "grime_amount": 0.27,
        "wetness": 0.08,
        "decal_density": 0.06,
    },
    "green_edge_planter": {
        "base_color": "#50524B",
        "accent_color": "#6E8C52",
        "roughness": 0.80,
        "metallic": 0.02,
        "normal_intensity": 0.60,
        "grime_amount": 0.38,
        "wetness": 0.22,
        "decal_density": 0.12,
    },
}


def category_to_profile(category: str, loc: str) -> str:
    c = (category or "").lower()
    l = (loc or "").lower()
    if "structured_interior" in c or "parking garage interior" in l:
        return "concrete_garage"
    if "structured_entrance" in c or "parking garage" in l:
        return "concrete_garage"
    if "row_rollup" in c or ("garage" in l and "graffiti" in l):
        return "rollup_metal_graffiti"
    if "garage" in c or "garage" in l:
        return "rollup_metal_graffiti"
    if "graffiti_wall" in c:
        return "graffiti_wall_masonry"
    if "chain" in c or "fence" in l:
        return "chainlink_utility"
    if "green" in c or "plant" in l:
        return "green_edge_planter"
    return "asphalt_wet_lane"


def main() -> int:
    rows = list(csv.DictReader(IN_CSV.open("r", encoding="utf-8", newline="")))
    profile_counts = Counter()
    for r in rows:
        p = category_to_profile(r.get("category") or "", r.get("address_or_location") or "")
        profile_counts[p] += 1

    payload = {
        "source": "photo_reference_catalog",
        "total_references": len(rows),
        "profiles": [
            {
                "profile": k,
                "reference_count": profile_counts.get(k, 0),
                **BASE_PROFILES[k],
            }
            for k in BASE_PROFILES
        ],
        "notable_reference_photos": [
            "IMG_20260315_151745774_HDR.jpg",
            "IMG_20260315_151752760_HDR.jpg",
            "IMG_20260315_153027271_HDR.jpg",
            "IMG_20260315_163719882_HDR.jpg",
            "IMG_20260316_002116506_HDR.jpg",
        ],
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "profile",
                "reference_count",
                "base_color",
                "accent_color",
                "roughness",
                "metallic",
                "normal_intensity",
                "grime_amount",
                "wetness",
                "decal_density",
            ],
        )
        w.writeheader()
        for rec in payload["profiles"]:
            w.writerow(rec)

    print(f"[OK] Wrote {OUT_JSON}")
    print(f"[OK] Wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
