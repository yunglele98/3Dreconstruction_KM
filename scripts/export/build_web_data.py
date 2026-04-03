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
        slim.append(_get_building_props(p))
    return slim


def _make_footprint_polygon(lon, lat, width_m, depth_m):
    """Create a simple rectangular footprint polygon from center + dimensions.

    Approximates metre offsets as degree deltas at Toronto latitude (~43.65N).
    1 degree lat ≈ 111,320 m; 1 degree lon ≈ 111,320 * cos(43.65°) ≈ 80,500 m.
    """
    import math
    lat_per_m = 1.0 / 111320.0
    lon_per_m = 1.0 / (111320.0 * math.cos(math.radians(lat)))

    hw = (width_m / 2) * lon_per_m   # half-width in degrees lon
    hd = (depth_m / 2) * lat_per_m   # half-depth in degrees lat

    return [
        [lon - hw, lat - hd],
        [lon + hw, lat - hd],
        [lon + hw, lat + hd],
        [lon - hw, lat + hd],
        [lon - hw, lat - hd],  # close ring
    ]


def _get_building_props(p):
    """Extract common building properties for GeoJSON and app_data."""
    site = p.get("site", {}) if isinstance(p.get("site"), dict) else {}
    hcd = p.get("hcd_data", {}) if isinstance(p.get("hcd_data"), dict) else {}
    facade_detail = p.get("facade_detail", {}) if isinstance(p.get("facade_detail"), dict) else {}
    colour_palette = p.get("colour_palette", {}) if isinstance(p.get("colour_palette"), dict) else {}

    return {
        "address": p.get("building_name", ""),
        "street": site.get("street", ""),
        "lat": site.get("lat"),
        "lon": site.get("lon"),
        "floors": p.get("floors"),
        "total_height_m": p.get("total_height_m"),
        "height": p.get("total_height_m"),  # alias for map layer
        "facade_width_m": p.get("facade_width_m"),
        "facade_depth_m": p.get("facade_depth_m"),
        "facade_material": p.get("facade_material"),
        "facade_hex": facade_detail.get("brick_colour_hex") or colour_palette.get("facade"),
        "roof_type": p.get("roof_type"),
        "condition": p.get("condition"),
        "contributing": hcd.get("contributing"),
        "era": hcd.get("construction_date", ""),
        "construction_date": hcd.get("construction_date"),
        "has_storefront": p.get("has_storefront", False),
        "typology": hcd.get("typology"),
        "has_porch": p.get("porch_present", False),
        "party_wall_left": p.get("party_wall_left", False),
        "party_wall_right": p.get("party_wall_right", False),
    }


def build_geojson(buildings):
    """Create a GeoJSON FeatureCollection with polygon footprints for 3D extrusion."""
    features = []
    for p in buildings:
        props = _get_building_props(p)
        lon = props.get("lon")
        lat = props.get("lat")
        if not lon or not lat:
            continue

        width = props.get("facade_width_m") or 6.0
        depth = props.get("facade_depth_m") or 10.0

        footprint = _make_footprint_polygon(lon, lat, width, depth)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [footprint],
            },
            "properties": props,
        })

    return {"type": "FeatureCollection", "features": features}


def build_app_data(slim):
    """Build app_data.json with buildings array, stats, and per-street summaries."""
    from collections import Counter, defaultdict

    stats = {
        "total_buildings": len(slim),
        "with_coords": sum(1 for b in slim if b.get("lat") and b.get("lon")),
        "with_storefront": sum(1 for b in slim if b.get("has_storefront")),
        "contributing": sum(1 for b in slim if b.get("contributing") == "Yes"),
        "condition_good": sum(1 for b in slim if (b.get("condition") or "").lower() == "good"),
        "condition_fair": sum(1 for b in slim if (b.get("condition") or "").lower() == "fair"),
        "condition_poor": sum(1 for b in slim if (b.get("condition") or "").lower() == "poor"),
        "materials": dict(Counter(b.get("facade_material") or "unknown" for b in slim).most_common()),
        "roof_types": dict(Counter(b.get("roof_type") or "unknown" for b in slim).most_common()),
        "eras": dict(Counter(b.get("construction_date") or "unknown" for b in slim).most_common()),
    }

    streets = defaultdict(lambda: {"count": 0, "contributing": 0, "storefronts": 0, "avg_height": 0, "heights": []})
    for b in slim:
        st = b.get("street") or "Unknown"
        streets[st]["count"] += 1
        if b.get("contributing") == "Yes":
            streets[st]["contributing"] += 1
        if b.get("has_storefront"):
            streets[st]["storefronts"] += 1
        h = b.get("total_height_m")
        if h:
            streets[st]["heights"].append(h)

    street_summary = {}
    for st, info in sorted(streets.items()):
        heights = info.pop("heights")
        info["avg_height"] = round(sum(heights) / len(heights), 1) if heights else 0
        street_summary[st] = info

    return {
        "buildings": slim,
        "stats": stats,
        "streets": street_summary,
    }


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

    # Write app_data.json (richer format for the web app)
    app_data = build_app_data(slim)
    app_data_path = args.output / "app_data.json"
    app_data_path.write_text(json.dumps(app_data, indent=2) + "\n", encoding="utf-8")

    # Write buildings.geojson (polygon footprints for 3D extrusion)
    geojson = build_geojson(buildings)
    geojson_path = args.output / "buildings.geojson"
    geojson_path.write_text(json.dumps(geojson, indent=2) + "\n", encoding="utf-8")

    # Copy scenarios
    scenario_count = copy_scenarios(args.scenarios, args.output)

    print(f"Built web data: {len(slim)} buildings, {len(geojson['features'])} footprints, {scenario_count} scenarios -> {args.output}")


if __name__ == "__main__":
    main()
