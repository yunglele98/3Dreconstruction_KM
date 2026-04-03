#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Retopologize raw photogrammetric meshes.

Converts raw triangulated meshes into clean, lower-poly meshes suitable
for the procedural generator and game engines. Three strategies:

1. Instant Meshes (preferred): quad-dominant remesh via external binary
2. Mesh decimation: reduce triangle count via edge collapse (numpy/trimesh)
3. Voxel remesh: uniform voxelization (Blender-compatible output)

Usage:
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method instant-meshes
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method decimate --target-faces 5000
    python scripts/reconstruct/retopologize.py --input meshes/raw/building.obj --output meshes/retopo/ --method decimate
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --dry-run
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MESH_EXTENSIONS = {".obj", ".ply", ".stl"}


def find_instant_meshes() -> str | None:
    """Locate Instant Meshes binary."""
    candidates = [
        shutil.which("instant-meshes"),
        shutil.which("InstantMeshes"),
        "C:/Tools/InstantMeshes/Instant Meshes.exe",
        "/usr/local/bin/instant-meshes",
        str(REPO_ROOT / "tools" / "instant-meshes"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def get_mesh_stats(mesh_path: Path) -> dict:
    """Get basic mesh statistics from an OBJ or PLY file."""
    stats = {
        "path": str(mesh_path),
        "size_bytes": mesh_path.stat().st_size,
        "format": mesh_path.suffix.lower(),
        "vertices": 0,
        "faces": 0,
    }

    try:
        content = mesh_path.read_text(encoding="utf-8", errors="replace")
        if mesh_path.suffix.lower() == ".obj":
            for line in content.splitlines():
                if line.startswith("v "):
                    stats["vertices"] += 1
                elif line.startswith("f "):
                    stats["faces"] += 1
        elif mesh_path.suffix.lower() == ".ply":
            for line in content.splitlines():
                if line.startswith("element vertex"):
                    stats["vertices"] = int(line.split()[-1])
                elif line.startswith("element face"):
                    stats["faces"] = int(line.split()[-1])
                elif line.strip() == "end_header":
                    break
    except Exception:
        pass

    return stats


def retopologize_instant_meshes(
    mesh_path: Path,
    output_path: Path,
    *,
    target_faces: int = 10000,
    binary: str | None = None,
) -> dict:
    """Retopologize using Instant Meshes (quad remesh)."""
    im_bin = binary or find_instant_meshes()
    if not im_bin:
        return {"status": "instant_meshes_not_found"}

    cmd = [
        im_bin,
        str(mesh_path),
        "-o", str(output_path),
        "-f", str(target_faces),
        "-d",  # deterministic
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and output_path.exists():
            out_stats = get_mesh_stats(output_path)
            return {
                "status": "success",
                "method": "instant-meshes",
                "output_vertices": out_stats["vertices"],
                "output_faces": out_stats["faces"],
            }
        return {
            "status": "failed",
            "error": result.stderr[:300] if result.stderr else "Unknown error",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except FileNotFoundError:
        return {"status": "instant_meshes_not_found"}


def retopologize_decimate(
    mesh_path: Path,
    output_path: Path,
    *,
    target_faces: int = 10000,
) -> dict:
    """Decimate mesh using trimesh (triangle reduction via edge collapse)."""
    try:
        import trimesh
    except ImportError:
        return {"status": "trimesh_not_installed"}

    try:
        mesh = trimesh.load(str(mesh_path))

        if hasattr(mesh, "faces") and len(mesh.faces) > target_faces:
            # Use simplify_quadric_decimation if available
            simplified = mesh.simplify_quadric_decimation(target_faces)
            simplified.export(str(output_path))
            return {
                "status": "success",
                "method": "decimate",
                "input_faces": len(mesh.faces),
                "output_faces": len(simplified.faces),
                "reduction_pct": round(
                    (1 - len(simplified.faces) / len(mesh.faces)) * 100, 1
                ),
            }
        else:
            # Already under target, just copy
            shutil.copy2(mesh_path, output_path)
            face_count = len(mesh.faces) if hasattr(mesh, "faces") else 0
            return {
                "status": "success",
                "method": "copy",
                "faces": face_count,
                "note": f"Already under target ({face_count} < {target_faces})",
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def retopologize_mesh(
    mesh_path: Path,
    output_dir: Path,
    *,
    method: str = "instant-meshes",
    target_faces: int = 10000,
    dry_run: bool = False,
) -> dict:
    """Retopologize a single mesh with fallback chain."""
    output_path = output_dir / mesh_path.name
    input_stats = get_mesh_stats(mesh_path)

    result = {
        "input": str(mesh_path),
        "output": str(output_path),
        "input_stats": input_stats,
        "target_faces": target_faces,
    }

    if dry_run:
        result["status"] = "would_retopo"
        result["method"] = method
        return result

    output_dir.mkdir(parents=True, exist_ok=True)

    if method == "instant-meshes":
        retopo = retopologize_instant_meshes(
            mesh_path, output_path, target_faces=target_faces,
        )
        if retopo["status"] == "instant_meshes_not_found":
            # Fallback to decimation
            retopo = retopologize_decimate(
                mesh_path, output_path, target_faces=target_faces,
            )
            retopo["fallback"] = "instant-meshes not found, used decimate"
    elif method == "decimate":
        retopo = retopologize_decimate(
            mesh_path, output_path, target_faces=target_faces,
        )
    else:
        retopo = {"status": "unknown_method", "method": method}

    result.update(retopo)
    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    method: str = "instant-meshes",
    target_faces: int = 10000,
    dry_run: bool = False,
    skip_existing: bool = False,
) -> list[dict]:
    """Retopologize all meshes in a directory."""
    meshes = sorted(
        p for p in input_dir.rglob("*")
        if p.suffix.lower() in MESH_EXTENSIONS
    )

    results = []
    for mesh in meshes:
        output_path = output_dir / mesh.name
        if skip_existing and output_path.exists():
            results.append({
                "input": str(mesh), "status": "skipped_existing",
            })
            continue
        results.append(
            retopologize_mesh(
                mesh, output_dir, method=method,
                target_faces=target_faces, dry_run=dry_run,
            )
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Retopologize photogrammetric meshes")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--method", default="instant-meshes",
                        choices=["instant-meshes", "decimate"])
    parser.add_argument("--target-faces", type=int, default=10000)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.input.is_file():
        result = retopologize_mesh(
            args.input, args.output, method=args.method,
            target_faces=args.target_faces, dry_run=args.dry_run,
        )
        print(f"{result['status']}: {result['input']} → {result['output']}")
    elif args.input.is_dir():
        results = run_batch(
            args.input, args.output, method=args.method,
            target_faces=args.target_faces, dry_run=args.dry_run,
            skip_existing=args.skip_existing,
        )
        prefix = "[DRY RUN] " if args.dry_run else ""
        ok = sum(1 for r in results if r.get("status") == "success")
        print(f"{prefix}Retopologized {ok}/{len(results)} meshes")

        # Write manifest
        if not args.dry_run:
            args.output.mkdir(parents=True, exist_ok=True)
            manifest_path = args.output / "retopo_manifest.json"
            manifest_path.write_text(
                json.dumps(results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    else:
        print(f"[ERROR] Input not found: {args.input}")
        sys.exit(1)


if __name__ == "__main__":
    main()
