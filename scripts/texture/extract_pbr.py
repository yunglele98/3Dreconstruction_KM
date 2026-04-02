#!/usr/bin/env python3
"""Extract PBR maps (normal, AO, roughness) from field photos.

Uses Intrinsic Anything or fallback edge-detection methods to decompose
a facade photo into PBR texture maps for material creation.

Designed for cloud GPU execution — prepare inputs locally, run on A100.

Usage:
    python scripts/texture/extract_pbr.py --input "PHOTOS KENSINGTON sorted/Augusta Ave/" --output textures/pbr/
    python scripts/texture/extract_pbr.py --input photos/test.jpg --output textures/pbr/ --method edge
    python scripts/texture/extract_pbr.py --prepare-cloud --output cloud_session/pbr/upload/
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "textures" / "pbr"


def extract_normal_from_photo(image_path, output_dir):
    """Generate a normal map from a photo using Sobel edge detection."""
    img = Image.open(image_path).convert("L")
    arr = np.array(img, dtype=np.float32) / 255.0

    # Sobel gradients
    from PIL import ImageFilter
    dx = np.array(img.filter(ImageFilter.Kernel((3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1)), dtype=np.float32) / 255.0
    dy = np.array(img.filter(ImageFilter.Kernel((3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1)), dtype=np.float32) / 255.0

    # Normal map: R=dx, G=dy, B=1 (normalized)
    strength = 2.0
    nx = dx * strength
    ny = dy * strength
    nz = np.ones_like(nx)
    mag = np.sqrt(nx**2 + ny**2 + nz**2)
    nx, ny, nz = nx / mag, ny / mag, nz / mag

    # Convert to 0-255 range (tangent space)
    normal = np.stack([
        ((nx + 1) * 0.5 * 255).astype(np.uint8),
        ((ny + 1) * 0.5 * 255).astype(np.uint8),
        ((nz + 1) * 0.5 * 255).astype(np.uint8),
    ], axis=-1)

    stem = Path(image_path).stem
    out = output_dir / f"{stem}_normal.png"
    Image.fromarray(normal).save(out)
    return out


def extract_ao_from_photo(image_path, output_dir):
    """Generate ambient occlusion map from photo luminance."""
    img = Image.open(image_path).convert("L")

    # AO approximation: blur + invert dark areas
    blurred = img.filter(ImageFilter.GaussianBlur(radius=15))
    arr = np.array(img, dtype=np.float32)
    blur_arr = np.array(blurred, dtype=np.float32)

    # AO = areas where local value is darker than surroundings
    ao = np.clip(blur_arr - arr + 128, 0, 255).astype(np.uint8)

    stem = Path(image_path).stem
    out = output_dir / f"{stem}_ao.png"
    Image.fromarray(ao).save(out)
    return out


def extract_roughness_from_photo(image_path, output_dir):
    """Generate roughness map from photo texture frequency."""
    img = Image.open(image_path).convert("L")

    # High-frequency content = rough surface
    blurred = img.filter(ImageFilter.GaussianBlur(radius=5))
    arr = np.array(img, dtype=np.float32)
    blur_arr = np.array(blurred, dtype=np.float32)

    # Roughness = local variance (high freq content)
    diff = np.abs(arr - blur_arr)
    roughness = np.clip(diff * 3 + 100, 0, 255).astype(np.uint8)

    stem = Path(image_path).stem
    out = output_dir / f"{stem}_roughness.png"
    Image.fromarray(roughness).save(out)
    return out


def prepare_cloud_session(photo_dir, output_dir, limit=200):
    """Package photos + script for cloud GPU Intrinsic Anything session."""
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    photos = sorted(photo_dir.rglob("*.jpg"))[:limit]

    # Copy photos
    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        shutil.copy2(p, img_dir / p.name)

    # Write run script
    run_script = upload_dir / "run.sh"
    run_script.write_text("""#!/bin/bash
# Intrinsic Anything PBR extraction — run on A100
# Estimated time: ~2 min per image, ~$0.75 for 200 images

pip install torch torchvision diffusers accelerate

# Clone Intrinsic Anything if not present
if [ ! -d "IntrinsicAnything" ]; then
    git clone https://github.com/zju3dv/IntrinsicAnything.git
fi

cd IntrinsicAnything

mkdir -p ../output/normal ../output/albedo ../output/roughness

for img in ../images/*.jpg; do
    stem=$(basename "$img" .jpg)
    echo "Processing $stem..."
    python predict.py --input "$img" --output_dir ../output/ --type normal
    python predict.py --input "$img" --output_dir ../output/ --type albedo
    python predict.py --input "$img" --output_dir ../output/ --type roughness
done

echo "Done. Download ../output/"
""", encoding="utf-8")

    print(f"  Cloud session prepared: {len(photos)} photos -> {upload_dir}")
    print(f"  Upload to cloud GPU and run: bash run.sh")
    print(f"  Estimated cost: ${len(photos) * 0.004:.2f} on A100")
    return upload_dir


def main():
    parser = argparse.ArgumentParser(description="Extract PBR maps from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--method", choices=["edge", "intrinsic"], default="edge",
                        help="edge=local Sobel, intrinsic=Intrinsic Anything (cloud GPU)")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--prepare-cloud", action="store_true")
    args = parser.parse_args()

    if args.prepare_cloud:
        prepare_cloud_session(args.input, args.output, args.limit)
        return

    args.output.mkdir(parents=True, exist_ok=True)

    if args.input.is_file():
        photos = [args.input]
    else:
        photos = sorted(args.input.rglob("*.jpg"))[:args.limit]

    print(f"PBR extraction ({args.method}): {len(photos)} photos")

    for i, photo in enumerate(photos, 1):
        try:
            extract_normal_from_photo(photo, args.output)
            extract_ao_from_photo(photo, args.output)
            extract_roughness_from_photo(photo, args.output)
            if i % 20 == 0:
                print(f"  [{i}/{len(photos)}] {photo.stem}")
        except Exception as e:
            print(f"  [{i}] {photo.stem}: ERROR - {e}")

    print(f"\nDone: {args.output}")


if __name__ == "__main__":
    main()
