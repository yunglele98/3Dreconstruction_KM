#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract monocular depth maps using Depth Anything v2.

Reads field photos, runs Depth Anything v2 inference, and saves .npy depth
arrays + visualization PNGs to depth_maps/.

Usage:
    python scripts/sense/extract_depth.py --model depth-anything-v2 --input "PHOTOS KENSINGTON/" --output depth_maps/
    python scripts/sense/extract_depth.py --model depth-anything-v2 --input "PHOTOS KENSINGTON/" --output depth_maps/ --limit 10
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
DEFAULT_OUTPUT = REPO_ROOT / "depth_maps"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    """Find all photo files in *input_dir* (non-recursive)."""
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def extract_depth_map(
    photo_path: Path, output_dir: Path, *, model: str = "depth-anything-v2"
) -> dict:
    """Run depth estimation on a single photo.

    Returns a result dict. In production, this loads the Depth Anything v2
    model and runs inference. Currently generates a placeholder .npy file.
    """
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_depth.npy"
    viz_path = output_dir / f"{stem}_depth_viz.png"

    result = {
        "photo": str(photo_path),
        "model": model,
        "depth_npy": str(npy_path),
        "depth_viz": str(viz_path),
    }

    try:
        if np is None:
            result["status"] = "skipped_no_numpy"
            return result
        # Placeholder: create a dummy depth map
        # In production: load image, run model, save real depth
        placeholder = np.zeros((480, 640), dtype=np.float32)
        np.save(npy_path, placeholder)

        result["status"] = "placeholder"
        result["shape"] = list(placeholder.shape)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    model: str = "depth-anything-v2",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    """Process all photos in *input_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)
    results = []

    for photo in photos:
        npy_path = output_dir / f"{photo.stem}_depth.npy"
        if skip_existing and npy_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        results.append(extract_depth_map(photo, output_dir, model=model))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract depth maps from photos")
    parser.add_argument("--model", default="depth-anything-v2")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = run_batch(
        args.input, args.output,
        model=args.model, limit=args.limit, skip_existing=args.skip_existing,
    )

    manifest_path = args.output / "depth_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r["status"] in ("placeholder", "success"))
    skip = sum(1 for r in results if r["status"] == "skipped_existing")
    err = sum(1 for r in results if r["status"] == "error")
    print(f"Depth extraction: {ok} processed, {skip} skipped, {err} errors")


if __name__ == "__main__":
    main()
