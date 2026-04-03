#!/usr/bin/env python3
"""Retopologize raw photogrammetric meshes for game-engine use.

Uses Instant Meshes for quad-dominant remeshing, or copies meshes
as-is when the binary is not available.

Usage:
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method instant-meshes
    python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --target-faces 5000
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DIR = REPO_ROOT / "meshes" / "raw"
OUTPUT_DIR = REPO_ROOT / "meshes" / "retopo"


def find_instant_meshes():
    """Locate Instant Meshes executable."""
    candidates = [
        shutil.which("instant-meshes"),
        shutil.which("InstantMeshes"),
        "C:/Program Files/Instant Meshes/Instant Meshes.exe",
        "C:/Users/liam1/Apps/InstantMeshes/Instant Meshes.exe",
        "/usr/local/bin/instant-meshes",
        "/usr/bin/instant-meshes",
        str(REPO_ROOT / "tools" / "instant-meshes"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def count_obj_faces(obj_path):
    """Count faces in an OBJ file."""
    count = 0
    with open(obj_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("f "):
                count += 1
    return count


def retopologize_instant_meshes(input_path, output_path, binary, target_faces=None,
                                 smooth_iterations=2):
    """Run Instant Meshes retopology on a mesh."""
    cmd = [binary, str(input_path), "-o", str(output_path)]

    if target_faces:
        cmd.extend(["-f", str(target_faces)])

    cmd.extend(["-S", str(smooth_iterations)])

    # Deterministic mode for reproducibility
    cmd.append("-D")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return False, f"Instant Meshes failed: {result.stderr[:300]}"
        if not output_path.exists():
            return False, "No output file produced"
        return True, str(output_path)
    except subprocess.TimeoutExpired:
        return False, "Instant Meshes timed out (300s)"
    except FileNotFoundError:
        return False, f"Binary not found: {binary}"


def copy_fallback(input_path, output_path):
    """Copy mesh as-is when retopology tool is not available."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, output_path)
    return True, f"Copied as-is (no retopology tool): {output_path.name}"


def main():
    parser = argparse.ArgumentParser(
        description="Retopologize raw photogrammetric meshes."
    )
    parser.add_argument("--input", type=Path, default=INPUT_DIR,
                        help="Input directory with raw meshes")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for retopologized meshes")
    parser.add_argument("--method", type=str, default="instant-meshes",
                        choices=["instant-meshes"],
                        help="Retopology method (default: instant-meshes)")
    parser.add_argument("--target-faces", type=int, default=None,
                        help="Target face count (default: auto)")
    parser.add_argument("--smooth", type=int, default=2,
                        help="Smoothing iterations (default: 2)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip meshes that already have retopologized output")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input directory not found: {args.input}")
        sys.exit(1)

    mesh_files = sorted(
        list(args.input.glob("*.obj")) +
        list(args.input.glob("*.ply")) +
        list(args.input.glob("*.stl"))
    )

    if args.limit:
        mesh_files = mesh_files[:args.limit]

    if not mesh_files:
        print(f"No mesh files found in {args.input}")
        return

    # Find retopology binary
    binary = None
    if args.method == "instant-meshes":
        binary = find_instant_meshes()
        if not binary:
            print("WARNING: Instant Meshes not found. Will copy meshes as-is.")
            print("  Install Instant Meshes for proper retopology.")
        else:
            print(f"Instant Meshes: {binary}")

    print(f"Retopologize: {len(mesh_files)} meshes")
    print(f"  Input:  {args.input}")
    print(f"  Output: {args.output}")
    if args.target_faces:
        print(f"  Target faces: {args.target_faces}")

    if args.dry_run:
        for mesh in mesh_files:
            out = args.output / mesh.name
            existing = out.exists()
            status = "EXISTS" if existing else "PENDING"
            if mesh.suffix == ".obj":
                faces = count_obj_faces(mesh)
                print(f"  [{status}] {mesh.name} ({faces} faces)")
            else:
                size_mb = mesh.stat().st_size / 1024 / 1024
                print(f"  [{status}] {mesh.name} ({size_mb:.1f} MB)")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    results = {"OK": 0, "SKIP": 0, "FAIL": 0, "COPY": 0}
    for mesh_path in mesh_files:
        output_path = args.output / mesh_path.name

        if args.skip_existing and output_path.exists():
            results["SKIP"] += 1
            continue

        if binary:
            ok, msg = retopologize_instant_meshes(
                mesh_path, output_path, binary,
                target_faces=args.target_faces,
                smooth_iterations=args.smooth,
            )
            if ok:
                results["OK"] += 1
                # Report face reduction
                if mesh_path.suffix == ".obj" and output_path.suffix == ".obj":
                    orig = count_obj_faces(mesh_path)
                    retopo = count_obj_faces(output_path)
                    reduction = (1 - retopo / orig) * 100 if orig > 0 else 0
                    print(f"  [OK] {mesh_path.name}: {orig} -> {retopo} faces ({reduction:.0f}% reduction)")
                else:
                    print(f"  [OK] {mesh_path.name}")
            else:
                # Fall back to copy on failure
                copy_fallback(mesh_path, output_path)
                results["COPY"] += 1
                print(f"  [COPY] {mesh_path.name}: retopo failed ({msg}), copied as-is")
        else:
            copy_fallback(mesh_path, output_path)
            results["COPY"] += 1
            print(f"  [COPY] {mesh_path.name}")

    print(f"\nComplete: {results}")


if __name__ == "__main__":
    main()
