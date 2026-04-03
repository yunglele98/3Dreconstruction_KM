#!/usr/bin/env python3
"""Stage 1d: Extract storefront signage text via OCR.

Uses EasyOCR (torch-based, GPU-accelerated) to detect and read text from
field photos — business names, addresses, signage. Cross-references with
context.business_name in params.

Usage:
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON sorted" --output signage/
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON sorted" --output signage/ --limit 10
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON sorted" --output signage/ --skip-existing
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
PHOTOS_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
OUTPUT_DIR = REPO_ROOT / "signage"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def check_dependencies():
    missing = []
    try:
        import easyocr
    except ImportError:
        missing.append("easyocr")
    try:
        from PIL import Image
    except ImportError:
        missing.append("pillow")

    if missing:
        logger.error("Missing: %s", ", ".join(missing))
        logger.error("Install: pip install easyocr pillow")
        sys.exit(1)


def discover_photos(input_dir: Path) -> list[Path]:
    return sorted(f for f in input_dir.rglob("*")
                  if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS)


def process_photo(reader, photo_path: Path, output_dir: Path) -> dict:
    """Run OCR on a single photo."""
    stem = photo_path.stem
    out_path = output_dir / f"{stem}_text.json"

    try:
        result = reader.readtext(str(photo_path))

        texts = []
        for bbox, text, conf in result:
            # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            avg_y = sum(pt[1] for pt in bbox) / 4

            texts.append({
                "text": text,
                "confidence": round(float(conf), 3),
                "bbox": [[round(pt[0]), round(pt[1])] for pt in bbox],
                "center_y_pct": None,  # filled below
            })

        # Get image height for y-position normalization
        try:
            from PIL import Image
            img = Image.open(photo_path)
            img_h = img.height
            for t in texts:
                avg_y = sum(pt[1] for pt in t["bbox"]) / 4
                t["center_y_pct"] = round(avg_y / img_h * 100, 1)
        except Exception:
            pass

        # Filter to high-confidence text
        good_texts = [t for t in texts if t["confidence"] >= 0.5]

        # Identify likely business names (lower half of image, larger text)
        storefront_texts = [t for t in good_texts
                            if t.get("center_y_pct", 0) > 40
                            and len(t["text"]) > 2]

        data = {
            "file": photo_path.name,
            "all_texts": texts,
            "high_confidence": good_texts,
            "storefront_candidates": storefront_texts,
            "text_count": len(texts),
            "storefront_count": len(storefront_texts),
        }

        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return {"file": photo_path.name, "status": "ok",
                "texts": len(texts), "storefront": len(storefront_texts)}

    except Exception as e:
        logger.warning("  Failed %s: %s", photo_path.name, e)
        return {"file": photo_path.name, "status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Stage 1d: Extract signage OCR")
    parser.add_argument("--input", type=Path, default=PHOTOS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    check_dependencies()

    import easyocr
    import torch
    use_gpu = torch.cuda.is_available()
    logger.info("Loading EasyOCR (gpu=%s)...", use_gpu)
    reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
    logger.info("EasyOCR loaded")

    photos = discover_photos(args.input)
    logger.info("Found %d photos", len(photos))

    args.output.mkdir(parents=True, exist_ok=True)

    if args.skip_existing:
        before = len(photos)
        photos = [p for p in photos
                  if not (args.output / f"{p.stem}_text.json").exists()]
        logger.info("Skipping %d existing, %d remaining",
                     before - len(photos), len(photos))

    if args.limit > 0:
        photos = photos[:args.limit]

    t0 = time.time()
    results = []
    ok = 0

    for i, photo in enumerate(photos):
        result = process_photo(reader, photo, args.output)
        results.append(result)
        if result["status"] == "ok":
            ok += 1
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            logger.info("  %d/%d (%.1f/s)", i + 1, len(photos), rate)

    elapsed = time.time() - t0

    total_texts = sum(r.get("texts", 0) for r in results if r["status"] == "ok")
    total_storefront = sum(r.get("storefront", 0) for r in results if r["status"] == "ok")

    manifest = {
        "completed_at": datetime.now().isoformat(),
        "total_photos": len(photos),
        "ok": ok,
        "failed": len(photos) - ok,
        "elapsed_seconds": round(elapsed, 1),
        "total_text_regions": total_texts,
        "total_storefront_candidates": total_storefront,
        "results": results,
    }
    (args.output / "_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info("\nDone: %d ok in %.1fs, %d text regions, %d storefront candidates",
                ok, elapsed, total_texts, total_storefront)


if __name__ == "__main__":
    main()
