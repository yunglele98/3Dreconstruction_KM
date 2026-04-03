#!/usr/bin/env python3
"""Extract keypoint features from field photos using LightGlue + SuperPoint.

Outputs .h5 files per photo with keypoints, descriptors, and scores.
These feed into COLMAP for multi-view reconstruction.

Usage:
    python scripts/sense/extract_features.py [--limit N]
    python scripts/sense/extract_features.py --input-dir "PHOTOS KENSINGTON sorted" --output-dir features/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract keypoint features using LightGlue + SuperPoint."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
        help="Root directory containing <street>/*.jpg photos.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "features",
        help="Directory to write .h5 feature outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after processing N photos.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip photos that already have feature files.",
    )
    parser.add_argument(
        "--max-keypoints",
        type=int,
        default=2048,
        help="Maximum keypoints per image (default: 2048).",
    )
    return parser.parse_args()


def load_extractor(max_keypoints=2048):
    """Load SuperPoint extractor via kornia or hloc."""
    try:
        import torch
        from lightglue import SuperPoint
        device = "cuda" if torch.cuda.is_available() else "cpu"
        extractor = SuperPoint(max_num_keypoints=max_keypoints).eval().to(device)
        print(f"Loaded SuperPoint on {device} (max {max_keypoints} keypoints)")
        return extractor, device
    except ImportError:
        pass

    # Fallback: try hloc (hierarchical localization)
    try:
        from hloc.extractors.superpoint import SuperPoint as HlocSP
        print("Loaded SuperPoint via hloc")
        return HlocSP({"max_keypoints": max_keypoints}), "cpu"
    except ImportError:
        pass

    print("ERROR: Neither lightglue nor hloc is installed.")
    print("  pip install lightglue   (preferred)")
    print("  OR: pip install hloc")
    sys.exit(1)


def extract_features_from_image(image_path, extractor, device):
    """Extract keypoints and descriptors from a single image."""
    import torch
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Resize to max 1024px on long side for speed
    max_side = 1024
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        w_new, h_new = int(w * scale), int(h * scale)
        img = img.resize((w_new, h_new), Image.LANCZOS)
    else:
        scale = 1.0

    img_tensor = torch.from_numpy(np.array(img)).permute(2, 0, 1).float() / 255.0
    img_tensor = img_tensor.unsqueeze(0).to(device)

    # Convert to grayscale for SuperPoint
    gray = 0.299 * img_tensor[:, 0] + 0.587 * img_tensor[:, 1] + 0.114 * img_tensor[:, 2]
    gray = gray.unsqueeze(1)

    with torch.no_grad():
        result = extractor.extract(gray)

    keypoints = result["keypoints"][0].cpu().numpy()
    descriptors = result["descriptors"][0].cpu().numpy()
    scores = result["keypoint_scores"][0].cpu().numpy() if "keypoint_scores" in result else np.ones(len(keypoints))

    # Scale keypoints back to original resolution
    if scale != 1.0:
        keypoints = keypoints / scale

    return {
        "keypoints": keypoints.astype(np.float32),
        "descriptors": descriptors.astype(np.float32),
        "scores": scores.astype(np.float32),
        "image_size": [w, h],
    }


def save_features_h5(output_path, features):
    """Save features to HDF5 file."""
    try:
        import h5py
        with h5py.File(str(output_path), "w") as f:
            for key, value in features.items():
                if isinstance(value, np.ndarray):
                    f.create_dataset(key, data=value)
                elif isinstance(value, list):
                    f.create_dataset(key, data=np.array(value))
    except ImportError:
        # Fallback: save as npz
        fallback = output_path.with_suffix(".npz")
        np.savez_compressed(str(fallback), **features)
        return fallback
    return output_path


def main():
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir}")
        sys.exit(1)

    photos = sorted(input_dir.rglob("*.jpg")) + sorted(input_dir.rglob("*.JPG"))
    if args.limit:
        photos = photos[: args.limit]

    print(f"Feature extraction: {len(photos)} photos from {input_dir}")

    extractor, device = load_extractor(args.max_keypoints)

    processed = 0
    skipped = 0
    errors = 0
    start_time = time.time()

    for i, photo_path in enumerate(photos, 1):
        stem = photo_path.stem
        out_path = output_dir / f"{stem}.h5"

        if args.skip_existing and (out_path.exists() or out_path.with_suffix(".npz").exists()):
            skipped += 1
            continue

        try:
            features = extract_features_from_image(photo_path, extractor, device)
            saved_to = save_features_h5(out_path, features)
            processed += 1
            n_kp = len(features["keypoints"])

            if i % 100 == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"  [{i}/{len(photos)}] {stem}: {n_kp} keypoints ({rate:.1f} img/s)")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [{i}/{len(photos)}] {stem}: ERROR - {e}")

    elapsed = time.time() - start_time
    print(f"\nDone: {processed} processed, {skipped} skipped, {errors} errors in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
