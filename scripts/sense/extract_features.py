#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract keypoints and descriptors using LightGlue + SuperPoint.

Runs feature extraction on field photos for use in multi-view matching
and SfM reconstruction. Saves per-photo .h5 feature files to features/.

Usage:
    python scripts/sense/extract_features.py --model lightglue+superpoint --input "PHOTOS KENSINGTON/" --output features/
    python scripts/sense/extract_features.py --model lightglue+superpoint --input "PHOTOS KENSINGTON/" --output features/ --limit 10
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "features"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def extract_features(
    photo_path: Path, output_dir: Path, *, model: str = "lightglue+superpoint"
) -> dict:
    """Extract keypoints and descriptors from a single photo.

    In production: loads SuperPoint + LightGlue and extracts features.
    Currently creates a placeholder .npz file (h5 requires h5py).
    """
    stem = photo_path.stem
    npz_path = output_dir / f"{stem}_features.npz"

    result = {
        "photo": str(photo_path),
        "model": model,
        "output": str(npz_path),
    }

    try:
        if np is None:
            result["status"] = "skipped_no_numpy"
            return result
        # Placeholder: empty keypoints and descriptors
        keypoints = np.zeros((0, 2), dtype=np.float32)
        descriptors = np.zeros((0, 256), dtype=np.float32)
        np.savez_compressed(
            npz_path, keypoints=keypoints, descriptors=descriptors
        )
        result["status"] = "placeholder"
        result["keypoint_count"] = 0
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    model: str = "lightglue+superpoint",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)
    results = []

    for photo in photos:
        npz_path = output_dir / f"{photo.stem}_features.npz"
        if skip_existing and npz_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        results.append(extract_features(photo, output_dir, model=model))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract keypoints and descriptors")
    parser.add_argument("--model", default="lightglue+superpoint")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = run_batch(
        args.input, args.output, model=args.model,
        limit=args.limit, skip_existing=args.skip_existing,
    )

    manifest_path = args.output / "features_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    ok = sum(1 for r in results if r["status"] in ("placeholder", "success"))
    print(f"Feature extraction: {ok} processed")


if __name__ == "__main__":
    main()
