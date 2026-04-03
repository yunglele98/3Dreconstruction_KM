#!/usr/bin/env python3
"""Extract signage text (OCR) from field photos.

Uses PaddleOCR when available, otherwise falls back to empty results
(signage detection requires a real OCR engine).

Usage:
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON sorted/" --output signage/
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON sorted/" --output signage/ --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "signage"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _collect_images(input_path, limit=None):
    """Collect .jpg/.png files from a file or directory."""
    if input_path.is_file():
        return [input_path]
    photos = sorted(
        p for p in input_path.rglob("*")
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if limit:
        photos = photos[:limit]
    return photos


def _try_import_paddleocr():
    """Try to import PaddleOCR."""
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        return ocr
    except Exception:
        return None


def extract_signage_ml(image_path, output_dir, ocr):
    """Extract text using PaddleOCR."""
    img = np.array(Image.open(image_path).convert("RGB"))
    results = ocr.ocr(img, cls=True)

    texts = []
    if results and results[0]:
        for line in results[0]:
            bbox = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            text = line[1][0]
            confidence = float(line[1][1])

            # Convert polygon bbox to [x_min, y_min, x_max, y_max]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            flat_bbox = [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]

            texts.append({
                "text": text,
                "confidence": round(confidence, 3),
                "bbox": flat_bbox,
            })

    stem = image_path.stem
    result = {
        "image": image_path.name,
        "method": "paddleocr",
        "texts": texts,
    }
    json_out = output_dir / f"{stem}_signage.json"
    json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def extract_signage_fallback(image_path, output_dir):
    """Fallback: produce empty signage result (OCR requires a real engine)."""
    stem = image_path.stem
    result = {
        "image": image_path.name,
        "method": "fallback-none",
        "texts": [],
    }
    json_out = output_dir / f"{stem}_signage.json"
    json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract signage text (OCR) from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR,
                        help="Photo directory or single image file")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for signage results")
    parser.add_argument("--model", type=str, default="paddleocr",
                        help="Model to use (paddleocr)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of photos to process")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    photos = _collect_images(args.input, args.limit)
    if not photos:
        print(f"No images found in {args.input}")
        sys.exit(1)

    # Try ML model
    ocr = _try_import_paddleocr() if args.model == "paddleocr" else None
    method = "paddleocr" if ocr else "fallback-none"
    print(f"Signage extraction ({method}): {len(photos)} photos -> {args.output}")
    if not ocr:
        print("  Note: PaddleOCR not available, producing empty results. Install with: pip install paddleocr")

    processed = 0
    skipped = 0
    failed = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        json_out = args.output / f"{stem}_signage.json"

        # Skip existing
        if json_out.exists():
            skipped += 1
            continue

        print(f"Processing {i}/{len(photos)}: {photo.name}")
        try:
            if ocr:
                extract_signage_ml(photo, args.output, ocr)
            else:
                extract_signage_fallback(photo, args.output)
            processed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
