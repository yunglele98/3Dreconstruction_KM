#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract signage text using PaddleOCR.

Runs OCR on field photos to identify storefront signs, address numbers,
and heritage plaques. Saves per-photo JSON results to signage/.

Usage:
    python scripts/sense/extract_signage.py --model paddleocr --input "PHOTOS KENSINGTON/" --output signage/
    python scripts/sense/extract_signage.py --model paddleocr --input "PHOTOS KENSINGTON/" --output signage/ --limit 10
"""

import argparse
import json
import sys
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "signage"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def extract_signage(
    photo_path: Path, output_dir: Path, *, model: str = "paddleocr"
) -> dict:
    """Run OCR on a single photo.

    In production: loads PaddleOCR and extracts text regions.
    Currently a stub that creates placeholder output.
    """
    stem = photo_path.stem
    json_path = output_dir / f"{stem}_signage.json"

    result = {
        "photo": str(photo_path),
        "model": model,
        "output": str(json_path),
    }

    ocr_data = {
        "photo": photo_path.name,
        "model": model,
        "text_regions": [],
        "note": "OCR pending — requires PaddleOCR installation",
    }
    json_path.write_text(json.dumps(ocr_data, indent=2, ensure_ascii=False), encoding="utf-8")
    result["status"] = "placeholder"
    result["text_regions_found"] = 0

    return result


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    model: str = "paddleocr",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)
    results = []

    for photo in photos:
        json_path = output_dir / f"{photo.stem}_signage.json"
        if skip_existing and json_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        results.append(extract_signage(photo, output_dir, model=model))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract signage via OCR")
    parser.add_argument("--model", default="paddleocr")
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

    manifest_path = args.output / "signage_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r["status"] in ("placeholder", "success"))
    print(f"Signage extraction: {ok} processed")


if __name__ == "__main__":
    main()
