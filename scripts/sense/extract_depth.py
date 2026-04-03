#!/usr/bin/env python3
"""Extract depth maps from field photos using Depth Anything v2.

Generates per-photo .npy depth arrays and visualization .png files.

Usage:
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --skip-existing
    python scripts/sense/extract_depth.py --model depth-anything-v2 --input "PHOTOS KENSINGTON/" --output depth_maps/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


def load_model(model_name: str = "depth-anything-v2", device: str = "cuda"):
    """Load depth estimation model.

    Attempts to load Depth Anything v2 via transformers pipeline.
    Falls back to a simple gradient-based estimator for environments
    without GPU or the model weights.
    """
    try:
        from transformers import pipeline
        pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf",
                        device=0 if device == "cuda" else -1)
        logger.info("Loaded Depth Anything v2 (Small) model")
        return pipe
    except Exception as e:
        logger.warning(f"Could not load Depth Anything v2: {e}")
        logger.info("Using fallback gradient-based depth estimator")
        return None


def estimate_depth_fallback(image_path: Path) -> np.ndarray:
    """Simple fallback depth estimation using vertical gradient.

    Assumes buildings are photographed roughly level — pixels higher
    in the image are generally farther away.
    """
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    # Vertical gradient as rough depth proxy
    depth = np.linspace(1.0, 0.0, h).reshape(h, 1).repeat(w, axis=1)
    return depth.astype(np.float32)


def estimate_depth(image_path: Path, model=None) -> np.ndarray:
    """Estimate depth from a single image.

    Args:
        image_path: Path to input image.
        model: Loaded depth model (transformers pipeline or None for fallback).

    Returns:
        2D numpy array of depth values (float32), normalized 0-1.
    """
    if model is not None:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        result = model(img)
        depth = np.array(result["depth"], dtype=np.float32)
        # Normalize to 0-1
        dmin, dmax = depth.min(), depth.max()
        if dmax > dmin:
            depth = (depth - dmin) / (dmax - dmin)
        return depth
    else:
        return estimate_depth_fallback(image_path)


def save_depth_viz(depth: np.ndarray, output_path: Path):
    """Save depth map as a colorized PNG visualization."""
    from PIL import Image
    # Normalize and convert to uint8
    d = depth.copy()
    dmin, dmax = d.min(), d.max()
    if dmax > dmin:
        d = (d - dmin) / (dmax - dmin)
    d_uint8 = (d * 255).astype(np.uint8)
    img = Image.fromarray(d_uint8, mode="L")
    img.save(output_path)


def process_directory(
    input_dir: Path,
    output_dir: Path,
    model=None,
    skip_existing: bool = False,
) -> dict:
    """Process all photos in a directory.

    Args:
        input_dir: Directory with input photos.
        output_dir: Directory for depth map outputs.
        model: Loaded depth model.
        skip_existing: Skip photos that already have depth maps.

    Returns:
        Stats dict with counts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "skipped": 0, "errors": 0}

    image_files = [
        f for f in sorted(input_dir.iterdir())
        if f.suffix.lower() in SUPPORTED_EXTS and f.is_file()
    ]

    logger.info(f"Found {len(image_files)} images in {input_dir}")

    for i, img_path in enumerate(image_files):
        stem = img_path.stem
        npy_path = output_dir / f"{stem}.npy"
        viz_path = output_dir / f"{stem}_depth.png"

        if skip_existing and npy_path.exists():
            stats["skipped"] += 1
            continue

        try:
            depth = estimate_depth(img_path, model)
            np.save(npy_path, depth)
            save_depth_viz(depth, viz_path)
            stats["processed"] += 1

            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i + 1}/{len(image_files)}")

        except Exception as e:
            logger.error(f"Error processing {img_path.name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract depth maps from photos")
    parser.add_argument("--model", default="depth-anything-v2")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "depth_maps")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--limit", type=int, default=None, help="Process at most N images")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    model = load_model(args.model, args.device)
    stats = process_directory(args.input, args.output, model, args.skip_existing)
    print(f"Depth extraction complete: {stats}")


if __name__ == "__main__":
    main()
