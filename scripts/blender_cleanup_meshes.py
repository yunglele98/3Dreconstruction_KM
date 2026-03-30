"""
Blender-side mesh cleanup utility for a single .blend file.

Runs inside Blender Python and writes a cleaned .blend copy.

Usage:
  blender --background --python scripts/blender_cleanup_meshes.py -- \
    --blend outputs/full_v2/103_Bellevue_Ave.blend \
    --output-blend outputs/session_runs/tmp/103_Bellevue_Ave.cleaned.blend
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bmesh
import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Clean mesh geometry in a blend and save copy")
    parser.add_argument("--blend", required=True, help="Input .blend path")
    parser.add_argument("--output-blend", required=True, help="Output cleaned .blend path")
    parser.add_argument("--merge-dist", type=float, default=1e-5, help="Merge-by-distance threshold")
    parser.add_argument("--degenerate-dist", type=float, default=1e-8, help="Dissolve-degenerate threshold")
    return parser.parse_args(argv)


def cleanup_mesh_object(obj: bpy.types.Object, merge_dist: float, degenerate_dist: float) -> dict[str, int]:
    stats = {
        "faces_before": 0,
        "faces_after": 0,
        "verts_before": 0,
        "verts_after": 0,
        "removed_degenerate_faces": 0,
    }
    if obj.type != "MESH":
        return stats

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    stats["faces_before"] = len(bm.faces)
    stats["verts_before"] = len(bm.verts)

    # Merge near-duplicate verts.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=merge_dist)
    # Dissolve tiny degenerate edges/faces.
    bmesh.ops.dissolve_degenerate(bm, dist=degenerate_dist, edges=list(bm.edges))

    # Explicitly remove zero-area faces that can survive dissolve_degenerate.
    zero_faces = [f for f in bm.faces if f.calc_area() < 1e-12]
    if zero_faces:
        bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
    stats["removed_degenerate_faces"] = len(zero_faces)

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    stats["faces_after"] = len(mesh.polygons)
    stats["verts_after"] = len(mesh.vertices)
    return stats


def main() -> None:
    args = parse_args()
    blend_path = Path(args.blend).resolve()
    output_blend = Path(args.output_blend).resolve()

    if not blend_path.exists():
        raise SystemExit(f"Input blend not found: {blend_path}")

    print(f"Loading: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    total = {"faces_before": 0, "faces_after": 0, "verts_before": 0, "verts_after": 0, "removed_degenerate_faces": 0}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        s = cleanup_mesh_object(obj, merge_dist=args.merge_dist, degenerate_dist=args.degenerate_dist)
        total["faces_before"] += s["faces_before"]
        total["faces_after"] += s["faces_after"]
        total["verts_before"] += s["verts_before"]
        total["verts_after"] += s["verts_after"]
        total["removed_degenerate_faces"] += s["removed_degenerate_faces"]

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), copy=False)

    print("Cleanup summary:")
    print(f"  faces: {total['faces_before']} -> {total['faces_after']}")
    print(f"  verts: {total['verts_before']} -> {total['verts_after']}")
    print(f"  removed_zero_area_faces: {total['removed_degenerate_faces']}")
    print(f"Saved: {output_blend}")


if __name__ == "__main__":
    main()
