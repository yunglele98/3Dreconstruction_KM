#!/usr/bin/env python3
"""Retopologize raw photogrammetric meshes using Instant Meshes.

Converts dense, irregular COLMAP/OpenMVS meshes into clean quad-dominant
meshes suitable for Blender import and material assignment.

Usage:
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/
    python scripts/reconstruct/retopologize.py --input meshes/raw/22_Lippincott.obj --target-faces 5000
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "meshes" / "raw"
DEFAULT_OUTPUT = REPO_ROOT / "meshes" / "retopo"


def find_instant_meshes():
    """Locate Instant Meshes executable."""
    candidates = [
        shutil.which("instant-meshes"),
        shutil.which("InstantMeshes"),
        "C:/Program Files/Instant Meshes/Instant Meshes.exe",
        "C:/tools/instant-meshes/Instant Meshes.exe",
        str(REPO_ROOT / "tools" / "Instant Meshes.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def retopologize(input_path, output_path, instant_meshes_bin, target_faces=5000,
                 smooth_iter=2, deterministic=True):
    """Run Instant Meshes on a single mesh."""
    cmd = [
        instant_meshes_bin,
        str(input_path),
        "-o", str(output_path),
        "-f", str(target_faces),
        "-S", str(smooth_iter),
    ]
    if deterministic:
        cmd.append("-d")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.returncode == 0, result.stderr[:300] if result.returncode != 0 else ""


def parse_args():
    parser = argparse.ArgumentParser(description="Retopologize meshes via Instant Meshes.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-faces", type=int, default=5000)
    parser.add_argument("--smooth-iter", type=int, default=2)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--method", choices=["instant-meshes", "pymeshlab"], default="instant-meshes")
    return parser.parse_args()


def retopo_pymeshlab(input_path, output_path, target_faces=5000):
    """Fallback retopology using pymeshlab quadric decimation."""
    try:
        import pymeshlab
    except ImportError:
        return False, "pymeshlab not installed"

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(input_path))
    mesh = ms.current_mesh()
    current_faces = mesh.face_number()

    if current_faces > target_faces:
        ratio = target_faces / current_faces
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_faces)

    ms.save_current_mesh(str(output_path))
    final_mesh = ms.current_mesh()
    return True, f"{current_faces} -> {final_mesh.face_number()} faces"


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    # Find input meshes
    if args.input.is_file():
        meshes = [args.input]
    else:
        meshes = sorted(args.input.glob("*.obj")) + sorted(args.input.glob("*.ply"))

    if args.limit:
        meshes = meshes[: args.limit]

    if not meshes:
        print(f"No meshes found in {args.input}")
        return

    # Find tool
    im_bin = None
    if args.method == "instant-meshes":
        im_bin = find_instant_meshes()
        if not im_bin:
            print("Instant Meshes not found, falling back to pymeshlab")
            args.method = "pymeshlab"

    print(f"Retopologize: {len(meshes)} meshes, target {args.target_faces} faces, method={args.method}")

    processed = 0
    errors = 0
    start = time.time()

    for i, mesh_path in enumerate(meshes, 1):
        out_path = args.output / mesh_path.name

        if args.skip_existing and out_path.exists():
            continue

        print(f"  [{i}/{len(meshes)}] {mesh_path.stem}...")

        if args.method == "instant-meshes":
            ok, msg = retopologize(mesh_path, out_path, im_bin, args.target_faces, args.smooth_iter)
        else:
            ok, msg = retopo_pymeshlab(mesh_path, out_path, args.target_faces)

        if ok:
            processed += 1
            if msg:
                print(f"    {msg}")
        else:
            errors += 1
            print(f"    FAILED: {msg}")

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {errors} errors in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
