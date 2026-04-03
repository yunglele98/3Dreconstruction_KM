#!/usr/bin/env python3
"""Clip a block-level mesh to individual building footprints.

Takes a block-level mesh (from run_photogrammetry_block.py) and clips it
into per-building meshes using building footprints from PostGIS or GeoJSON.
Falls back to bounding box clipping when PostGIS is not available.

Usage:
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/Augusta_Ave.obj --footprints postgis
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/Augusta_Ave.obj --footprints-geojson data/open_data/building_footprints.geojson
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/Augusta_Ave.obj --footprints bbox --params params/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "meshes" / "per_building"

# Coordinate system origin (SRID 2952)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def load_footprints_postgis(street=None):
    """Load building footprints from PostGIS."""
    try:
        import psycopg2
    except ImportError:
        print("WARNING: psycopg2 not available. Use --footprints-geojson or --footprints bbox.")
        return None

    try:
        conn = psycopg2.connect(
            host="localhost", port=5432, database="kensington",
            user="postgres", password="test123"
        )
        cur = conn.cursor()

        query = """
            SELECT bf.address, ST_AsGeoJSON(bf.geom) as geojson
            FROM opendata.building_footprints bf
        """
        params = []
        if street:
            query += " WHERE bf.address ILIKE %s"
            params.append(f"%{street}%")

        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()

        footprints = {}
        for address, geojson_str in rows:
            if address and geojson_str:
                geom = json.loads(geojson_str)
                footprints[address] = geom
        return footprints

    except Exception as e:
        print(f"WARNING: PostGIS query failed: {e}")
        return None


def load_footprints_geojson(geojson_path):
    """Load building footprints from a GeoJSON file."""
    if not geojson_path.exists():
        print(f"ERROR: GeoJSON file not found: {geojson_path}")
        return None

    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    footprints = {}

    features = data.get("features", [])
    for feat in features:
        props = feat.get("properties", {})
        address = props.get("ADDRESS_FULL") or props.get("address") or props.get("FULL_ADDR", "")
        geom = feat.get("geometry")
        if address and geom:
            footprints[address] = geom
    return footprints


def load_footprints_bbox(params_dir, street=None):
    """Build bounding box footprints from param files as fallback."""
    footprints = {}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("skipped"):
            continue

        address = data.get("building_name", param_file.stem.replace("_", " "))
        site = data.get("site", {})

        if street and street.lower() not in (site.get("street") or "").lower():
            continue

        # Build a bbox from facade dimensions and position
        width = data.get("facade_width_m", 6.0)
        depth = data.get("facade_depth_m", 12.0)

        # Try to get position from site coordinates
        lon = site.get("lon")
        lat = site.get("lat")

        if lon is not None and lat is not None:
            # Simple bbox centered on position
            # These are approximate local coordinates
            footprints[address] = {
                "type": "bbox",
                "width": width,
                "depth": depth,
                "lon": lon,
                "lat": lat,
            }
        else:
            footprints[address] = {
                "type": "bbox",
                "width": width,
                "depth": depth,
            }

    return footprints


def read_obj_vertices(obj_path):
    """Read vertex positions from an OBJ file."""
    vertices = []
    with open(obj_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return vertices


def clip_mesh_to_bbox(obj_path, min_x, max_x, min_y, max_y, output_path):
    """Clip OBJ mesh faces to a 2D bounding box (XY plane).

    Keeps faces where at least one vertex falls within the bbox.
    """
    vertices = []
    faces = []
    other_lines = []

    with open(obj_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("v "):
                parts = stripped.split()
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif stripped.startswith("f "):
                faces.append(stripped)
            else:
                other_lines.append(stripped)

    # Determine which vertices are inside bbox
    inside = set()
    for i, (x, y, z) in enumerate(vertices):
        if min_x <= x <= max_x and min_y <= y <= max_y:
            inside.add(i + 1)  # OBJ indices are 1-based

    # Keep faces with at least one vertex inside
    kept_faces = []
    used_vertices = set()
    for face_line in faces:
        parts = face_line.split()[1:]
        face_indices = []
        for p in parts:
            idx = int(p.split("/")[0])
            face_indices.append(idx)
        if any(idx in inside for idx in face_indices):
            kept_faces.append(face_line)
            used_vertices.update(face_indices)

    if not kept_faces:
        return False

    # Remap vertex indices
    sorted_verts = sorted(used_vertices)
    remap = {old: new for new, old in enumerate(sorted_verts, 1)}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Clipped from block mesh\n")
        for idx in sorted_verts:
            v = vertices[idx - 1]
            f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for face_line in kept_faces:
            parts = face_line.split()
            new_parts = ["f"]
            for p in parts[1:]:
                components = p.split("/")
                components[0] = str(remap[int(components[0])])
                new_parts.append("/".join(components))
            f.write(" ".join(new_parts) + "\n")

    return True


def sanitize_name(address):
    """Convert address to filesystem-safe name."""
    return address.replace(" ", "_").replace(",", "").replace("/", "_")


def main():
    parser = argparse.ArgumentParser(
        description="Clip block-level mesh to individual building footprints."
    )
    parser.add_argument("--block-mesh", type=Path, required=True,
                        help="Path to block-level OBJ mesh")
    parser.add_argument("--footprints", type=str, default="bbox",
                        choices=["postgis", "bbox"],
                        help="Footprint source: postgis or bbox (default: bbox)")
    parser.add_argument("--footprints-geojson", type=Path, default=None,
                        help="GeoJSON file with building footprints (overrides --footprints)")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Params directory (for bbox fallback)")
    parser.add_argument("--street", type=str, default=None,
                        help="Filter to a specific street")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for per-building meshes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.block_mesh.exists():
        print(f"ERROR: Block mesh not found: {args.block_mesh}")
        sys.exit(1)

    # Load footprints
    footprints = None
    if args.footprints_geojson:
        print(f"Loading footprints from GeoJSON: {args.footprints_geojson}")
        footprints = load_footprints_geojson(args.footprints_geojson)
    elif args.footprints == "postgis":
        print("Loading footprints from PostGIS...")
        footprints = load_footprints_postgis(args.street)

    if not footprints:
        print("Falling back to bounding box footprints from params...")
        footprints = load_footprints_bbox(args.params, args.street)

    if not footprints:
        print("ERROR: No footprints found.")
        sys.exit(1)

    print(f"Block mesh: {args.block_mesh}")
    print(f"Footprints: {len(footprints)} buildings")

    # Read mesh to get bounding box for reference
    vertices = read_obj_vertices(args.block_mesh)
    if not vertices:
        print("ERROR: No vertices found in block mesh.")
        sys.exit(1)

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    print(f"Mesh bounds: X=[{min(xs):.1f}, {max(xs):.1f}], Y=[{min(ys):.1f}, {max(ys):.1f}]")

    if args.dry_run:
        for address in sorted(footprints):
            slug = sanitize_name(address)
            print(f"  Would clip: {address} -> {slug}.obj")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    clipped = 0
    failed = 0
    for address, footprint in sorted(footprints.items()):
        slug = sanitize_name(address)
        output_path = args.output / f"{slug}.obj"

        if output_path.exists():
            continue

        # Determine clipping bbox
        if isinstance(footprint, dict) and footprint.get("type") == "bbox":
            width = footprint.get("width", 6.0)
            depth = footprint.get("depth", 12.0)
            # Without exact position, use parametric approximation
            # This is a best-effort fallback
            lon = footprint.get("lon")
            lat = footprint.get("lat")
            if lon is not None and lat is not None:
                # Convert to local coords (approximate)
                cx = lon  # Already local if from site coords
                cy = lat
                min_x = cx - width / 2
                max_x = cx + width / 2
                min_y = cy - depth / 2
                max_y = cy + depth / 2
            else:
                print(f"  SKIP {address}: no position data for bbox clipping")
                failed += 1
                continue
        elif isinstance(footprint, dict) and footprint.get("type") in ("Polygon", "MultiPolygon"):
            # Extract bbox from GeoJSON polygon coordinates
            coords = footprint.get("coordinates", [])
            if footprint["type"] == "MultiPolygon":
                all_pts = [pt for poly in coords for ring in poly for pt in ring]
            else:
                all_pts = [pt for ring in coords for pt in ring]
            if not all_pts:
                failed += 1
                continue
            fxs = [p[0] for p in all_pts]
            fys = [p[1] for p in all_pts]
            # Convert from SRID 2952 to local
            min_x = min(fxs) - ORIGIN_X
            max_x = max(fxs) - ORIGIN_X
            min_y = min(fys) - ORIGIN_Y
            max_y = max(fys) - ORIGIN_Y
        else:
            print(f"  SKIP {address}: unsupported footprint type")
            failed += 1
            continue

        ok = clip_mesh_to_bbox(args.block_mesh, min_x, max_x, min_y, max_y, output_path)
        if ok:
            clipped += 1
            size_kb = output_path.stat().st_size / 1024
            print(f"  [OK] {slug}.obj ({size_kb:.0f} KB)")
        else:
            failed += 1
            print(f"  [EMPTY] {address}: no faces in footprint bbox")

    print(f"\nComplete: {clipped} clipped, {failed} failed/skipped")


if __name__ == "__main__":
    main()
