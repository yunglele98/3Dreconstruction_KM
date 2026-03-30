"""
Optimize mesh files using pymeshlab: remove duplicates, fix non-manifolds, recompute normals.

NOT run inside Blender — uses pymeshlab standalone for mesh cleanup.

Run:
    python scripts/optimize_meshes.py --input-dir outputs/exports/ [--address "22 Lippincott St"]

Process per FBX:
1. Load via pymeshlab.MeshSet
2. Remove duplicate vertices: ms.meshing_remove_duplicate_vertices()
3. Remove duplicate faces: ms.meshing_remove_duplicate_faces()
4. Fix non-manifold edges: ms.meshing_repair_non_manifold_edges()
5. Recompute normals: ms.compute_normal_per_vertex()
6. Save optimized mesh back
7. Report stats + texture memory + draw call estimates

Output: Updated FBX files + outputs/exports/mesh_optimization_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import pymeshlab
except ImportError:
    print("Error: pymeshlab not installed")
    print("Install with: pip install pymeshlab")
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = REPO_ROOT / "outputs" / "exports"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Optimize mesh files using pymeshlab"
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing mesh files to optimize",
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Process only meshes matching this address (substring)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stats without modifying files",
    )

    return parser.parse_args()


def get_texture_memory_bytes(mesh_path: Path) -> int:
    """
    Estimate texture memory from file name patterns.
    Heuristic: look for nearby .png/.jpg files with same stem.

    Returns: Total bytes of associated texture files.
    """
    parent = mesh_path.parent
    stem = mesh_path.stem

    texture_bytes = 0
    for ext in [".png", ".jpg", ".jpeg", ".tga"]:
        for tex_path in parent.glob(f"*{stem}*{ext}"):
            if tex_path.exists():
                texture_bytes += tex_path.stat().st_size

    return texture_bytes


def optimize_mesh(mesh_path: Path, dry_run: bool = False) -> dict[str, Any] | None:
    """
    Optimize a single mesh file using pymeshlab.

    Returns: Dict of optimization stats, or None if failed.
    """
    if not mesh_path.exists():
        print(f"  File not found: {mesh_path}")
        return None

    try:
        # Load mesh
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(str(mesh_path))

        if len(ms) == 0:
            print(f"  Error: No meshes loaded from {mesh_path}")
            return None

        mesh = ms.mesh(0)

        # Record initial state
        initial_verts = len(mesh.vertex_matrix())
        initial_faces = len(mesh.face_matrix())

        # Remove duplicate vertices
        try:
            ms.meshing_remove_duplicate_vertices()
        except Exception as e:
            print(f"    Warning: Could not remove duplicate vertices: {e}")

        # Remove duplicate faces
        try:
            ms.meshing_remove_duplicate_faces()
        except Exception as e:
            print(f"    Warning: Could not remove duplicate faces: {e}")

        # Fix non-manifold edges
        non_manifold_fixed = 0
        try:
            non_manifold_before = len(ms.get_non_manifold_edges(0))
            ms.meshing_repair_non_manifold_edges()
            non_manifold_after = len(ms.get_non_manifold_edges(0))
            non_manifold_fixed = max(0, non_manifold_before - non_manifold_after)
        except Exception as e:
            print(f"    Warning: Could not repair non-manifolds: {e}")

        # Recompute normals
        try:
            ms.compute_normal_per_vertex()
        except Exception as e:
            print(f"    Warning: Could not recompute normals: {e}")

        # Record final state
        mesh = ms.mesh(0)
        final_verts = len(mesh.vertex_matrix())
        final_faces = len(mesh.face_matrix())

        # Save if not dry run
        if not dry_run:
            ms.save_current_mesh(str(mesh_path))

        # Estimate draw calls: unique material count (assume 1 for now, could be higher)
        unique_materials = 1  # Default estimate

        # Texture memory
        texture_bytes = get_texture_memory_bytes(mesh_path)

        stats = {
            "file": str(mesh_path),
            "stem": mesh_path.stem,
            "vertex_count_before": initial_verts,
            "vertex_count_after": final_verts,
            "face_count_before": initial_faces,
            "face_count_after": final_faces,
            "vertices_removed": initial_verts - final_verts,
            "faces_removed": initial_faces - final_faces,
            "non_manifold_edges_fixed": non_manifold_fixed,
            "texture_memory_bytes": texture_bytes,
            "texture_memory_mb": round(texture_bytes / (1024 * 1024), 2),
            "estimated_draw_calls": unique_materials,
            "optimization_ratio": round((final_faces / initial_faces * 100), 1) if initial_faces > 0 else 100,
        }

        return stats

    except Exception as e:
        print(f"  Error optimizing {mesh_path}: {e}")
        import traceback

        traceback.print_exc()
        return None


def main() -> None:
    """Main entry point."""
    args = parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        sys.exit(1)

    # Find mesh files
    mesh_files = list(input_dir.glob("*.fbx"))
    mesh_files.extend(input_dir.glob("*.obj"))
    mesh_files.extend(input_dir.glob("*.stl"))
    mesh_files = sorted(set(mesh_files))

    if args.address:
        mesh_files = [f for f in mesh_files if args.address.lower() in f.stem.lower()]

    if not mesh_files:
        print(f"No mesh files found in {input_dir}")
        if args.address:
            print(f"  (filtered by address: {args.address})")
        sys.exit(0)

    print(f"Found {len(mesh_files)} mesh file(s)")
    if args.dry_run:
        print("DRY RUN MODE: Will not modify files\n")

    # Process each mesh
    results = []
    for i, mesh_path in enumerate(mesh_files, 1):
        print(f"[{i}/{len(mesh_files)}] Optimizing {mesh_path.stem}...")

        stats = optimize_mesh(mesh_path, dry_run=args.dry_run)
        if stats:
            results.append(stats)
            print(
                f"  {stats['faces_removed']} faces removed "
                f"({stats['optimization_ratio']}% remaining)"
            )
            print(f"  {stats['non_manifold_edges_fixed']} non-manifold edges fixed")
            print(f"  Texture memory: {stats['texture_memory_mb']} MB")

    # Write summary report
    report: dict[str, Any] = {
        "input_dir": str(input_dir),
        "address_filter": args.address,
        "dry_run": args.dry_run,
        "total_files_processed": len(results),
        "meshes": results,
    }

    if results:
        # Summary stats
        total_verts_removed = sum(r["vertices_removed"] for r in results)
        total_faces_removed = sum(r["faces_removed"] for r in results)
        total_texture_bytes = sum(r["texture_memory_bytes"] for r in results)
        total_non_manifolds_fixed = sum(r["non_manifold_edges_fixed"] for r in results)
        avg_optimization_ratio = (
            sum(r["optimization_ratio"] for r in results) / len(results)
            if results
            else 0
        )

        report["summary"] = {
            "total_vertices_removed": total_verts_removed,
            "total_faces_removed": total_faces_removed,
            "total_non_manifold_edges_fixed": total_non_manifolds_fixed,
            "total_texture_memory_bytes": total_texture_bytes,
            "total_texture_memory_mb": round(total_texture_bytes / (1024 * 1024), 2),
            "average_optimization_ratio_percent": round(avg_optimization_ratio, 1),
        }

    # Write report
    report_path = input_dir / "mesh_optimization_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nWrote report: {report_path}")

    # Print summary table
    print("\n=== Summary ===")
    print(f"Files processed: {len(results)}")
    if results:
        print(f"Total vertices removed: {report['summary']['total_vertices_removed']}")
        print(f"Total faces removed: {report['summary']['total_faces_removed']}")
        print(
            f"Total non-manifold edges fixed: {report['summary']['total_non_manifold_edges_fixed']}"
        )
        print(
            f"Total texture memory: {report['summary']['total_texture_memory_mb']} MB"
        )
        print(
            f"Average optimization: {report['summary']['average_optimization_ratio_percent']}% faces remaining"
        )

    if args.dry_run:
        print("\nDRY RUN: No files were modified")


if __name__ == "__main__":
    main()
