#!/usr/bin/env python3
"""Stage 8 — EXPORT: Export to 3D Tiles format for CesiumJS.

Converts exported meshes to 3D Tiles tileset for the web planning platform.

Usage:
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/
    python scripts/export/export_3dtiles.py --input outputs/exports/ --output tiles_3d/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "outputs" / "exports"
DEFAULT_OUTPUT = REPO_ROOT / "tiles_3d"

# SRID 2952 origin for coordinate transform
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86
ORIGIN_LAT = 43.6555
ORIGIN_LON = -79.4000


def create_tileset_json(
    buildings: list[dict],
    output_dir: Path,
    *,
    geometric_error: float = 50.0,
) -> dict:
    """Create a 3D Tiles tileset.json manifest.

    In production: uses py3dtiles to convert meshes to B3DM/GLB tiles.
    Currently creates the tileset.json structure with metadata.
    """
    tiles = []
    for b in buildings:
        name = b.get("building_name", "unknown")
        safe = name.replace(" ", "_")
        height = b.get("total_height_m", 8.0)

        tiles.append({
            "boundingVolume": {
                "box": [0, 0, height / 2, 5, 0, 0, 0, 5, 0, 0, 0, height / 2]
            },
            "geometricError": 5.0,
            "content": {"uri": f"tiles/{safe}.b3dm"},
            "refine": "REPLACE",
        })

    tileset = {
        "asset": {"version": "1.0", "tilesetVersion": "1.0.0"},
        "geometricError": geometric_error,
        "root": {
            "boundingVolume": {
                "region": [
                    ORIGIN_LON * 0.0174533 - 0.005,
                    ORIGIN_LAT * 0.0174533 - 0.005,
                    ORIGIN_LON * 0.0174533 + 0.005,
                    ORIGIN_LAT * 0.0174533 + 0.005,
                    0, 50,
                ]
            },
            "geometricError": geometric_error,
            "refine": "ADD",
            "children": tiles,
        },
    }

    return tileset


def export_3dtiles(
    input_dir: Path,
    output_dir: Path,
    params_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Export buildings to 3D Tiles format."""
    # Load building params for metadata
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
    }

    if dry_run:
        result["status"] = "would_export"
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "tiles").mkdir(exist_ok=True)

    tileset = create_tileset_json(buildings, output_dir)
    (output_dir / "tileset.json").write_text(
        json.dumps(tileset, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result["status"] = "tileset_created"
    result["note"] = "B3DM tile content pending — requires py3dtiles"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export to 3D Tiles")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = export_3dtiles(args.input, args.output, args.params, dry_run=args.dry_run)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}3D Tiles: {result['building_count']} buildings → {result['output']}")


if __name__ == "__main__":
    main()
