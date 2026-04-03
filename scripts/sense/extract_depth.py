#!/usr/bin/env python3
"""Extract monocular depth maps from field photos.

Uses Depth Anything v2 when available, otherwise falls back to a
gradient-based placeholder that produces .npy files with correct shape.

Usage:
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON sorted/" --output depth_maps/
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON sorted/" --output depth_maps/ --limit 20
    python scripts/sense/extract_depth.py --model depth-anything-v2 --input photos/ --output depth_maps/
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "depth_maps"

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


def _try_import_depth_model():
    """Try to import Depth Anything v2 pipeline."""
    try:
        from transformers import pipeline as hf_pipeline
        depth_pipe = hf_pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
        return depth_pipe
    except Exception:
        return None


def extract_depth_ml(image_path, output_dir, depth_pipe):
    """Extract depth using Depth Anything v2."""
    img = Image.open(image_path).convert("RGB")
    result = depth_pipe(img)
    depth_map = np.array(result["depth"], dtype=np.float32)

    stem = image_path.stem
    np.save(output_dir / f"{stem}_depth.npy", depth_map)

    # Visualization: normalize to 0-255
    d_min, d_max = depth_map.min(), depth_map.max()
    if d_max > d_min:
        viz = ((depth_map - d_min) / (d_max - d_min) * 255).astype(np.uint8)
    else:
        viz = np.zeros_like(depth_map, dtype=np.uint8)
    Image.fromarray(viz).save(output_dir / f"{stem}_depth.png")
    return True


def extract_depth_fallback(image_path, output_dir):
    """Fallback: gradient-based pseudo-depth from image luminance."""
    img = Image.open(image_path).convert("L")
    w, h = img.size

    # Resize for processing if very large
    max_side = 2048
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        w, h = img.size

    arr = np.array(img, dtype=np.float32) / 255.0

    # Simple depth heuristic: vertical gradient (sky=far, ground=near)
    # combined with blur for smoothness
    vertical_gradient = np.linspace(1.0, 0.0, h).reshape(h, 1)
    vertical_gradient = np.broadcast_to(vertical_gradient, (h, w))

    # Blur the luminance to get large-scale depth cues
    blurred = np.array(img.filter(ImageFilter.GaussianBlur(radius=20)), dtype=np.float32) / 255.0

    # Combine: darker regions tend to be closer (shadows/overhangs)
    depth_map = (0.5 * vertical_gradient + 0.3 * (1.0 - blurred) + 0.2 * (1.0 - arr)).astype(np.float32)

    stem = image_path.stem
    np.save(output_dir / f"{stem}_depth.npy", depth_map)

    # Visualization
    d_min, d_max = depth_map.min(), depth_map.max()
    if d_max > d_min:
        viz = ((depth_map - d_min) / (d_max - d_min) * 255).astype(np.uint8)
    else:
        viz = np.zeros_like(depth_map, dtype=np.uint8)
    Image.fromarray(viz).save(output_dir / f"{stem}_depth.png")
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract depth maps from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR,
                        help="Photo directory or single image file")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for depth maps")
    parser.add_argument("--model", type=str, default="depth-anything-v2",
                        help="Model to use (depth-anything-v2)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of photos to process")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    photos = _collect_images(args.input, args.limit)
    if not photos:
        print(f"No images found in {args.input}")
        sys.exit(1)

    # Try ML model
    depth_pipe = _try_import_depth_model() if args.model == "depth-anything-v2" else None
    method = "depth-anything-v2" if depth_pipe else "fallback-gradient"
    print(f"Depth extraction ({method}): {len(photos)} photos -> {args.output}")

    processed = 0
    skipped = 0
    failed = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        npy_out = args.output / f"{stem}_depth.npy"

        # Skip existing
        if npy_out.exists():
            skipped += 1
            continue

        print(f"Processing {i}/{len(photos)}: {photo.name}")
        try:
            if depth_pipe:
                extract_depth_ml(photo, args.output, depth_pipe)
            else:
                extract_depth_fallback(photo, args.output)
            processed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
