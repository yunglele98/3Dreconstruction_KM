#!/usr/bin/env python3
"""Clip a block-level COLMAP mesh into per-building meshes using footprints.

After COLMAP produces a dense mesh for a street block, this script clips it
into individual building meshes using PostGIS footprint polygons or param
facade_width/depth values.

Usage:
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/augusta_ave.obj --footprints postgis
    python scripts/reconstruct/clip_block_mesh.py --block-mesh meshes/blocks/augusta_ave.obj --footprints params
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "meshes" / "per_building"

# Blender coordinate origin (SRID 2952)
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def parse_args():
    parser = argparse.ArgumentParser(description="Clip block mesh into per-building meshes.")
    parser.add_argument("--block-mesh", type=Path, required=True, help="Path to block .obj/.ply mesh")
    parser.add_argument("--footprints", choices=["postgis", "params"], default="postgis")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--buffer-m", type=float, default=0.5, help="Buffer around footprint (metres)")
    parser.add_argument("--street", type=str, default=None, help="Filter to one street")
    return parser.parse_args()


def load_mesh_vertices(mesh_path):
    """Load vertex positions from OBJ or PLY file."""
    suffix = mesh_path.suffix.lower()
    if suffix == ".ply":
        try:
            import trimesh
            mesh = trimesh.load(str(mesh_path))
            return mesh.vertices, mesh
        except ImportError:
            pass
        # Manual PLY parse
        verts = []
        in_header = True
        with open(mesh_path, "r", encoding="utf-8") as f:
            for line in f:
                if in_header:
                    if line.strip() == "end_header":
                        in_header = False
                    continue
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        verts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        break
        return np.array(verts), None

    elif suffix == ".obj":
        try:
            import trimesh
            mesh = trimesh.load(str(mesh_path))
            return mesh.vertices, mesh
        except ImportError:
            pass
        verts = []
        with open(mesh_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("v "):
                    parts = line.strip().split()
                    verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        return np.array(verts), None

    else:
        print(f"ERROR: Unsupported mesh format: {suffix}")
        sys.exit(1)


def load_footprints_from_postgis(street=None):
    """Load building footprints from PostGIS."""
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed")
        return []

    conn = psycopg2.connect(host="localhost", port=5432, database="kensington",
                            user="postgres", password="test123")
    cur = conn.cursor()

    query = """
        SELECT ba.address_full,
               ST_XMin(bf.geom) - {origin_x}, ST_YMin(bf.geom) - {origin_y},
               ST_XMax(bf.geom) - {origin_x}, ST_YMax(bf.geom) - {origin_y}
        FROM building_assessment ba
        JOIN opendata.building_footprints bf ON ba.address_full = bf.full_address
    """.format(origin_x=ORIGIN_X, origin_y=ORIGIN_Y)

    if street:
        query += f" WHERE ba.ba_street ILIKE '%{street}%'"

    cur.execute(query)
    footprints = []
    for row in cur.fetchall():
        footprints.append({
            "address": row[0],
            "bbox": [row[1], row[2], row[3], row[4]],  # local coords
        })
    conn.close()
    return footprints


def load_footprints_from_params(street=None):
    """Estimate footprints from param width/depth + site coordinates."""
    site_coords_path = PARAMS_DIR / "_site_coordinates.json"
    site_coords = {}
    if site_coords_path.exists():
        site_coords = json.loads(site_coords_path.read_text(encoding="utf-8"))

    footprints = []
    for f in sorted(PARAMS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("skipped"):
            continue

        site = p.get("site", {})
        if street and street.lower() not in (site.get("street") or "").lower():
            continue

        addr = f.stem.replace("_", " ")
        w = p.get("facade_width_m", 5.0)
        d = p.get("facade_depth_m", 15.0)

        # Get position from site coords
        coords = site_coords.get(addr, {})
        cx = coords.get("blender_x", 0)
        cy = coords.get("blender_y", 0)

        footprints.append({
            "address": addr,
            "bbox": [cx - w / 2, cy - d, cx + w / 2, cy],
        })

    return footprints


def clip_mesh_to_bbox(vertices, mesh_obj, bbox, buffer_m):
    """Clip mesh to 2D bounding box (XY plane)."""
    xmin, ymin, xmax, ymax = bbox
    xmin -= buffer_m
    ymin -= buffer_m
    xmax += buffer_m
    ymax += buffer_m

    mask = (
        (vertices[:, 0] >= xmin) & (vertices[:, 0] <= xmax) &
        (vertices[:, 1] >= ymin) & (vertices[:, 1] <= ymax)
    )

    if mesh_obj is not None:
        try:
            import trimesh
            # Use face mask: keep faces where all vertices are inside
            face_mask = mask[mesh_obj.faces].all(axis=1)
            clipped = mesh_obj.submesh([face_mask], only_watertight=False)
            if isinstance(clipped, list):
                clipped = clipped[0] if clipped else None
            return clipped
        except Exception:
            pass

    # Fallback: just return filtered vertices
    return vertices[mask]


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    if not args.block_mesh.exists():
        print(f"ERROR: Block mesh not found: {args.block_mesh}")
        sys.exit(1)

    print(f"Loading block mesh: {args.block_mesh}")
    vertices, mesh_obj = load_mesh_vertices(args.block_mesh)
    print(f"  {len(vertices)} vertices")

    if args.footprints == "postgis":
        footprints = load_footprints_from_postgis(args.street)
    else:
        footprints = load_footprints_from_params(args.street)

    print(f"  {len(footprints)} footprints loaded")

    clipped = 0
    for fp in footprints:
        addr = fp["address"]
        slug = addr.replace(" ", "_").replace(",", "")
        out_path = args.output / f"{slug}.obj"

        result = clip_mesh_to_bbox(vertices, mesh_obj, fp["bbox"], args.buffer_m)

        if result is None or (hasattr(result, "__len__") and len(result) == 0):
            continue

        try:
            import trimesh
            if isinstance(result, trimesh.Trimesh):
                result.export(str(out_path))
                clipped += 1
                print(f"  {addr}: {len(result.vertices)} verts -> {out_path.name}")
                continue
        except (ImportError, AttributeError):
            pass

        # Fallback: save as PLY point cloud
        ply_path = out_path.with_suffix(".ply")
        pts = result if isinstance(result, np.ndarray) else np.array(result)
        with open(ply_path, "w", encoding="utf-8") as f:
            f.write(f"ply\nformat ascii 1.0\nelement vertex {len(pts)}\n")
            f.write("property float x\nproperty float y\nproperty float z\nend_header\n")
            for pt in pts:
                f.write(f"{pt[0]:.6f} {pt[1]:.6f} {pt[2]:.6f}\n")
        clipped += 1

    print(f"\nClipped {clipped}/{len(footprints)} buildings -> {args.output}")


if __name__ == "__main__":
    main()
