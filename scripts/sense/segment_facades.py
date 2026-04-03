#!/usr/bin/env python3
"""Stage 1 — SENSE: Segment facade elements using YOLOv11 + SAM2.

Runs object detection (YOLOv11) then instance segmentation (SAM2) on field
photos to identify windows, doors, cornices, string courses, etc. Saves
per-photo mask PNGs and element JSON to segmentation/.

Usage:
    python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --model yolov11+sam2
    python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --limit 10
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
DEFAULT_OUTPUT = REPO_ROOT / "segmentation"

# Facade element classes the detector looks for
ELEMENT_CLASSES = [
    "window", "door", "storefront", "cornice", "string_course",
    "quoin", "bracket", "voussoir", "balcony", "porch",
    "chimney", "dormer", "bay_window", "signage", "awning",
    "foundation", "gutter", "downspout", "lintel", "sill",
]


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def segment_photo(
    photo_path: Path, output_dir: Path, *, model: str = "yolov11+sam2"
) -> dict:
    """Segment a single photo into facade elements.

    In production: loads YOLOv11 for detection, SAM2 for segmentation masks.
    Currently a stub that creates the output structure.
    """
    stem = photo_path.stem
    photo_out = output_dir / stem
    photo_out.mkdir(parents=True, exist_ok=True)

    result = {
        "photo": str(photo_path),
        "model": model,
        "output_dir": str(photo_out),
        "elements": [],
    }

    # Placeholder: write an empty elements JSON
    elements_data = {
        "photo": photo_path.name,
        "model": model,
        "image_size": [640, 480],
        "detections": [],
        "note": "Segmentation pending — requires YOLOv11+SAM2 models",
    }
    (photo_out / "elements.json").write_text(
        json.dumps(elements_data, indent=2), encoding="utf-8"
    )

    result["status"] = "placeholder"
    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    model: str = "yolov11+sam2",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)
    results = []

    for photo in photos:
        photo_out = output_dir / photo.stem
        if skip_existing and (photo_out / "elements.json").exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        results.append(segment_photo(photo, output_dir, model=model))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Segment facade elements")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="yolov11+sam2")
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

    manifest_path = args.output / "segmentation_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    ok = sum(1 for r in results if r["status"] in ("placeholder", "success"))
    skip = sum(1 for r in results if r["status"] == "skipped_existing")
    print(f"Segmentation: {ok} processed, {skip} skipped")


if __name__ == "__main__":
    main()
