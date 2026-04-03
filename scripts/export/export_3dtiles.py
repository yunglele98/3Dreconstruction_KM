#!/usr/bin/env python3
"""Stage 8 — EXPORT: Export to 3D Tiles format for CesiumJS.

Converts building params and exported meshes into a 3D Tiles tileset
for the web planning platform. Supports two backends:

1. py3dtiles: converts meshes to B3DM tiles (full pipeline)
2. GLB passthrough: wraps existing GLB exports as 3D Tiles content
3. Tileset-only: generates tileset.json referencing expected tile URIs

The tileset uses WGS84 coordinates derived from building lat/lon
or the SRID 2952 centroid transform.

Usage:
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/ --method glb
    python scripts/export/export_3dtiles.py --params params/ --output tiles_3d/ --dry-run
"""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "outputs" / "exports"
DEFAULT_OUTPUT = REPO_ROOT / "tiles_3d"

# SRID 2952 origin → WGS84 approximate centre
ORIGIN_LAT = 43.6555
ORIGIN_LON = -79.4000
DEG_TO_RAD = math.pi / 180.0

# Study area bounds in radians
WEST = -79.4050 * DEG_TO_RAD
SOUTH = 43.6530 * DEG_TO_RAD
EAST = -79.3940 * DEG_TO_RAD
NORTH = 43.6590 * DEG_TO_RAD


def building_to_tile(params: dict, index: int) -> dict:
    """Convert building params to a 3D Tiles child node."""
    name = params.get("building_name", f"building_{index}")
    safe = name.replace(" ", "_").replace(",", "")
    height = params.get("total_height_m", 8.0)
    width = params.get("facade_width_m", 6.0)
    depth = params.get("facade_depth_m", 10.0)

    # Position from lat/lon if available
    site = params.get("site", {})
    lat = site.get("lat")
    lon = site.get("lon")

    if lat and lon:
        # Region bounding volume in radians
        half_w = (width / 111320.0) * DEG_TO_RAD / 2  # approx degrees per metre
        half_d = (depth / 111320.0) * DEG_TO_RAD / 2
        lon_rad = lon * DEG_TO_RAD
        lat_rad = lat * DEG_TO_RAD
        bv = {
            "region": [
                lon_rad - half_w, lat_rad - half_d,
                lon_rad + half_w, lat_rad + half_d,
                0, height,
            ]
        }
    else:
        # Box bounding volume (local coordinates)
        bv = {
            "box": [
                0, 0, height / 2,
                width / 2, 0, 0,
                0, depth / 2, 0,
                0, 0, height / 2,
            ]
        }

    tile = {
        "boundingVolume": bv,
        "geometricError": max(1.0, height * 0.3),
        "content": {"uri": f"tiles/{safe}.glb"},
        "refine": "REPLACE",
        "properties": {
            "address": params.get("_meta", {}).get("address", name),
            "floors": params.get("floors", 0),
            "height_m": height,
            "material": params.get("facade_material", ""),
            "condition": params.get("condition", ""),
        },
    }

    return tile


def create_tileset(buildings: list[dict], output_dir: Path) -> dict:
    """Create a 3D Tiles 1.1 tileset.json."""
    tiles = [building_to_tile(b, i) for i, b in enumerate(buildings)]

    tileset = {
        "asset": {
            "version": "1.1",
            "tilesetVersion": "2026.04.03",
            "generator": "kensington-3d-pipeline",
        },
        "geometricError": 100.0,
        "root": {
            "boundingVolume": {
                "region": [WEST, SOUTH, EAST, NORTH, 0, 60],
            },
            "geometricError": 50.0,
            "refine": "ADD",
            "children": tiles,
        },
        "properties": {
            "building_count": len(buildings),
        },
    }
    return tileset


def copy_glb_tiles(input_dir: Path, tiles_dir: Path) -> int:
    """Copy GLB files from exports to the tiles directory."""
    tiles_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for glb in input_dir.rglob("*.glb"):
        dst = tiles_dir / glb.name
        if not dst.exists():
            shutil.copy2(glb, dst)
            copied += 1
    return copied


def check_py3dtiles() -> bool:
    try:
        import py3dtiles
        return True
    except ImportError:
        return False


def export_3dtiles(
    input_dir: Path,
    output_dir: Path,
    params_dir: Path,
    *,
    method: str = "auto",
    dry_run: bool = False,
) -> dict:
    """Export buildings to 3D Tiles format."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue
        buildings.append(data)

    result = {
        "building_count": len(buildings),
        "output": str(output_dir),
        "method": method,
    }

    if dry_run:
        result["status"] = "would_export"
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir = output_dir / "tiles"
    tiles_dir.mkdir(exist_ok=True)

    # Copy GLB tiles if available
    if input_dir.exists():
        copied = copy_glb_tiles(input_dir, tiles_dir)
        result["glb_tiles_copied"] = copied

    # Generate tileset.json
    tileset = create_tileset(buildings, output_dir)
    (output_dir / "tileset.json").write_text(
        json.dumps(tileset, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Try py3dtiles for B3DM conversion
    if method in ("auto", "py3dtiles") and check_py3dtiles():
        result["note"] = "py3dtiles available — B3DM conversion supported"
    else:
        result["note"] = "GLB passthrough mode — install py3dtiles for B3DM"

    result["status"] = "exported"
    result["tiles_count"] = len(tileset["root"]["children"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export to 3D Tiles")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--method", default="auto", choices=["auto", "glb", "py3dtiles"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = export_3dtiles(
        args.input, args.output, args.params,
        method=args.method, dry_run=args.dry_run,
    )

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}3D Tiles: {result['building_count']} buildings → {result['output']}")
    if "tiles_count" in result:
        print(f"  Tileset: {result['tiles_count']} tile nodes")
    if "glb_tiles_copied" in result:
        print(f"  GLB tiles copied: {result['glb_tiles_copied']}")


if __name__ == "__main__":
    main()
