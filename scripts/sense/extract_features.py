#!/usr/bin/env python3
"""Extract keypoints and descriptors using LightGlue+SuperPoint.

Outputs per-photo .h5 files with keypoints and descriptors for
COLMAP-compatible feature matching in multi-view reconstruction.

Usage:
    python scripts/sense/extract_features.py --input "PHOTOS KENSINGTON/" --output features/
    python scripts/sense/extract_features.py --model lightglue+superpoint --input "PHOTOS KENSINGTON/" --output features/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


def load_extractor(model_name: str = "lightglue+superpoint", device: str = "cuda"):
    """Load feature extractor model.

    Attempts to load SuperPoint via kornia or hloc.
    Falls back to ORB feature detection via OpenCV.
    """
    try:
        import torch
        from kornia.feature import LAFDescriptor, SuperPoint as KSP
        extractor = KSP(max_num_keypoints=4096).eval()
        if device == "cuda" and torch.cuda.is_available():
            extractor = extractor.cuda()
        logger.info("Loaded SuperPoint via kornia")
        return {"extractor": extractor, "type": "superpoint", "device": device}
    except Exception as e:
        logger.warning(f"Could not load SuperPoint: {e}")

    try:
        import cv2
        orb = cv2.ORB_create(nfeatures=4096)
        logger.info("Using ORB fallback feature extractor")
        return {"extractor": orb, "type": "orb"}
    except Exception as e:
        logger.warning(f"Could not load ORB: {e}")
        return {"type": "none"}


def extract_features(image_path: Path, models: dict) -> dict:
    """Extract keypoints and descriptors from a single image.

    Returns:
        Dict with keypoints (Nx2 array), descriptors (NxD array),
        and scores (N array).
    """
    from PIL import Image

    if models.get("type") == "superpoint":
        import torch
        img = Image.open(image_path).convert("L")
        img_np = np.array(img, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(img_np).unsqueeze(0).unsqueeze(0)
        device = models["device"]
        if device == "cuda":
            tensor = tensor.cuda()

        with torch.no_grad():
            result = models["extractor"](tensor)

        keypoints = result.keypoints[0].cpu().numpy()
        descriptors = result.descriptors[0].cpu().numpy()
        scores = result.detection_scores[0].cpu().numpy() if hasattr(result, 'detection_scores') else np.ones(len(keypoints))

        return {"keypoints": keypoints, "descriptors": descriptors, "scores": scores}

    elif models.get("type") == "orb":
        import cv2
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        orb = models["extractor"]
        kps, descs = orb.detectAndCompute(img, None)

        if kps and descs is not None:
            keypoints = np.array([kp.pt for kp in kps], dtype=np.float32)
            scores = np.array([kp.response for kp in kps], dtype=np.float32)
            return {"keypoints": keypoints, "descriptors": descs, "scores": scores}

    # Fallback: empty
    return {"keypoints": np.zeros((0, 2)), "descriptors": np.zeros((0, 256)), "scores": np.zeros(0)}


def save_features_h5(features: dict, output_path: Path):
    """Save features to HDF5 file if h5py available, otherwise .npz."""
    try:
        import h5py
        with h5py.File(output_path.with_suffix(".h5"), "w") as f:
            f.create_dataset("keypoints", data=features["keypoints"])
            f.create_dataset("descriptors", data=features["descriptors"])
            f.create_dataset("scores", data=features["scores"])
    except ImportError:
        np.savez(
            output_path.with_suffix(".npz"),
            keypoints=features["keypoints"],
            descriptors=features["descriptors"],
            scores=features["scores"],
        )


def process_directory(
    input_dir: Path,
    output_dir: Path,
    models: dict,
    skip_existing: bool = False,
) -> dict:
    """Process all photos in a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "skipped": 0, "errors": 0, "total_keypoints": 0}

    image_files = [
        f for f in sorted(input_dir.iterdir())
        if f.suffix.lower() in SUPPORTED_EXTS and f.is_file()
    ]

    logger.info(f"Found {len(image_files)} images in {input_dir}")

    for i, img_path in enumerate(image_files):
        stem = img_path.stem
        h5_path = output_dir / f"{stem}.h5"
        npz_path = output_dir / f"{stem}.npz"

        if skip_existing and (h5_path.exists() or npz_path.exists()):
            stats["skipped"] += 1
            continue

        try:
            features = extract_features(img_path, models)
            save_features_h5(features, output_dir / stem)

            stats["processed"] += 1
            stats["total_keypoints"] += len(features["keypoints"])

            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i + 1}/{len(image_files)}")

        except Exception as e:
            logger.error(f"Error processing {img_path.name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract features from photos")
    parser.add_argument("--model", default="lightglue+superpoint")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "features")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    models = load_extractor(args.model, args.device)
    stats = process_directory(args.input, args.output, models, args.skip_existing)
    print(f"Feature extraction complete: {stats}")


if __name__ == "__main__":
    main()
