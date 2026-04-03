#!/usr/bin/env python3
"""Extract storefront signage text from field photos using PaddleOCR.

Outputs OCR results per photo for downstream enrichment of business_name
and signage fields in params.

Usage:
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON/" --output signage/
    python scripts/sense/extract_signage.py --model paddleocr --input "PHOTOS KENSINGTON/" --output signage/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


def load_ocr_model(model_name: str = "paddleocr"):
    """Load OCR model. Falls back to None if PaddleOCR unavailable."""
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        logger.info("Loaded PaddleOCR model")
        return ocr
    except Exception as e:
        logger.warning(f"Could not load PaddleOCR: {e}")
        return None


def extract_text(image_path: Path, ocr_model=None) -> list[dict]:
    """Extract text regions from an image.

    Args:
        image_path: Path to input image.
        ocr_model: Loaded PaddleOCR instance or None.

    Returns:
        List of text detection dicts with text, confidence, bbox.
    """
    if ocr_model is not None:
        result = ocr_model.ocr(str(image_path), cls=True)
        detections = []
        if result and result[0]:
            for line in result[0]:
                bbox = line[0]
                text = line[1][0]
                conf = float(line[1][1])
                detections.append({
                    "text": text,
                    "confidence": conf,
                    "bbox": [[int(p[0]), int(p[1])] for p in bbox],
                })
        return detections
    else:
        # No OCR model available — return empty
        return []


def process_directory(
    input_dir: Path,
    output_dir: Path,
    ocr_model=None,
    skip_existing: bool = False,
) -> dict:
    """Process all photos in a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {"processed": 0, "skipped": 0, "errors": 0, "text_found": 0}

    image_files = [
        f for f in sorted(input_dir.iterdir())
        if f.suffix.lower() in SUPPORTED_EXTS and f.is_file()
    ]

    logger.info(f"Found {len(image_files)} images in {input_dir}")

    for i, img_path in enumerate(image_files):
        stem = img_path.stem
        json_path = output_dir / f"{stem}_signage.json"

        if skip_existing and json_path.exists():
            stats["skipped"] += 1
            continue

        try:
            detections = extract_text(img_path, ocr_model)

            output = {
                "source_image": img_path.name,
                "detections": detections,
                "text_count": len(detections),
            }
            json_path.write_text(
                json.dumps(output, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            stats["processed"] += 1
            if detections:
                stats["text_found"] += 1

            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i + 1}/{len(image_files)}")

        except Exception as e:
            logger.error(f"Error processing {img_path.name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract signage text from photos")
    parser.add_argument("--model", default="paddleocr")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "signage")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ocr_model = load_ocr_model(args.model)
    stats = process_directory(args.input, args.output, ocr_model, args.skip_existing)
    print(f"Signage extraction complete: {stats}")


if __name__ == "__main__":
    main()
