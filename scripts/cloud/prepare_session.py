#!/usr/bin/env python3
"""Prepare data packages for cloud GPU sessions.

Packages input data + run scripts for upload to Jarvislabs or similar
cloud GPU providers. Supports DUSt3R, splat training, and PBR extraction.

Usage:
    python scripts/cloud/prepare_session.py --type dust3r --limit 50
    python scripts/cloud/prepare_session.py --type splats --limit 20
    python scripts/cloud/prepare_session.py --type pbr --limit 200
    python scripts/cloud/prepare_session.py --list
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_session"

# Cost estimates per image/building (A100 @ $1.49/hr)
COST_PER_UNIT = {
    "dust3r": 0.02,   # ~2 min per building
    "splats": 0.10,   # ~5 min per building
    "pbr": 0.004,     # ~15 sec per image
}

SESSION_CONFIGS = {
    "dust3r": {
        "description": "DUSt3R single-view 3D reconstruction",
        "input_dir": "PHOTOS KENSINGTON sorted",
        "gpu": "A100",
        "estimated_time_per_unit": "2 min",
    },
    "splats": {
        "description": "Gaussian splatting from COLMAP outputs",
        "input_dir": "point_clouds/colmap",
        "gpu": "A100",
        "estimated_time_per_unit": "5 min",
    },
    "pbr": {
        "description": "Intrinsic Anything PBR extraction",
        "input_dir": "PHOTOS KENSINGTON sorted",
        "gpu": "A100 or T4",
        "estimated_time_per_unit": "15 sec",
    },
}


def prepare_dust3r(limit=50):
    """Prepare DUSt3R session."""
    upload_dir = OUTPUT_DIR / "dust3r" / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = REPO_ROOT / "PHOTOS KENSINGTON sorted"
    depth_dir = REPO_ROOT / "depth_maps"

    photos = sorted(photo_dir.rglob("*.jpg"))[:limit]

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        dst = img_dir / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    # Copy matching depth maps
    dep_dir = upload_dir / "depth_maps"
    dep_dir.mkdir(exist_ok=True)
    for p in photos:
        dep = depth_dir / f"{p.stem}.npy"
        if dep.exists():
            dst = dep_dir / dep.name
            if not dst.exists():
                shutil.copy2(dep, dst)

    run_script = upload_dir / "run.sh"
    run_script.write_text("""#!/bin/bash
pip install torch torchvision
pip install git+https://github.com/naver/dust3r.git

mkdir -p output

for img in images/*.jpg; do
    stem=$(basename "$img" .jpg)
    echo "DUSt3R: $stem"
    python -c "
from dust3r.inference import inference
from dust3r.model import AsymmetricCroCo3DStereo
from dust3r.utils.image import load_images
import numpy as np

model = AsymmetricCroCo3DStereo.from_pretrained('naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt')
model = model.cuda()

images = load_images(['$img'], size=512)
output = inference([tuple(images)], model, device='cuda', batch_size=1)

pts = output['pred1']['pts3d'][0].cpu().numpy().reshape(-1, 3)
np.save('output/${stem}.npy', pts)

# Save as PLY
with open('output/${stem}.ply', 'w') as f:
    f.write(f'ply\\nformat ascii 1.0\\nelement vertex {len(pts)}\\n')
    f.write('property float x\\nproperty float y\\nproperty float z\\nend_header\\n')
    for p in pts:
        f.write(f'{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\\n')
"
done

echo "Done. Download output/"
""", encoding="utf-8")

    return len(photos)


def prepare_splats(limit=20):
    """Prepare Gaussian splatting session."""
    from pathlib import Path
    colmap_dir = REPO_ROOT / "point_clouds" / "colmap"
    upload_dir = OUTPUT_DIR / "splats" / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    workspaces = [d for d in colmap_dir.iterdir() if d.is_dir() and (d / "sparse").exists()]
    workspaces = sorted(workspaces)[:limit]

    for ws in workspaces:
        dst = upload_dir / "workspaces" / ws.name
        if not dst.exists():
            shutil.copytree(ws, dst, ignore=shutil.ignore_patterns("dense", "*.db"))

    run_script = upload_dir / "run.sh"
    run_script.write_text("""#!/bin/bash
pip install gsplat torch torchvision

mkdir -p output

for ws in workspaces/*/; do
    name=$(basename "$ws")
    echo "Training splats: $name"
    python -m gsplat train --data_dir "$ws" --result_dir "output/$name" --iterations 7000
done

echo "Done. Download output/"
""", encoding="utf-8")

    return len(workspaces)


def prepare_pbr(limit=200):
    """Prepare PBR extraction session."""
    upload_dir = OUTPUT_DIR / "pbr" / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = REPO_ROOT / "PHOTOS KENSINGTON sorted"
    photos = sorted(photo_dir.rglob("*.jpg"))[:limit]

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        dst = img_dir / p.name
        if not dst.exists():
            shutil.copy2(p, dst)

    run_script = upload_dir / "run.sh"
    run_script.write_text("""#!/bin/bash
pip install torch torchvision diffusers accelerate

git clone https://github.com/zju3dv/IntrinsicAnything.git 2>/dev/null || true
cd IntrinsicAnything

mkdir -p ../output/normal ../output/albedo ../output/roughness

for img in ../images/*.jpg; do
    stem=$(basename "$img" .jpg)
    python predict.py --input "$img" --output_dir ../output/ --type normal
    python predict.py --input "$img" --output_dir ../output/ --type albedo
    python predict.py --input "$img" --output_dir ../output/ --type roughness
done

echo "Done. Download ../output/"
""", encoding="utf-8")

    return len(photos)


def main():
    parser = argparse.ArgumentParser(description="Prepare cloud GPU sessions.")
    parser.add_argument("--type", choices=["dust3r", "splats", "pbr"], default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        print("Available cloud session types:")
        for name, cfg in SESSION_CONFIGS.items():
            cost = COST_PER_UNIT[name] * args.limit
            print(f"  {name:<10} {cfg['description']}")
            print(f"             GPU: {cfg['gpu']}, ~{cfg['estimated_time_per_unit']}/unit, est ${cost:.2f} for {args.limit} units")
        return

    if not args.type:
        print("Specify --type (dust3r, splats, pbr) or use --list")
        return

    print(f"Preparing cloud session: {args.type}")
    if args.type == "dust3r":
        n = prepare_dust3r(args.limit)
    elif args.type == "splats":
        n = prepare_splats(args.limit)
    elif args.type == "pbr":
        n = prepare_pbr(args.limit)

    cost = COST_PER_UNIT[args.type] * n
    print(f"\n  {n} units packaged")
    print(f"  Estimated cost: ${cost:.2f}")
    print(f"  Upload: {OUTPUT_DIR / args.type / 'upload'}")
    print(f"  Run: jl start --gpu A100 && jl upload {OUTPUT_DIR / args.type / 'upload'}")


if __name__ == "__main__":
    main()
