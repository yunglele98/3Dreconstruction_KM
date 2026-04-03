#!/usr/bin/env python3
"""Extract keypoint features from field photos for matching.

Uses LightGlue+SuperPoint when available, otherwise falls back to
ORB feature detection via numpy/PIL.

Usage:
    python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON sorted/" --output features/
    python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON sorted/" --output features/ --limit 20
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
OUTPUT_DIR = REPO_ROOT / "features"

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


def _try_import_lightglue():
    """Try to import LightGlue + SuperPoint."""
    try:
        import torch
        from lightglue import SuperPoint
        device = "cuda" if torch.cuda.is_available() else "cpu"
        extractor = SuperPoint(max_num_keypoints=2048).eval().to(device)
        return extractor, device
    except Exception:
        return None, None


def _resize_for_processing(img, max_side=1600):
    """Resize image if larger than max_side."""
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def extract_features_ml(image_path, output_dir, extractor, device):
    """Extract features using SuperPoint."""
    import torch
    from torchvision import transforms

    img = _resize_for_processing(Image.open(image_path).convert("L"))
    arr = np.array(img, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0).to(device)

    with torch.no_grad():
        result = extractor({"image": tensor})

    keypoints = result["keypoints"][0].cpu().numpy()
    descriptors = result["descriptors"][0].cpu().numpy()

    stem = image_path.stem

    # Save keypoints as .npy
    np.save(output_dir / f"{stem}_keypoints.npy", keypoints)
    np.save(output_dir / f"{stem}_descriptors.npy", descriptors)

    # Save summary JSON
    summary = {
        "image": image_path.name,
        "method": "lightglue+superpoint",
        "keypoints_count": int(keypoints.shape[0]),
        "descriptors_shape": list(descriptors.shape),
    }
    json_out = output_dir / f"{stem}_features.json"
    json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def extract_features_fallback(image_path, output_dir):
    """Fallback: corner-based feature detection via numpy/PIL."""
    img = _resize_for_processing(Image.open(image_path).convert("L"))
    w, h = img.size
    arr = np.array(img, dtype=np.float32)

    # Harris corner detection approximation via Sobel derivatives
    dx = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
    )), dtype=np.float32)
    dy = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
    )), dtype=np.float32)

    # Structure tensor components
    ix2 = dx * dx
    iy2 = dy * dy
    ixy = dx * dy

    # Gaussian blur the structure tensor
    k_size = 5
    from PIL import ImageFilter as IF
    ix2_blur = np.array(Image.fromarray(ix2).filter(IF.GaussianBlur(radius=k_size)), dtype=np.float32)
    iy2_blur = np.array(Image.fromarray(iy2).filter(IF.GaussianBlur(radius=k_size)), dtype=np.float32)
    ixy_blur = np.array(Image.fromarray(ixy).filter(IF.GaussianBlur(radius=k_size)), dtype=np.float32)

    # Harris response: det(M) - k * trace(M)^2
    k = 0.04
    det = ix2_blur * iy2_blur - ixy_blur * ixy_blur
    trace = ix2_blur + iy2_blur
    harris = det - k * trace * trace

    # Threshold and find local maxima
    threshold = np.percentile(harris[harris > 0], 95) if np.any(harris > 0) else 0
    candidates = np.argwhere(harris > threshold)

    # Non-maximum suppression: keep strongest in 8-pixel neighborhoods
    keypoints = []
    used = set()
    # Sort by response strength
    responses = [(int(y), int(x), float(harris[y, x])) for y, x in candidates]
    responses.sort(key=lambda r: r[2], reverse=True)

    min_dist = 8
    for y, x, resp in responses:
        grid_key = (y // min_dist, x // min_dist)
        if grid_key in used:
            continue
        used.add(grid_key)
        keypoints.append([float(x), float(y)])
        if len(keypoints) >= 2048:
            break

    keypoints_arr = np.array(keypoints, dtype=np.float32) if keypoints else np.zeros((0, 2), dtype=np.float32)

    # Simple descriptor: 8x8 patch intensity around each keypoint
    desc_size = 8
    half = desc_size // 2
    descriptors = []
    for kx, ky in keypoints_arr:
        ix, iy = int(kx), int(ky)
        if iy - half < 0 or iy + half >= h or ix - half < 0 or ix + half >= w:
            descriptors.append(np.zeros(desc_size * desc_size, dtype=np.float32))
            continue
        patch = arr[iy - half:iy + half, ix - half:ix + half].flatten()
        # Normalize
        norm = np.linalg.norm(patch)
        if norm > 0:
            patch = patch / norm
        descriptors.append(patch)

    descriptors_arr = np.array(descriptors, dtype=np.float32) if descriptors else np.zeros((0, desc_size * desc_size), dtype=np.float32)

    stem = image_path.stem

    # Save arrays
    np.save(output_dir / f"{stem}_keypoints.npy", keypoints_arr)
    np.save(output_dir / f"{stem}_descriptors.npy", descriptors_arr)

    # Save summary JSON
    summary = {
        "image": image_path.name,
        "method": "fallback-harris-corners",
        "keypoints_count": int(keypoints_arr.shape[0]),
        "descriptors_shape": list(descriptors_arr.shape),
    }
    json_out = output_dir / f"{stem}_features.json"
    json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract keypoint features from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR,
                        help="Photo directory or single image file")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for feature data")
    parser.add_argument("--model", type=str, default="lightglue+superpoint",
                        help="Model to use (lightglue+superpoint)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of photos to process")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    photos = _collect_images(args.input, args.limit)
    if not photos:
        print(f"No images found in {args.input}")
        sys.exit(1)

    # Try ML model
    extractor, device = (None, None)
    if args.model == "lightglue+superpoint":
        extractor, device = _try_import_lightglue()
    method = "lightglue+superpoint" if extractor else "fallback-harris-corners"
    print(f"Feature extraction ({method}): {len(photos)} photos -> {args.output}")

    processed = 0
    skipped = 0
    failed = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        json_out = args.output / f"{stem}_features.json"

        # Skip existing
        if json_out.exists():
            skipped += 1
            continue

        print(f"Processing {i}/{len(photos)}: {photo.name}")
        try:
            if extractor:
                extract_features_ml(photo, args.output, extractor, device)
            else:
                extract_features_fallback(photo, args.output)
            processed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
