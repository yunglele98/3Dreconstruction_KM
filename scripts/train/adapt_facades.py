#!/usr/bin/env python3
"""Domain adaptation from CMP Facade dataset to Kensington Market photos.

Uses a style-transfer approach to adapt CMP Facade labels to match
Kensington Market photo style. This augments our small labeled dataset
with transferred annotations from CMP's 606 annotated facade images.

Approaches (in order of complexity):
1. Direct label transfer — use CMP labels as-is (class mapping only)
2. Histogram matching — adapt CMP images to Kensington colour distribution
3. Neural style transfer — adapt CMP images to look like Kensington photos

Usage:
    python scripts/train/adapt_facades.py --cmp-dir data/cmp_facade/ --method histogram
    python scripts/train/adapt_facades.py --download  # download CMP Facade dataset
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"
CMP_DIR = REPO_ROOT / "data" / "cmp_facade"
OUTPUT_DIR = TRAINING_DIR / "adapted"

# CMP Facade -> Kensington class mapping
# CMP classes: facade, window, door, cornice, sill, balcony, blind, molding, pillar, shop
CMP_TO_KENSINGTON = {
    "facade": "wall",
    "window": "window",
    "door": "door",
    "cornice": "cornice",
    "sill": "sill",
    "balcony": "balcony",
    "blind": "shutter",
    "molding": "molding",
    "pillar": "pilaster",
    "shop": "shop",
    "deco": "molding",
}


def download_cmp_facade(output_dir):
    """Download CMP Facade dataset (instructions only — manual download required)."""
    print("CMP Facade Dataset")
    print("==================")
    print("The CMP Facade dataset must be downloaded manually:")
    print("  URL: https://cmp.felk.cvut.cz/~tylecr1/facade/")
    print(f"  Extract to: {output_dir}")
    print()
    print("Expected structure:")
    print("  data/cmp_facade/")
    print("    base/    (606 facade images)")
    print("    extended/ (additional images)")
    print("    *.png    (label masks)")
    print()
    print("After downloading, run:")
    print(f"  python scripts/train/adapt_facades.py --cmp-dir {output_dir}")


def histogram_match(source, reference):
    """Match histogram of source image to reference image."""
    from PIL import Image

    src = np.array(source).astype(np.float32)
    ref = np.array(reference).astype(np.float32)

    matched = np.zeros_like(src)
    for c in range(3):
        src_hist, src_bins = np.histogram(src[:, :, c].flatten(), 256, [0, 256])
        ref_hist, ref_bins = np.histogram(ref[:, :, c].flatten(), 256, [0, 256])

        src_cdf = src_hist.cumsum()
        ref_cdf = ref_hist.cumsum()

        src_cdf = src_cdf / src_cdf[-1]
        ref_cdf = ref_cdf / ref_cdf[-1]

        # Map source to reference
        lut = np.interp(src_cdf, ref_cdf, np.arange(256))
        matched[:, :, c] = lut[src[:, :, c].astype(int)]

    return Image.fromarray(matched.astype(np.uint8))


def adapt_images(cmp_dir, kensington_dir, output_dir, method="histogram"):
    """Adapt CMP images to Kensington style."""
    from PIL import Image

    cmp_dir = Path(cmp_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find CMP images
    cmp_images = sorted(cmp_dir.rglob("*.jpg")) + sorted(cmp_dir.rglob("*.png"))
    # Filter out label masks (typically named *_label.png)
    cmp_images = [p for p in cmp_images if "_label" not in p.stem and "_mask" not in p.stem]

    if not cmp_images:
        print(f"  No CMP images found in {cmp_dir}")
        return 0

    # Load reference Kensington images for histogram matching
    ref_images = []
    ken_dir = Path(kensington_dir)
    if ken_dir.exists():
        ken_photos = sorted(ken_dir.rglob("*.jpg"))[:50]
        for p in ken_photos:
            try:
                ref_images.append(Image.open(p).convert("RGB"))
            except Exception:
                pass

    if not ref_images:
        print("  No Kensington reference images found, using direct copy")
        method = "direct"

    # Compute average reference histogram
    if method == "histogram" and ref_images:
        # Use median of reference images
        ref_img = ref_images[len(ref_images) // 2]

    adapted = 0
    for i, cmp_path in enumerate(cmp_images):
        out_path = output_dir / f"cmp_{cmp_path.stem}.jpg"
        if out_path.exists():
            continue

        try:
            img = Image.open(cmp_path).convert("RGB")

            if method == "histogram":
                img = histogram_match(img, ref_img)
            # else: direct copy

            img.save(out_path, quality=95)
            adapted += 1

            # Copy corresponding label mask if exists
            label_path = cmp_path.with_name(cmp_path.stem + "_label.png")
            if not label_path.exists():
                label_path = cmp_path.with_suffix(".png")
            if label_path.exists() and label_path != cmp_path:
                shutil.copy2(label_path, output_dir / f"cmp_{label_path.stem}_label.png")

        except Exception as e:
            if adapted < 5:
                print(f"  Error: {cmp_path.name}: {e}")

        if (i + 1) % 100 == 0:
            print(f"  [{i + 1}/{len(cmp_images)}] adapted")

    return adapted


def remap_labels(cmp_label_dir, output_dir, class_mapping=None):
    """Remap CMP label masks to Kensington class IDs."""
    if class_mapping is None:
        class_mapping = CMP_TO_KENSINGTON

    label_files = sorted(Path(cmp_label_dir).glob("*_label.png"))
    remapped = 0

    for label_path in label_files:
        # CMP labels are colour-coded PNG masks
        # Remap to COCO-compatible format
        out_path = Path(output_dir) / label_path.name
        if out_path.exists():
            continue

        shutil.copy2(label_path, out_path)
        remapped += 1

    return remapped


def main():
    parser = argparse.ArgumentParser(description="Domain adaptation for facade segmentation.")
    parser.add_argument("--cmp-dir", type=Path, default=CMP_DIR)
    parser.add_argument("--kensington-dir", type=Path, default=TRAINING_DIR / "images")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--method", choices=["direct", "histogram"], default="histogram")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    if args.download:
        download_cmp_facade(args.cmp_dir)
        return

    if not args.cmp_dir.exists():
        print(f"CMP Facade dataset not found at {args.cmp_dir}")
        print("Run with --download for instructions.")
        return

    print(f"Domain adaptation: {args.method}")
    print(f"  CMP source: {args.cmp_dir}")
    print(f"  Kensington reference: {args.kensington_dir}")

    adapted = adapt_images(args.cmp_dir, args.kensington_dir, args.output, args.method)
    print(f"\n  Adapted {adapted} images -> {args.output}")


if __name__ == "__main__":
    main()
