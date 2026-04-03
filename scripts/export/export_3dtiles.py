#!/usr/bin/env python3
"""Stage 8d: Convert building params to 3D Tiles tileset for CesiumJS.

Generates a tileset.json with per-building bounding volumes. Actual b3dm
tile content requires py3dtiles (pip install py3dtiles). This script creates
the tileset structure and metadata; b3dm conversion runs separately.

Usage:
    python scripts/export/export_3dtiles.py --output tiles_3d/
    python scripts/export/export_3dtiles.py --output tiles_3d/ --limit 10
"""
import argparse, json, logging, math
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent

ORIGIN_LON = -79.4000
ORIGIN_LAT = 43.6560
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def wgs84_to_ecef(lon, lat, alt=0):
    """Convert WGS84 to ECEF coordinates for 3D Tiles."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f * f
    lon_r = math.radians(lon)
    lat_r = math.radians(lat)
    N = a / math.sqrt(1 - e2 * math.sin(lat_r) ** 2)
    x = (N + alt) * math.cos(lat_r) * math.cos(lon_r)
    y = (N + alt) * math.cos(lat_r) * math.sin(lon_r)
    z = (N * (1 - e2) + alt) * math.sin(lat_r)
    return x, y, z


def build_tileset(buildings: list[dict]) -> dict:
    """Build 3D Tiles tileset.json."""
    # Compute bounding region
    lons, lats, heights = [], [], []
    for b in buildings:
        site = b.get("site", {})
        lon = site.get("lon")
        lat = site.get("lat")
        if lon and lat and abs(lon) < 180:
            lons.append(lon)
            lats.append(lat)
            heights.append(b.get("total_height_m", 8.0))

    if not lons:
        lons = [ORIGIN_LON]
        lats = [ORIGIN_LAT]
        heights = [10]

    region = [
        math.radians(min(lons)), math.radians(min(lats)),
        math.radians(max(lons)), math.radians(max(lats)),
        0, max(heights),
    ]

    children = []
    for b in buildings:
        site = b.get("site", {})
        addr = b.get("building_name", b.get("_meta", {}).get("address", ""))
        lon = site.get("lon")
        lat = site.get("lat")
        height = b.get("total_height_m", 8.0)
        width = b.get("facade_width_m", 6.0)

        if not lon or not lat or abs(lon) > 180:
            continue

        child = {
            "boundingVolume": {
                "region": [
                    math.radians(lon - 0.00005), math.radians(lat - 0.00005),
                    math.radians(lon + 0.00005), math.radians(lat + 0.00005),
                    0, height,
                ]
            },
            "geometricError": 5,
            "content": {
                "uri": f"tiles/{addr.replace(' ', '_')}.b3dm"
            },
            "properties": {
                "address": addr,
                "height": height,
                "floors": b.get("floors", 2),
                "era": b.get("hcd_data", {}).get("construction_date", ""),
                "material": b.get("facade_material", ""),
            }
        }
        children.append(child)

    tileset = {
        "asset": {
            "version": "1.0",
            "generator": "kensington-pipeline",
            "generatedAt": datetime.now().isoformat(),
        },
        "geometricError": 50,
        "root": {
            "boundingVolume": {"region": region},
            "geometricError": 20,
            "refine": "ADD",
            "children": children,
        },
        "properties": {
            "building_count": len(children),
        }
    }
    return tileset


def main():
    parser = argparse.ArgumentParser(description="Export 3D Tiles tileset")
    parser.add_argument("--output", type=Path, default=REPO / "tiles_3d")
    parser.add_argument("--params", type=Path, default=REPO / "params")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    buildings = []
    for f in sorted(args.params.glob("*.json")):
        if f.name.startswith("_"): continue
        d = json.load(open(f, encoding="utf-8"))
        if d.get("skipped"): continue
        buildings.append(d)
        if args.limit and len(buildings) >= args.limit: break

    logger.info("Building tileset for %d buildings", len(buildings))
    tileset = build_tileset(buildings)

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "tiles").mkdir(exist_ok=True)
    tileset_path = args.output / "tileset.json"
    tileset_path.write_text(json.dumps(tileset, indent=2), encoding="utf-8")

    logger.info("Saved: %s (%d buildings in tileset)", tileset_path,
                tileset["properties"]["building_count"])


if __name__ == "__main__":
    main()
