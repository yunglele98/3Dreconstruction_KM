#!/usr/bin/env python3
"""Train Gaussian splats from COLMAP point clouds.

Uses gsplat library to train 3D Gaussian Splatting representations
from COLMAP sparse/dense outputs. Designed for cloud GPU execution.

Usage:
    python scripts/reconstruct/train_splats.py --input point_clouds/colmap/22_Lippincott/ --output splats/
    python scripts/reconstruct/train_splats.py --input point_clouds/colmap/ --batch --limit 5
    python scripts/reconstruct/train_splats.py --prepare-cloud
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COLMAP_DIR = REPO_ROOT / "point_clouds" / "colmap"
OUTPUT_DIR = REPO_ROOT / "splats"


def check_gsplat():
    """Check if gsplat is available."""
    try:
        import gsplat
        return True
    except ImportError:
        return False


def train_single(workspace, output_dir, iterations=7000):
    """Train Gaussian splats for a single building."""
    sparse_dir = workspace / "sparse"
    if not sparse_dir.exists():
        return False, "No sparse model found"

    models = sorted(sparse_dir.iterdir())
    if not models:
        return False, "Empty sparse directory"

    model_dir = models[0]
    images_dir = workspace / "images"
    if not images_dir.exists():
        return False, "No images directory"

    image_count = len(list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.JPG")))
    if image_count < 3:
        return False, f"Only {image_count} images (need 3+)"

    output_dir.mkdir(parents=True, exist_ok=True)
    slug = workspace.name

    # Try gsplat Python API
    if check_gsplat():
        try:
            # gsplat training uses COLMAP format directly
            cmd = [
                sys.executable, "-m", "gsplat", "train",
                "--data_dir", str(workspace),
                "--result_dir", str(output_dir / slug),
                "--iterations", str(iterations),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                return True, str(output_dir / slug)
        except Exception as e:
            pass

    # Fallback: write a training script for manual execution
    script = output_dir / slug / "train.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"""#!/usr/bin/env python3
# Auto-generated Gaussian splatting training script
# Run on GPU: python {script.name}
import subprocess, sys
subprocess.run([
    sys.executable, "-m", "gsplat", "train",
    "--data_dir", "{workspace}",
    "--result_dir", "{output_dir / slug}",
    "--iterations", "{iterations}",
], check=True)
""", encoding="utf-8")

    return True, f"Training script written: {script}"


def prepare_cloud_session(colmap_dir, output_dir, limit=20):
    """Package COLMAP outputs for cloud GPU splat training."""
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    workspaces = sorted([d for d in colmap_dir.iterdir() if d.is_dir() and (d / "sparse").exists()])
    workspaces = workspaces[:limit]

    for ws in workspaces:
        dst = upload_dir / "workspaces" / ws.name
        if dst.exists():
            continue
        shutil.copytree(ws, dst, ignore=shutil.ignore_patterns("dense", "*.db"))

    run_script = upload_dir / "run_splats.sh"
    run_script.write_text("""#!/bin/bash
pip install gsplat torch torchvision

for ws in workspaces/*/; do
    name=$(basename "$ws")
    echo "Training splats: $name"
    python -m gsplat train \\
        --data_dir "$ws" \\
        --result_dir "output/$name" \\
        --iterations 7000
done

echo "Done. Download output/"
""", encoding="utf-8")

    print(f"  Cloud session: {len(workspaces)} workspaces -> {upload_dir}")
    print(f"  Estimated cost: ~${len(workspaces) * 0.10:.2f} on A100")


def main():
    parser = argparse.ArgumentParser(description="Train Gaussian splats from COLMAP.")
    parser.add_argument("--input", type=Path, default=COLMAP_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=7000)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--prepare-cloud", action="store_true")
    args = parser.parse_args()

    if args.prepare_cloud:
        prepare_cloud_session(args.input, args.output, args.limit or 20)
        return

    if args.batch:
        workspaces = sorted([d for d in args.input.iterdir() if d.is_dir() and (d / "sparse").exists()])
        if args.limit:
            workspaces = workspaces[:args.limit]
        print(f"Batch splat training: {len(workspaces)} buildings")
        for ws in workspaces:
            ok, msg = train_single(ws, args.output, args.iterations)
            status = "OK" if ok else "SKIP"
            print(f"  [{status}] {ws.name}: {msg}")
    else:
        ok, msg = train_single(args.input, args.output, args.iterations)
        print(f"{'OK' if ok else 'FAIL'}: {msg}")


if __name__ == "__main__":
    main()
