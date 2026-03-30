#!/usr/bin/env python3
"""
Export all active buildings with lon/lat to a GeoJSON file.

Output: outputs/deliverables/kensington_buildings.geojson
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_FILE = ROOT / "outputs" / "deliverables" / "kensington_buildings.geojson"


def main():
    features = []

    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        site = params.get("site", {})
        lon = site.get("lon")
        lat = site.get("lat")

        if lon is None or lat is None:
            continue

        try:
            lon = float(lon)
            lat = float(lat)
        except (TypeError, ValueError):
            continue

        hcd = params.get("hcd_data", {})
        address = params.get("building_name", param_file.stem.replace("_", " "))

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "address": address,
                "floors": params.get("floors"),
                "height_m": params.get("total_height_m"),
                "facade_material": params.get("facade_material"),
                "construction_date": hcd.get("construction_date", ""),
                "contributing": hcd.get("contributing", ""),
                "condition": params.get("condition", ""),
                "roof_type": params.get("roof_type", ""),
                "typology": hcd.get("typology", ""),
            },
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Exported {len(features)} buildings to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
