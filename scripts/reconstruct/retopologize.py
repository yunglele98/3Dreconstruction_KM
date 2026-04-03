#!/usr/bin/env python3
"""Retopologize photogrammetric meshes for game-engine use.

Converts raw photogrammetric meshes (high-poly, irregular) to clean
quad-dominant meshes using Instant Meshes or simple decimation.

Usage:
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/
    python scripts/reconstruct/retopologize.py --input meshes/raw/22_Lippincott.obj --output meshes/retopo/ --target-faces 5000
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def find_instant_meshes() -> str | None:
    """Locate Instant Meshes executable."""
    candidates = [
        shutil.which("instant-meshes"),
        shutil.which("InstantMeshes"),
        str(REPO_ROOT / "tools" / "instant-meshes"),
        "/usr/local/bin/instant-meshes",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def retopo_instant_meshes(input_path: Path, output_path: Path,
                          target_faces: int, im_bin: str) -> tuple[bool, str]:
    """Run Instant Meshes retopology."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        im_bin,
        str(input_path),
        "-o", str(output_path),
        "-f", str(target_faces),
        "-d",  # deterministic
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and output_path.exists():
            return True, ""
        return False, result.stderr[:300]
    except subprocess.TimeoutExpired:
        return False, "Instant Meshes timed out"


def retopo_trimesh_decimate(input_path: Path, output_path: Path,
                            target_faces: int) -> tuple[bool, str]:
    """Fallback: simple decimation using trimesh."""
    try:
        import trimesh
        mesh = trimesh.load(str(input_path), process=False)
        if isinstance(mesh, trimesh.Scene):
            meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                return False, "Empty scene"
            mesh = trimesh.util.concatenate(meshes)

        current_faces = len(mesh.faces)
        if current_faces <= target_faces:
            # Already under budget
            output_path.parent.mkdir(parents=True, exist_ok=True)
            mesh.export(str(output_path))
            return True, ""

        # Simple vertex clustering decimation
        ratio = target_faces / current_faces
        mesh = mesh.simplify_quadric_decimation(target_faces)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(output_path))
        return True, ""
    except Exception as e:
        return False, str(e)


def retopologize(input_path: Path, output_path: Path,
                 target_faces: int = 5000,
                 method: str = "auto") -> dict:
    """Retopologize a single mesh.

    Args:
        input_path: Input mesh path (OBJ, PLY, GLB).
        output_path: Output retopologized mesh path.
        target_faces: Target face count.
        method: "instant-meshes", "trimesh", or "auto".

    Returns:
        Result dict with stats.
    """
    result = {
        "input": str(input_path),
        "output": str(output_path),
        "target_faces": target_faces,
        "success": False,
        "method_used": "",
        "error": "",
    }

    if method in ("auto", "instant-meshes"):
        im_bin = find_instant_meshes()
        if im_bin:
            ok, err = retopo_instant_meshes(input_path, output_path, target_faces, im_bin)
            if ok:
                result["success"] = True
                result["method_used"] = "instant-meshes"
                return result
            if method == "instant-meshes":
                result["error"] = err
                return result

    # Fallback to trimesh
    ok, err = retopo_trimesh_decimate(input_path, output_path, target_faces)
    result["success"] = ok
    result["method_used"] = "trimesh_decimate"
    result["error"] = err
    return result


def main():
    parser = argparse.ArgumentParser(description="Retopologize photogrammetric meshes")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "meshes" / "retopo")
    parser.add_argument("--target-faces", type=int, default=5000)
    parser.add_argument("--method", choices=["auto", "instant-meshes", "trimesh"], default="auto")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if args.input.is_file():
        mesh_files = [args.input]
    else:
        mesh_files = sorted(args.input.glob("*.obj")) + sorted(args.input.glob("*.ply"))

    print(f"Retopologize: {len(mesh_files)} meshes -> target {args.target_faces} faces")

    stats = {"processed": 0, "success": 0, "errors": 0}
    for mf in mesh_files:
        out_path = args.output / mf.with_suffix(".obj").name
        if args.skip_existing and out_path.exists():
            continue

        result = retopologize(mf, out_path, args.target_faces, args.method)
        stats["processed"] += 1
        if result["success"]:
            stats["success"] += 1
            print(f"  OK: {mf.name} -> {result['method_used']}")
        else:
            stats["errors"] += 1
            print(f"  FAIL: {mf.name}: {result['error']}")

    print(f"\nRetopology: {stats}")


if __name__ == "__main__":
    main()
