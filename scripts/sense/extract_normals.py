#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract surface normal maps using DSINE.

Reads field photos and estimates per-pixel surface normals. Saves .npy
normal arrays to normals/.

Usage:
    python scripts/sense/extract_normals.py --model dsine --input "PHOTOS KENSINGTON/"
    python scripts/sense/extract_normals.py --model dsine --input "PHOTOS KENSINGTON/" --output normals/ --limit 10
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "normals"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def extract_normals(
    photo_path: Path, output_dir: Path, *, model: str = "dsine"
) -> dict:
    """Estimate surface normals for a single photo.

    In production: loads DSINE model and runs inference.
    Currently creates a placeholder .npy file.
    """
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_normals.npy"

    result = {
        "photo": str(photo_path),
        "model": model,
        "normals_npy": str(npy_path),
    }

    try:
        placeholder = np.zeros((480, 640, 3), dtype=np.float32)
        placeholder[:, :, 2] = 1.0  # Default: facing camera
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
    model: str = "dsine",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)
    results = []

    for photo in photos:
        npy_path = output_dir / f"{photo.stem}_normals.npy"
        if skip_existing and npy_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        results.append(extract_normals(photo, output_dir, model=model))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract surface normals")
    parser.add_argument("--model", default="dsine")
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

    manifest_path = args.output / "normals_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    ok = sum(1 for r in results if r["status"] in ("placeholder", "success"))
    print(f"Normals: {ok} processed")


if __name__ == "__main__":
    main()
