#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Clip block-level meshes to per-building footprints.

Takes a block-level photogrammetric mesh (or point cloud) and clips it
using building footprints from GeoJSON or PostGIS to produce individual
per-building meshes.

Supports two clipping backends:
- GeoJSON footprints (from gis_scene.json or exported GeoJSON)
- PostGIS query (requires psycopg2)

Usage:
    python scripts/reconstruct/clip_block_mesh.py --block-mesh point_clouds/colmap_blocks/Augusta_Ave/fused.ply --footprints data/open_data/footprints.geojson
    python scripts/reconstruct/clip_block_mesh.py --block-mesh point_clouds/colmap_blocks/Augusta_Ave/fused.ply --footprints postgis --street "Augusta Ave"
    python scripts/reconstruct/clip_block_mesh.py --block-mesh point_clouds/colmap_blocks/Augusta_Ave/fused.ply --footprints postgis --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "meshes" / "per_building"
GIS_SCENE = REPO_ROOT / "gis_scene.json"

# Coordinate origin (SRID 2952)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def load_footprints_geojson(geojson_path: Path, *, street_filter: str | None = None) -> list[dict]:
    """Load building footprints from a GeoJSON file."""
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    features = data.get("features", [])

    footprints = []
    for feat in features:
        props = feat.get("properties", {})
        address = props.get("ADDRESS_FULL", props.get("address", ""))
        street = props.get("street", "")
        geom = feat.get("geometry", {})

        if street_filter and street_filter.lower() not in street.lower():
            continue

        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue

        coords = geom.get("coordinates", [])
        if geom["type"] == "Polygon":
            ring = coords[0] if coords else []
        else:
            ring = coords[0][0] if coords and coords[0] else []

        footprints.append({
            "address": address,
            "street": street,
            "polygon": ring,
            "properties": props,
        })

    return footprints


def load_footprints_gis_scene(*, street_filter: str | None = None) -> list[dict]:
    """Load footprints from gis_scene.json (local coordinates)."""
    if not GIS_SCENE.exists():
        return []

    scene = json.loads(GIS_SCENE.read_text(encoding="utf-8"))
    footprints_data = scene.get("footprints", [])
    footprints = []

    for fp in footprints_data:
        address = fp.get("address", "")
        street = fp.get("street", "")

        if street_filter and street_filter.lower() not in street.lower():
            continue

        coords = fp.get("coords", [])
        if not coords:
            continue

        footprints.append({
            "address": address,
            "street": street,
            "polygon": coords,
            "source": "gis_scene",
        })

    return footprints


def clip_point_cloud_to_polygon(
    ply_path: Path,
    polygon: list,
    output_path: Path,
) -> dict:
    """Clip a PLY point cloud using a 2D polygon (XY plane).

    Requires numpy. Falls back to status report if unavailable.
    """
    try:
        import numpy as np
    except ImportError:
        return {"status": "requires_numpy"}

    # Lightweight 2D point-in-polygon (ray casting)
    def point_in_polygon(px, py, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i][0], poly[i][1]
            xj, yj = poly[j][0], poly[j][1]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # Read PLY (simple ASCII parser)
    lines = ply_path.read_text(encoding="utf-8", errors="replace").splitlines()

    header_end = 0
    vertex_count = 0
    for i, line in enumerate(lines):
        if line.startswith("element vertex"):
            vertex_count = int(line.split()[-1])
        if line.strip() == "end_header":
            header_end = i + 1
            break

    if vertex_count == 0:
        return {"status": "empty_point_cloud", "vertices": 0}

    # Parse vertices and filter
    kept = []
    header = lines[:header_end]
    for line in lines[header_end:header_end + vertex_count]:
        parts = line.split()
        if len(parts) < 3:
            continue
        x, y = float(parts[0]), float(parts[1])
        if point_in_polygon(x, y, polygon):
            kept.append(line)

    if not kept:
        return {"status": "no_points_in_footprint", "vertices_checked": vertex_count}

    # Write clipped PLY
    output_path.parent.mkdir(parents=True, exist_ok=True)
    new_header = []
    for h in header:
        if h.startswith("element vertex"):
            new_header.append(f"element vertex {len(kept)}")
        else:
            new_header.append(h)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_header) + "\n")
        f.write("\n".join(kept) + "\n")

    return {
        "status": "clipped",
        "input_vertices": vertex_count,
        "output_vertices": len(kept),
    }


def clip_block(
    block_mesh_path: Path,
    footprints: list[dict],
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Clip a block mesh/point cloud by all footprints."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for fp in footprints:
        address = fp.get("address", "unknown")
        safe_name = address.replace(" ", "_").replace(",", "")
        ext = block_mesh_path.suffix
        output_path = output_dir / f"{safe_name}{ext}"

        result = {
            "address": address,
            "block_mesh": str(block_mesh_path),
            "output": str(output_path),
            "polygon_vertices": len(fp.get("polygon", [])),
        }

        if dry_run:
            result["status"] = "would_clip"
        elif ext.lower() == ".ply":
            clip_result = clip_point_cloud_to_polygon(
                block_mesh_path, fp["polygon"], output_path,
            )
            result.update(clip_result)
        else:
            result["status"] = "unsupported_format"
            result["note"] = f"Only PLY clipping supported; got {ext}"

        results.append(result)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Clip block mesh to building footprints")
    parser.add_argument("--block-mesh", required=True, type=Path)
    parser.add_argument(
        "--footprints", default="gis_scene",
        help="'gis_scene', 'postgis', or path to GeoJSON",
    )
    parser.add_argument("--street", type=str, default=None, help="Filter by street")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.block_mesh.exists():
        print(f"[ERROR] Block mesh not found: {args.block_mesh}")
        sys.exit(1)

    # Load footprints
    if args.footprints == "gis_scene":
        footprints = load_footprints_gis_scene(street_filter=args.street)
    elif args.footprints == "postgis":
        print("[WARN] PostGIS footprint loading not yet implemented, falling back to gis_scene")
        footprints = load_footprints_gis_scene(street_filter=args.street)
    else:
        geojson_path = Path(args.footprints)
        if not geojson_path.exists():
            print(f"[ERROR] GeoJSON not found: {geojson_path}")
            sys.exit(1)
        footprints = load_footprints_geojson(geojson_path, street_filter=args.street)

    print(f"Loaded {len(footprints)} footprints")

    results = clip_block(args.block_mesh, footprints, args.output, dry_run=args.dry_run)

    # Write manifest
    manifest_path = args.output / "clip_manifest.json"
    if not args.dry_run:
        manifest_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    clipped = sum(1 for r in results if r.get("status") == "clipped")
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Clipped {clipped}/{len(results)} buildings from {args.block_mesh.name}")


if __name__ == "__main__":
    main()
