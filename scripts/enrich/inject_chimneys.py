#!/usr/bin/env python3
"""Inject missing chimneys into pre-1930 buildings.

Pre-1930 Toronto buildings almost universally had chimneys for coal/wood
heating. This script adds chimney entries to roof_features for buildings
that are missing them, with era-appropriate placement and sizing.

Usage:
    python scripts/enrich/inject_chimneys.py                # dry run
    python scripts/enrich/inject_chimneys.py --apply        # write changes
"""

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = ROOT / "params"

# Chimney placement varies by era and typology
ERA_CHIMNEY_PROFILES = {
    "Pre-1889": {
        "count": (1, 2),
        "positions": ["left_chimney", "right_chimney"],
        "width_m": (0.5, 0.7),
        "depth_m": (0.5, 0.7),
        "height_above_ridge_m": (0.6, 1.0),
        "material": "brick",
        "cap_style": "corbelled",
    },
    "1889-1903": {
        "count": (1, 2),
        "positions": ["left_chimney", "right_chimney"],
        "width_m": (0.45, 0.65),
        "depth_m": (0.45, 0.65),
        "height_above_ridge_m": (0.5, 0.9),
        "material": "brick",
        "cap_style": "simple",
    },
    "1904-1913": {
        "count": (1, 1),
        "positions": ["right_chimney"],
        "width_m": (0.4, 0.55),
        "depth_m": (0.4, 0.55),
        "height_above_ridge_m": (0.4, 0.8),
        "material": "brick",
        "cap_style": "simple",
    },
    "1914-1930": {
        "count": (1, 1),
        "positions": ["right_chimney"],
        "width_m": (0.35, 0.50),
        "depth_m": (0.35, 0.50),
        "height_above_ridge_m": (0.3, 0.6),
        "material": "brick",
        "cap_style": "plain",
    },
}


def needs_chimney(params):
    """Check if a building should have a chimney but doesn't."""
    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        return False, ""

    era = hcd.get("construction_date", "")
    if not era or era not in ERA_CHIMNEY_PROFILES:
        return False, ""

    # Skip flat-roof commercial buildings (chimneys less visible)
    roof = str(params.get("roof_type", "")).lower()
    if "flat" in roof:
        floors = params.get("floors", 2)
        if isinstance(floors, (int, float)) and floors >= 3:
            return False, ""

    # Check if chimney already present
    rf = params.get("roof_features", [])
    if isinstance(rf, list) and "chimney" in rf:
        return False, ""

    # Check decorative_elements for chimney
    dec = params.get("decorative_elements", {})
    if isinstance(dec, dict):
        for key in ("chimney", "chimneys", "left_chimney", "right_chimney"):
            if dec.get(key):
                return False, ""

    return True, era


def inject_chimney(params, era, seed=None):
    """Add chimney data to a building's params."""
    profile = ERA_CHIMNEY_PROFILES[era]
    rng = random.Random(seed)

    count_lo, count_hi = profile["count"]
    count = rng.randint(count_lo, count_hi)

    # Add to roof_features
    rf = params.get("roof_features", [])
    if not isinstance(rf, list):
        rf = []
    if "chimney" not in rf:
        rf.append("chimney")
    params["roof_features"] = rf

    # Add chimney detail
    chimney_detail = params.get("chimney_detail", {})
    if not isinstance(chimney_detail, dict):
        chimney_detail = {}

    w_lo, w_hi = profile["width_m"]
    d_lo, d_hi = profile["depth_m"]
    h_lo, h_hi = profile["height_above_ridge_m"]

    positions = profile["positions"][:count]
    for pos in positions:
        chimney_detail[pos] = {
            "width_m": round(rng.uniform(w_lo, w_hi), 2),
            "depth_m": round(rng.uniform(d_lo, d_hi), 2),
            "height_above_ridge_m": round(rng.uniform(h_lo, h_hi), 2),
            "material": profile["material"],
            "cap_style": profile["cap_style"],
        }

    params["chimney_detail"] = chimney_detail
    params["chimneys"] = count

    return count


def main():
    parser = argparse.ArgumentParser(description="Inject missing chimneys")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    injected = 0
    total_chimneys = 0
    by_era = {}

    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        needed, era = needs_chimney(data)
        if not needed:
            continue

        # Use address hash as seed for reproducible randomness
        seed = hash(data.get("building_name", f.stem))
        count = inject_chimney(data, era, seed=seed)

        injected += 1
        total_chimneys += count
        by_era[era] = by_era.get(era, 0) + 1

        if args.apply:
            meta = data.setdefault("_meta", {})
            meta["chimney_injected"] = True
            meta["chimney_injection_era"] = era
            f.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8"
            )

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"=== Chimney Injection ({mode}) ===")
    print(f"Buildings needing chimneys: {injected}")
    print(f"Total chimneys added: {total_chimneys}")
    print(f"By era: {json.dumps(by_era, indent=2)}")


if __name__ == "__main__":
    main()
