#!/usr/bin/env python3
"""Extract surface normal maps from field photos.

Uses DSINE when available, otherwise falls back to Sobel-based normal
estimation (same approach as extract_pbr.py).

Usage:
    python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON sorted/" --output normals/
    python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON sorted/" --output normals/ --limit 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "normals"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _collect_images(input_path, limit=None):
    """Collect .jpg/.png files from a file or directory."""
    if input_path.is_file():
        return [input_path]
    photos = sorted(
        p for p in input_path.rglob("*")
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if limit:
        photos = photos[:limit]
    return photos


def _try_import_dsine():
    """Try to import DSINE normal estimation model."""
    try:
        import torch
        from dsine import DSINE
        model = DSINE.from_pretrained()
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()
        return model
    except Exception:
        return None


def _resize_for_processing(img, max_side=2048):
    """Resize image if larger than max_side."""
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def extract_normals_ml(image_path, output_dir, model):
    """Extract normals using DSINE model."""
    import torch
    from torchvision import transforms

    img = Image.open(image_path).convert("RGB")
    img = _resize_for_processing(img)

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    input_tensor = transform(img).unsqueeze(0)
    if torch.cuda.is_available():
        input_tensor = input_tensor.cuda()

    with torch.no_grad():
        normal_map = model(input_tensor)[0].cpu().numpy()

    # normal_map shape: (3, H, W) -> (H, W, 3)
    normal_map = np.transpose(normal_map, (1, 2, 0)).astype(np.float32)

    stem = image_path.stem
    np.save(output_dir / f"{stem}_normals.npy", normal_map)

    # Visualization: map [-1,1] to [0,255]
    viz = ((normal_map + 1.0) * 0.5 * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(viz).save(output_dir / f"{stem}_normals.png")
    return True


def extract_normals_fallback(image_path, output_dir):
    """Fallback: Sobel-based normal estimation from luminance."""
    img = _resize_for_processing(Image.open(image_path).convert("L"))
    w, h = img.size
    arr = np.array(img, dtype=np.float32) / 255.0

    # Sobel gradients
    dx = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
    )), dtype=np.float32) / 255.0
    dy = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
    )), dtype=np.float32) / 255.0

    # Normal map: (dx, dy, 1) normalized
    strength = 2.0
    nx = dx * strength
    ny = dy * strength
    nz = np.ones_like(nx)
    mag = np.sqrt(nx**2 + ny**2 + nz**2)
    nx, ny, nz = nx / mag, ny / mag, nz / mag

    # Stack as (H, W, 3), values in [-1, 1]
    normal_map = np.stack([nx, ny, nz], axis=-1).astype(np.float32)

    stem = image_path.stem
    np.save(output_dir / f"{stem}_normals.npy", normal_map)

    # Visualization: map [-1,1] to [0,255]
    viz = ((normal_map + 1.0) * 0.5 * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(viz).save(output_dir / f"{stem}_normals.png")
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract surface normal maps from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR,
                        help="Photo directory or single image file")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for normal maps")
    parser.add_argument("--model", type=str, default="dsine",
                        help="Model to use (dsine)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of photos to process")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    photos = _collect_images(args.input, args.limit)
    if not photos:
        print(f"No images found in {args.input}")
        sys.exit(1)

    # Try ML model
    dsine_model = _try_import_dsine() if args.model == "dsine" else None
    method = "dsine" if dsine_model else "fallback-sobel"
    print(f"Normal extraction ({method}): {len(photos)} photos -> {args.output}")

    processed = 0
    skipped = 0
    failed = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        npy_out = args.output / f"{stem}_normals.npy"

        # Skip existing
        if npy_out.exists():
            skipped += 1
            continue

        print(f"Processing {i}/{len(photos)}: {photo.name}")
        try:
            if dsine_model:
                extract_normals_ml(photo, args.output, dsine_model)
            else:
                extract_normals_fallback(photo, args.output)
            processed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
