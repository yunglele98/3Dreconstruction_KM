#!/usr/bin/env python3
"""Extract surface normal maps from field photos using DSINE.

Generates per-photo .npy normal arrays for downstream facade analysis.

Usage:
    python scripts/sense/extract_normals.py --model dsine --input "PHOTOS KENSINGTON/" --output normals/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}


def load_model(model_name: str = "dsine", device: str = "cuda"):
    """Load normal estimation model. Falls back to gradient-based."""
    try:
        from transformers import pipeline
        pipe = pipeline("image-to-image", model="huggingface/dsine-normal-nyu")
        logger.info("Loaded DSINE model")
        return pipe
    except Exception as e:
        logger.warning(f"Could not load DSINE: {e}")
        return None


def estimate_normals_fallback(image_path: Path) -> np.ndarray:
    """Gradient-based normal estimation fallback."""
    from PIL import Image
    img = np.array(Image.open(image_path).convert("L"), dtype=np.float32) / 255.0
    dx = np.gradient(img, axis=1)
    dy = np.gradient(img, axis=0)
    dz = np.ones_like(dx)
    mag = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    normals = np.stack([dx / mag, dy / mag, dz / mag], axis=2)
    return ((normals + 1) * 0.5).astype(np.float32)


def estimate_normals(image_path: Path, model=None) -> np.ndarray:
    """Estimate surface normals from a single image."""
    if model is not None:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        result = model(img)
        return np.array(result, dtype=np.float32) / 255.0
    return estimate_normals_fallback(image_path)


def process_directory(input_dir: Path, output_dir: Path, model=None,
                      skip_existing: bool = False) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "skipped": 0, "errors": 0}

    image_files = [f for f in sorted(input_dir.iterdir())
                   if f.suffix.lower() in SUPPORTED_EXTS and f.is_file()]

    for i, img_path in enumerate(image_files):
        npy_path = output_dir / f"{img_path.stem}.npy"
        if skip_existing and npy_path.exists():
            stats["skipped"] += 1
            continue
        try:
            normals = estimate_normals(img_path, model)
            np.save(npy_path, normals)
            # Save visualization
            from PIL import Image
            viz = (normals * 255).astype(np.uint8)
            if viz.ndim == 3:
                Image.fromarray(viz).save(output_dir / f"{img_path.stem}_normals.png")
            stats["processed"] += 1
        except Exception as e:
            logger.error(f"Error: {img_path.name}: {e}")
            stats["errors"] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract normal maps from photos")
    parser.add_argument("--model", default="dsine")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "normals")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    model = load_model(args.model, args.device)
    stats = process_directory(args.input, args.output, model, args.skip_existing)
    print(f"Normal extraction: {stats}")


if __name__ == "__main__":
    main()
