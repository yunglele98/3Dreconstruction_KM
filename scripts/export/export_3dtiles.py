#!/usr/bin/env python3
"""Generate a 3D Tiles tileset.json manifest for the web platform.

Creates a tileset.json following the 3D Tiles 1.0 spec with per-building
tile entries. References .glb files if they exist in the input directory;
otherwise creates placeholder entries.

Usage:
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/ --params params/
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DIR = REPO_ROOT / "outputs" / "exports"
OUTPUT_DIR = REPO_ROOT / "tiles_3d"
PARAMS_DIR = REPO_ROOT / "params"

# Kensington Market approximate centre (WGS84)
CENTER_LON = -79.4025
CENTER_LAT = 43.6545
CENTER_HEIGHT = 0.0

# Approximate bounding region for the full study area (radians)
# Dundas W (north) / Bathurst (east) / College (south) / Spadina (west)
REGION_WEST = math.radians(-79.4080)
REGION_SOUTH = math.radians(43.6510)
REGION_EAST = math.radians(-79.3960)
REGION_NORTH = math.radians(43.6590)


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
        buildings.append((f.stem, p))
    return buildings


def _building_region(lon, lat, w, d, h):
    """Compute a bounding region [west, south, east, north, minH, maxH] in radians + metres."""
    m_per_deg_lat = 111320.0
    m_per_deg_lon = m_per_deg_lat * 0.7  # cos(~43.65)

    dlon = (w / 2.0) / m_per_deg_lon
    dlat = (d / 2.0) / m_per_deg_lat

    return [
        math.radians(lon - dlon),
        math.radians(lat - dlat),
        math.radians(lon + dlon),
        math.radians(lat + dlat),
        0.0,
        float(h),
    ]


def _geometric_error_for_height(h):
    """Assign geometric error based on building height for LOD switching."""
    if h > 15:
        return 5.0
    if h > 10:
        return 8.0
    return 12.0


def build_tileset(buildings, input_dir, output_dir):
    """Generate tileset.json with per-building tile entries."""
    glb_files = {}
    if input_dir.exists():
        for glb in input_dir.rglob("*.glb"):
            glb_files[glb.stem] = glb

    children = []
    for stem, params in buildings:
        site = params.get("site", {}) if isinstance(params.get("site"), dict) else {}
        lon = site.get("lon")
        lat = site.get("lat")
        if not lon or not lat:
            continue

        w = params.get("facade_width_m") or 6.0
        d = params.get("facade_depth_m") or 15.0
        h = params.get("total_height_m") or 7.0
        address = params.get("building_name", stem.replace("_", " "))

        region = _building_region(lon, lat, w, d, h)
        geometric_error = _geometric_error_for_height(h)

        # Check for matching .glb
        glb = glb_files.get(stem)
        content_uri = f"../outputs/exports/{stem}.glb" if glb else None

        tile = {
            "boundingVolume": {
                "region": region,
            },
            "geometricError": geometric_error,
            "refine": "REPLACE",
            "extras": {
                "address": address,
                "floors": params.get("floors", 2),
                "height_m": h,
            },
        }

        if content_uri:
            tile["content"] = {"uri": content_uri}
        else:
            tile["content"] = {"uri": f"placeholder/{stem}.glb"}

        children.append(tile)

    # Root bounding volume covers the full study area
    max_h = max((p.get("total_height_m") or 7.0 for _, p in buildings), default=20.0)

    tileset = {
        "asset": {
            "version": "1.0",
            "tilesetVersion": "1.0.0",
            "extras": {
                "project": "Kensington Market 3D Reconstruction",
                "srid": "EPSG:4326",
                "generated_by": "export_3dtiles.py",
            },
        },
        "geometricError": 50.0,
        "root": {
            "boundingVolume": {
                "region": [
                    REGION_WEST,
                    REGION_SOUTH,
                    REGION_EAST,
                    REGION_NORTH,
                    0.0,
                    float(max_h),
                ],
            },
            "geometricError": 25.0,
            "refine": "ADD",
            "children": children,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "tileset.json"
    out_path.write_text(json.dumps(tileset, indent=2) + "\n", encoding="utf-8")

    glb_count = sum(1 for c in children if not c["content"]["uri"].startswith("placeholder/"))
    placeholder_count = len(children) - glb_count

    return len(children), glb_count, placeholder_count, out_path


def main():
    parser = argparse.ArgumentParser(description="Generate 3D Tiles tileset.json manifest.")
    parser.add_argument("--input", type=Path, default=INPUT_DIR,
                        help="Directory containing .glb exports")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for tileset.json")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Directory containing building param JSON files")
    args = parser.parse_args()

    buildings = load_params(args.params)
    if not buildings:
        print(f"No building params found in {args.params}")
        return

    total, glb_count, placeholder_count, out_path = build_tileset(
        buildings, args.input, args.output
    )

    print(f"Generated tileset.json: {total} tiles ({glb_count} with .glb, {placeholder_count} placeholders) -> {out_path}")


if __name__ == "__main__":
    main()
