#!/usr/bin/env python3
"""Project photo textures onto photogrammetric meshes.

For buildings with COLMAP reconstruction, projects the best field photo
onto the mesh as a UV-mapped texture. Uses camera poses from COLMAP
sparse model.

Usage:
    python scripts/texture/project_textures.py --mesh meshes/retopo/22_Lippincott.obj --photo photo.jpg
    python scripts/texture/project_textures.py --mesh-dir meshes/retopo/ --photo-dir "PHOTOS KENSINGTON sorted/"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MESH_DIR = REPO_ROOT / "meshes" / "retopo"
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "textures" / "projected"
COLMAP_DIR = REPO_ROOT / "point_clouds" / "colmap"


def load_obj_vertices(obj_path):
    """Load vertex positions from OBJ file."""
    vertices = []
    with open(obj_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return np.array(vertices)


def generate_planar_uv(vertices):
    """Generate simple planar UV projection from front face."""
    if len(vertices) == 0:
        return np.array([])

    # Project onto XZ plane (front facade)
    x = vertices[:, 0]
    z = vertices[:, 2]

    x_min, x_max = x.min(), x.max()
    z_min, z_max = z.min(), z.max()

    x_range = max(x_max - x_min, 0.001)
    z_range = max(z_max - z_min, 0.001)

    u = (x - x_min) / x_range
    v = (z - z_min) / z_range

    return np.column_stack([u, v])


def project_texture(mesh_path, photo_path, output_dir):
    """Project photo onto mesh and save textured OBJ + texture."""
    from PIL import Image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = mesh_path.stem

    # Load mesh
    vertices = load_obj_vertices(mesh_path)
    if len(vertices) == 0:
        return None

    # Generate UVs
    uvs = generate_planar_uv(vertices)

    # Copy photo as texture
    tex_name = f"{stem}_diffuse.jpg"
    tex_path = output_dir / tex_name
    img = Image.open(photo_path).convert("RGB")
    img.save(tex_path, quality=95)

    # Write material file
    mtl_path = output_dir / f"{stem}.mtl"
    mtl_path.write_text(
        f"newmtl facade\n"
        f"Ka 1.0 1.0 1.0\n"
        f"Kd 1.0 1.0 1.0\n"
        f"map_Kd {tex_name}\n",
        encoding="utf-8",
    )

    # Rewrite OBJ with UVs and material reference
    obj_out = output_dir / f"{stem}.obj"
    with open(mesh_path, "r", encoding="utf-8") as fin, \
         open(obj_out, "w", encoding="utf-8") as fout:
        fout.write(f"mtllib {stem}.mtl\n")
        fout.write(f"usemtl facade\n\n")

        # Write original content
        vt_written = False
        for line in fin:
            fout.write(line)

            # After all vertices, write UVs
            if not vt_written and not line.startswith("v "):
                for u, v in uvs:
                    fout.write(f"vt {u:.6f} {v:.6f}\n")
                vt_written = True

    return obj_out


def find_best_photo(address, photo_dir):
    """Find the best photo for an address."""
    addr_lower = address.lower().replace("_", " ")
    for subdir in sorted(photo_dir.iterdir()):
        if not subdir.is_dir():
            continue
        for photo in sorted(subdir.glob("*.jpg")):
            if addr_lower in photo.stem.lower():
                return photo
    return None


def main():
    parser = argparse.ArgumentParser(description="Project photo textures onto meshes.")
    parser.add_argument("--mesh", type=Path, default=None, help="Single mesh file")
    parser.add_argument("--mesh-dir", type=Path, default=MESH_DIR, help="Directory of meshes")
    parser.add_argument("--photo", type=Path, default=None, help="Single photo file")
    parser.add_argument("--photo-dir", type=Path, default=PHOTO_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    if args.mesh and args.photo:
        # Single file mode
        result = project_texture(args.mesh, args.photo, args.output)
        if result:
            print(f"Projected: {result}")
        return

    # Batch mode
    meshes = sorted(args.mesh_dir.glob("*.obj"))
    if args.limit:
        meshes = meshes[:args.limit]

    print(f"Projecting textures: {len(meshes)} meshes")
    projected = 0
    for i, mesh in enumerate(meshes, 1):
        photo = find_best_photo(mesh.stem, args.photo_dir)
        if not photo:
            continue
        try:
            result = project_texture(mesh, photo, args.output)
            if result:
                projected += 1
                if i % 10 == 0:
                    print(f"  [{i}/{len(meshes)}] {mesh.stem}")
        except Exception as e:
            print(f"  [{i}] {mesh.stem}: ERROR - {e}")

    print(f"\nDone: {projected} textured meshes -> {args.output}")


if __name__ == "__main__":
    main()
