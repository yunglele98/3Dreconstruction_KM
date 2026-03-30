#!/usr/bin/env python3
"""Integrate all urban element instances into the GIS scene JSON.

Reads instance CSVs from outputs/ (trees, poles, signs, bikeracks, street_furniture,
parking, ground, waste, accessibility, vertical_hardscape, alleys, alley_garages,
intersections, fence_gates, transit_stops) and merges them into
outputs/gis_scene_enriched.json for use by gis_scene.py.

Also generates outputs/urban_elements_summary.json with counts and coverage.

Usage:
    python scripts/integrate_urban_elements.py
    python scripts/integrate_urban_elements.py --output outputs/gis_scene_enriched.json
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86

# Map category → (csv_filename, shape, default_height, default_radius, hex_colour)
CATEGORIES = {
    "trees": {
        "csv": "tree_instances.csv",
        "shape": "sphere",
        "height": 6.0,
        "radius": 1.5,
        "hex": "#2A5A2A",
        "x_col": "local_x_m",
        "y_col": "local_y_m",
    },
    "poles": {
        "csv": "pole_instances_unreal_cm.csv",
        "shape": "cylinder",
        "height": 5.0,
        "radius": 0.08,
        "hex": "#5A5A5A",
    },
    "signs": {
        "csv": "sign_instances_unreal_cm.csv",
        "shape": "sign",
        "height": 2.5,
        "radius": 0.3,
        "hex": "#CC4444",
    },
    "bikeracks": {
        "csv": "bikerack_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.8,
        "radius": 0.4,
        "hex": "#4488CC",
    },
    "street_furniture": {
        "csv": "street_furniture_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.9,
        "radius": 0.3,
        "hex": "#8A6A4A",
    },
    "parking": {
        "csv": "parking_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.05,
        "radius": 2.5,
        "hex": "#333333",
    },
    "ground": {
        "csv": "ground_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.02,
        "radius": 1.0,
        "hex": "#7A7A6A",
    },
    "waste": {
        "csv": "waste_instances_unreal_cm.csv",
        "shape": "cylinder",
        "height": 1.0,
        "radius": 0.3,
        "hex": "#4A6A4A",
    },
    "accessibility": {
        "csv": "accessibility_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.1,
        "radius": 0.8,
        "hex": "#DDDD44",
    },
    "vertical_hardscape": {
        "csv": "vertical_hardscape_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 1.2,
        "radius": 0.15,
        "hex": "#8A8A8A",
    },
    "alleys": {
        "csv": "alley_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.02,
        "radius": 2.0,
        "hex": "#6A6A6A",
    },
    "alley_garages": {
        "csv": "alley_garage_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 2.5,
        "radius": 1.5,
        "hex": "#9A8A7A",
    },
    "intersections": {
        "csv": "intersection_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 0.02,
        "radius": 5.0,
        "hex": "#4A4A4A",
    },
    "fence_gates": {
        "csv": "fence_gate_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 1.5,
        "radius": 0.5,
        "hex": "#6A5A4A",
    },
    "transit_stops": {
        "csv": "transit_instances_unreal_cm.csv",
        "shape": "cube",
        "height": 2.5,
        "radius": 1.5,
        "hex": "#44AAAA",
    },
}


def read_instances(category, config):
    """Read instance CSV and return list of placement dicts."""
    csv_path = OUTPUTS / category / config["csv"]
    if not csv_path.exists():
        return []

    instances = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Get coordinates — try multiple column name conventions
            x = y = None

            # Trees use local_x_m, local_y_m directly
            x_col = config.get("x_col", "")
            y_col = config.get("y_col", "")
            if x_col and x_col in row:
                try:
                    x = float(row[x_col])
                    y = float(row[y_col])
                except (ValueError, TypeError):
                    continue
            else:
                # Unreal CSVs use cm coordinates — convert to metres
                for xk in ["x_cm", "pos_x_cm", "center_x_cm"]:
                    if xk in row:
                        try:
                            x = float(row[xk]) / 100.0
                            break
                        except (ValueError, TypeError):
                            pass
                for yk in ["y_cm", "pos_y_cm", "center_y_cm"]:
                    if yk in row:
                        try:
                            y = float(row[yk]) / 100.0
                            break
                        except (ValueError, TypeError):
                            pass

                # Try raw metre columns
                if x is None:
                    for xk in ["x_m", "local_x", "x_2952_m"]:
                        if xk in row:
                            try:
                                raw = float(row[xk])
                                x = raw - ORIGIN_X if raw > 100000 else raw
                                break
                            except (ValueError, TypeError):
                                pass
                if y is None:
                    for yk in ["y_m", "local_y", "y_2952_m"]:
                        if yk in row:
                            try:
                                raw = float(row[yk])
                                y = raw - ORIGIN_Y if raw > 100000 else raw
                                break
                            except (ValueError, TypeError):
                                pass

            if x is None or y is None:
                continue

            instance = {
                "x": round(x, 2),
                "y": round(y, 2),
                "id": row.get("instance_id", row.get("id", "")),
                "type": row.get("type", row.get("asset_id", row.get("species_key", category))),
            }

            # Optional height override
            for hk in ["height_m", "height_cm"]:
                if hk in row and row[hk]:
                    try:
                        h = float(row[hk])
                        instance["h"] = h / 100.0 if "cm" in hk else h
                    except (ValueError, TypeError):
                        pass

            # Optional rotation
            for rk in ["rotation_deg", "yaw_deg"]:
                if rk in row and row[rk]:
                    try:
                        instance["rotation"] = float(row[rk])
                    except (ValueError, TypeError):
                        pass

            instances.append(instance)

    return instances


def main():
    parser = argparse.ArgumentParser(description="Integrate urban elements into GIS scene")
    parser.add_argument("--output", default=str(OUTPUTS / "gis_scene_enriched.json"))
    args = parser.parse_args()

    # Load existing GIS scene
    gis_path = OUTPUTS / "gis_scene.json"
    if gis_path.exists():
        with open(gis_path, encoding="utf-8") as f:
            gis = json.load(f)
    else:
        gis = {}

    print("=== Integrating Urban Elements into GIS Scene ===\n")

    # Add urban elements
    urban = {}
    summary = {}
    total = 0

    for category, config in sorted(CATEGORIES.items()):
        instances = read_instances(category, config)
        if instances:
            urban[category] = {
                "instances": instances,
                "config": {
                    "shape": config["shape"],
                    "height": config["height"],
                    "radius": config["radius"],
                    "hex": config["hex"],
                },
            }
        summary[category] = len(instances)
        total += len(instances)
        status = f"{len(instances):6d} instances" if instances else "     - no data"
        print(f"  {category:25s} {status}")

    gis["urban_elements"] = urban

    print(f"\n  {'TOTAL':25s} {total:6d} instances")

    # Write enriched GIS scene
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(gis, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nWrote {output_path}")

    # Write summary
    summary_path = OUTPUTS / "urban_elements_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_instances": total,
            "categories": summary,
        }, f, indent=2)
        f.write("\n")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
