#!/usr/bin/env python3
"""Convert point clouds to Potree octree format for web viewing.

Uses PotreeConverter CLI to create hierarchical octree from PLY/LAS
point clouds. Output goes to web/public/potree/ for the web platform.

Usage:
    python scripts/export/export_potree.py --input point_clouds/colmap/
    python scripts/export/export_potree.py --input point_clouds/colmap/22_Lippincott/fused.ply
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DIR = REPO_ROOT / "point_clouds" / "colmap"
OUTPUT_DIR = REPO_ROOT / "web" / "public" / "potree"


def find_potree_converter():
    """Locate PotreeConverter executable."""
    candidates = [
        shutil.which("PotreeConverter"),
        shutil.which("potreeconverter"),
        "C:/tools/PotreeConverter/PotreeConverter.exe",
        "C:/Program Files/PotreeConverter/PotreeConverter.exe",
        str(REPO_ROOT / "tools" / "PotreeConverter.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def convert_to_potree(input_ply, output_dir, converter_bin):
    """Convert a single PLY to Potree format."""
    cmd = [
        converter_bin,
        str(input_ply),
        "-o", str(output_dir),
        "--generate-page", input_ply.stem,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.returncode == 0, result.stderr[:300] if result.returncode != 0 else ""


def convert_with_py3dtiles(input_ply, output_dir):
    """Fallback: convert using py3dtiles (3D Tiles, not Potree)."""
    try:
        import py3dtiles
        # py3dtiles converts to 3D Tiles format
        cmd = [sys.executable, "-m", "py3dtiles", "convert",
               str(input_ply), "--out", str(output_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0, ""
    except ImportError:
        return False, "py3dtiles not installed"


def main():
    parser = argparse.ArgumentParser(description="Convert point clouds to Potree format.")
    parser.add_argument("--input", type=Path, default=INPUT_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    converter = find_potree_converter()
    if not converter:
        print("PotreeConverter not found.")
        print("  Download from: https://github.com/potree/PotreeConverter/releases")
        print("  Place in C:/tools/PotreeConverter/ or add to PATH")
        print("  Trying py3dtiles fallback...")

    # Find PLY files
    if args.input.is_file():
        plys = [args.input]
    else:
        plys = sorted(args.input.rglob("fused.ply"))
        plys += sorted(args.input.rglob("sparse_cloud.ply"))

    if args.limit:
        plys = plys[:args.limit]

    if not plys:
        print(f"No PLY files found in {args.input}")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Converting {len(plys)} point clouds to Potree")

    converted = 0
    for i, ply in enumerate(plys, 1):
        slug = ply.parent.name if ply.name == "fused.ply" else ply.stem
        out_dir = args.output / slug

        if args.skip_existing and out_dir.exists():
            continue

        if converter:
            ok, err = convert_to_potree(ply, out_dir, converter)
        else:
            ok, err = convert_with_py3dtiles(ply, out_dir)

        if ok:
            converted += 1
        else:
            if i <= 5:
                print(f"  [{i}] {slug}: FAILED - {err}")

        if i % 10 == 0:
            print(f"  [{i}/{len(plys)}] converted")

    print(f"\nDone: {converted}/{len(plys)} converted -> {args.output}")


if __name__ == "__main__":
    main()
