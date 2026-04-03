#!/usr/bin/env python3
"""Build slim JSON data files for the web planning platform.

Reads building params and scenario files to produce lightweight data
for the CesiumJS/Potree web viewer: params-slim.json, buildings.geojson,
and scenario JSON copies.

Usage:
    python scripts/export/build_web_data.py --params params/ --scenarios scenarios/ --output web/public/data/
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "data"


def load_params(params_dir):
    """Load all non-skipped building param files."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("skipped"):
            continue
        buildings.append(p)
    return buildings


def build_slim_params(buildings):
    """Extract lightweight properties for each building."""
    slim = []
    for p in buildings:
        site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
        hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}

        slim.append({
            "address": p.get("building_name", ""),
            "street": site.get("street", ""),
            "lat": site.get("lat"),
            "lon": site.get("lon"),
            "floors": p.get("floors"),
            "total_height_m": p.get("total_height_m"),
            "facade_material": p.get("facade_material"),
            "roof_type": p.get("roof_type"),
            "condition": p.get("condition"),
            "contributing": hcd.get("contributing"),
            "construction_date": hcd.get("construction_date"),
            "has_storefront": p.get("has_storefront", False),
            "typology": hcd.get("typology"),
        })
    return slim


def build_geojson(buildings):
    """Create a GeoJSON FeatureCollection with point features per building."""
    features = []
    for p in buildings:
        site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat:
            continue

        hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "address": p.get("building_name", ""),
                "street": site.get("street", ""),
                "floors": p.get("floors"),
                "total_height_m": p.get("total_height_m"),
                "facade_material": p.get("facade_material"),
                "roof_type": p.get("roof_type"),
                "condition": p.get("condition"),
                "contributing": hcd.get("contributing"),
                "construction_date": hcd.get("construction_date"),
                "has_storefront": p.get("has_storefront", False),
                "typology": hcd.get("typology"),
            },
        })

    return {"type": "FeatureCollection", "features": features}


def copy_scenarios(scenarios_dir, output_dir):
    """Copy scenario JSON files to the output directory."""
    scenarios_out = output_dir / "scenarios"
    copied = 0

    if not scenarios_dir.exists():
        return copied

    for scenario_dir in sorted(scenarios_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
        interventions = scenario_dir / "interventions.json"
        if not interventions.exists():
            continue

        dest_dir = scenarios_out / scenario_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(interventions, dest_dir / "interventions.json")
        copied += 1

    # Also copy any top-level JSON files in scenarios/
    for f in sorted(scenarios_dir.glob("*.json")):
        scenarios_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, scenarios_out / f.name)
        copied += 1

    return copied


def main():
    parser = argparse.ArgumentParser(description="Build web data files for the planning platform.")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Directory containing building param JSON files")
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_DIR,
                        help="Directory containing scenario definitions")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for web data")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # Load buildings
    buildings = load_params(args.params)
    if not buildings:
        print(f"No building params found in {args.params}")
        return

    # Write params-slim.json
    slim = build_slim_params(buildings)
    slim_path = args.output / "params-slim.json"
    slim_path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")

    # Write buildings.geojson
    geojson = build_geojson(buildings)
    geojson_path = args.output / "buildings.geojson"
    geojson_path.write_text(json.dumps(geojson, indent=2) + "\n", encoding="utf-8")

    # Copy scenarios
    scenario_count = copy_scenarios(args.scenarios, args.output)

    print(f"Built web data: {len(slim)} buildings, {scenario_count} scenarios -> {args.output}")


if __name__ == "__main__":
    main()
