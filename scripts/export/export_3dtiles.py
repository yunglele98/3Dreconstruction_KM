#!/usr/bin/env python3
"""Export building meshes to 3D Tiles format for CesiumJS.

Converts exported meshes + params to OGC 3D Tiles for the web
planning platform. Includes LOD hierarchy and per-tile metadata.

Usage:
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/ --params params/
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import struct
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Coordinate origin (SRID 2952 -> approximate WGS84)
ORIGIN_LON = -79.4008
ORIGIN_LAT = 43.6545
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def load_building_metadata(params_dir: Path) -> dict[str, dict]:
    """Load building metadata from params for tile properties."""
    metadata = {}
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue
        stem = f.stem
        metadata[stem] = {
            "name": data.get("building_name", stem.replace("_", " ")),
            "floors": data.get("floors", 2),
            "height": data.get("total_height_m", 6.0),
            "material": data.get("facade_material", "brick"),
            "hcd_contributing": data.get("hcd_data", {}).get("contributing", "No"),
            "construction_date": data.get("hcd_data", {}).get("construction_date", ""),
            "typology": data.get("hcd_data", {}).get("typology", ""),
            "condition": data.get("condition", "fair"),
            "has_storefront": data.get("has_storefront", False),
            "lon": data.get("site", {}).get("lon", 0),
            "lat": data.get("site", {}).get("lat", 0),
        }
    return metadata


def compute_bounding_region(buildings: dict[str, dict]) -> list[float]:
    """Compute bounding region [west, south, east, north, minHeight, maxHeight] in radians."""
    if not buildings:
        return [
            math.radians(ORIGIN_LON - 0.005),
            math.radians(ORIGIN_LAT - 0.005),
            math.radians(ORIGIN_LON + 0.005),
            math.radians(ORIGIN_LAT + 0.005),
            0, 30,
        ]

    lons = [b.get("lon", ORIGIN_LON) for b in buildings.values() if b.get("lon")]
    lats = [b.get("lat", ORIGIN_LAT) for b in buildings.values() if b.get("lat")]

    if not lons or all(abs(l) < 1 for l in lons):
        # Coordinates are local, use origin
        return [
            math.radians(ORIGIN_LON - 0.005),
            math.radians(ORIGIN_LAT - 0.005),
            math.radians(ORIGIN_LON + 0.005),
            math.radians(ORIGIN_LAT + 0.005),
            0,
            max((b.get("height", 6) for b in buildings.values()), default=30),
        ]

    return [
        math.radians(min(lons) - 0.001),
        math.radians(min(lats) - 0.001),
        math.radians(max(lons) + 0.001),
        math.radians(max(lats) + 0.001),
        0,
        max((b.get("height", 6) for b in buildings.values()), default=30),
    ]


def create_tileset_json(
    buildings: dict[str, dict],
    output_dir: Path,
    geometric_error: float = 70.0,
) -> dict:
    """Create 3D Tiles tileset.json with building references."""
    region = compute_bounding_region(buildings)

    children = []
    for stem, meta in buildings.items():
        # Check if a GLB or B3DM file exists
        glb_path = output_dir / "tiles" / f"{stem}.glb"
        b3dm_path = output_dir / "tiles" / f"{stem}.b3dm"

        content_uri = None
        if b3dm_path.exists():
            content_uri = f"tiles/{stem}.b3dm"
        elif glb_path.exists():
            content_uri = f"tiles/{stem}.glb"

        child = {
            "boundingVolume": {
                "region": region,  # Simplified: same region for all
            },
            "geometricError": 10.0,
            "properties": {
                "name": meta["name"],
                "floors": meta["floors"],
                "height": meta["height"],
                "material": meta["material"],
                "hcd_contributing": meta["hcd_contributing"],
                "construction_date": meta["construction_date"],
            },
        }

        if content_uri:
            child["content"] = {"uri": content_uri}

        children.append(child)

    tileset = {
        "asset": {
            "version": "1.1",
            "generator": "kensington-3d-pipeline",
        },
        "geometricError": geometric_error,
        "root": {
            "boundingVolume": {"region": region},
            "geometricError": geometric_error,
            "refine": "ADD",
            "children": children,
        },
        "properties": {
            "name": {"minimum": 0, "maximum": len(buildings)},
        },
    }

    return tileset


def export_3dtiles(
    input_dir: Path,
    output_dir: Path,
    params_dir: Path,
) -> dict:
    """Export to 3D Tiles format.

    Args:
        input_dir: Directory with exported meshes (GLB/FBX).
        output_dir: Output directory for 3D Tiles.
        params_dir: Building params directory for metadata.

    Returns:
        Stats dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir = output_dir / "tiles"
    tiles_dir.mkdir(exist_ok=True)

    metadata = load_building_metadata(params_dir)
    stats = {"buildings": len(metadata), "tiles_with_geometry": 0}

    # Copy GLB files to tiles directory
    for glb_file in input_dir.rglob("*.glb"):
        stem = glb_file.stem
        dest = tiles_dir / glb_file.name
        if not dest.exists():
            import shutil
            shutil.copy2(glb_file, dest)
            stats["tiles_with_geometry"] += 1

    # Generate tileset.json
    tileset = create_tileset_json(metadata, output_dir)
    tileset_path = output_dir / "tileset.json"
    tileset_path.write_text(
        json.dumps(tileset, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    stats["tileset_path"] = str(tileset_path)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Export to 3D Tiles")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "outputs" / "exports")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "tiles_3d")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = export_3dtiles(args.input, args.output, args.params)
    print(f"3D Tiles export: {stats['buildings']} buildings, "
          f"{stats['tiles_with_geometry']} with geometry")
    print(f"  Tileset: {stats['tileset_path']}")


if __name__ == "__main__":
    main()
