"""
Batch Blender cleanup pass for watertight-oriented mesh repair.

Usage:
  blender --background --python scripts/batch_watertight_blends.py -- \
    --input-dir outputs/full_v2 --in-place
"""

from __future__ import annotations

import argparse
import json
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
    parser = argparse.ArgumentParser(description="Batch watertight cleanup for .blend files")
    parser.add_argument("--input-dir", required=True, help="Directory containing .blend files")
    parser.add_argument("--in-place", action="store_true", help="Overwrite source .blend files")
    parser.add_argument("--output-dir", help="Write cleaned .blend files to this directory")
    parser.add_argument("--merge-dist", type=float, default=1e-5)
    parser.add_argument("--degenerate-dist", type=float, default=1e-8)
    parser.add_argument("--limit", type=int, default=0, help="Optional cap for testing")
    parser.add_argument(
        "--report-path",
        default="outputs/watertight_batch_report.json",
        help="JSON summary output path",
    )
    return parser.parse_args(argv)


def cleanup_mesh_object(obj: bpy.types.Object, merge_dist: float, degenerate_dist: float) -> dict[str, int]:
    stats = {
        "faces_before": 0,
        "faces_after": 0,
        "verts_before": 0,
        "verts_after": 0,
        "removed_zero_area_faces": 0,
    }
    if obj.type != "MESH":
        return stats

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    stats["faces_before"] = len(bm.faces)
    stats["verts_before"] = len(bm.verts)

    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=merge_dist)
    bmesh.ops.dissolve_degenerate(bm, dist=degenerate_dist, edges=list(bm.edges))
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)

    zero_faces = [f for f in bm.faces if f.calc_area() < 1e-12]
    if zero_faces:
        bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
    stats["removed_zero_area_faces"] = len(zero_faces)

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    bm.to_mesh(mesh)
    mesh.update()
    bm.free()

    stats["faces_after"] = len(mesh.polygons)
    stats["verts_after"] = len(mesh.vertices)
    return stats


def resolve_output_path(src: Path, args: argparse.Namespace, input_dir: Path) -> Path:
    if args.in_place:
        return src
    if args.output_dir:
        rel = src.relative_to(input_dir)
        return Path(args.output_dir) / rel
    raise SystemExit("Either --in-place or --output-dir must be supplied")


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists():
        raise SystemExit(f"Input dir not found: {input_dir}")

    blend_files = sorted(input_dir.rglob("*.blend"))
    if args.limit > 0:
        blend_files = blend_files[: args.limit]

    report: dict[str, object] = {"input_dir": str(input_dir), "processed": 0, "files": []}

    for blend_path in blend_files:
        out_path = resolve_output_path(blend_path, args, input_dir).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"[watertight] processing {blend_path}")
        try:
            bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        except RuntimeError as exc:
            report["files"].append({"file": str(blend_path), "error": str(exc)})
            continue

        total = {
            "faces_before": 0,
            "faces_after": 0,
            "verts_before": 0,
            "verts_after": 0,
            "removed_zero_area_faces": 0,
            "mesh_objects": 0,
        }

        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            total["mesh_objects"] += 1
            s = cleanup_mesh_object(
                obj, merge_dist=args.merge_dist, degenerate_dist=args.degenerate_dist
            )
            total["faces_before"] += s["faces_before"]
            total["faces_after"] += s["faces_after"]
            total["verts_before"] += s["verts_before"]
            total["verts_after"] += s["verts_after"]
            total["removed_zero_area_faces"] += s["removed_zero_area_faces"]

        bpy.ops.wm.save_as_mainfile(filepath=str(out_path), copy=False)
        report["processed"] = int(report["processed"]) + 1
        report["files"].append({"file": str(out_path), "stats": total})

    report_path = Path(args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[watertight] processed={report['processed']}")
    print(f"[watertight] report={report_path}")


if __name__ == "__main__":
    main()
