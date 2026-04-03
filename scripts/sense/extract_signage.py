#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract signage text using PaddleOCR.

Runs OCR on field photos to identify storefront signs, address numbers,
and heritage plaques. Classifies detected text by type.

Modes:
  1. GPU: PaddleOCR with CUDA acceleration
  2. Edge fallback: pytesseract OCR (CPU, lower accuracy)
  3. Cloud prep: packages photos for cloud execution

Usage:
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON/" --output signage/
    python scripts/sense/extract_signage.py --input "PHOTOS KENSINGTON/" --output signage/ --method tesseract
    python scripts/sense/extract_signage.py --prepare-cloud --output cloud_session/signage/
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "signage"

# Text classification patterns
ADDRESS_PATTERN = re.compile(r'^\d{1,4}\s*[A-Za-z]')
PHONE_PATTERN = re.compile(r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}')
HOURS_PATTERN = re.compile(r'(open|close|hours|mon|tue|wed|thu|fri|sat|sun)', re.I)


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in PHOTO_EXTENSIONS)
    return photos[:limit] if limit > 0 else photos


def classify_text(text: str) -> str:
    """Classify detected text by type."""
    if not text or len(text) < 2:
        return "noise"
    if ADDRESS_PATTERN.match(text):
        return "address"
    if PHONE_PATTERN.search(text):
        return "phone"
    if HOURS_PATTERN.search(text):
        return "hours"
    if len(text) > 3 and text[0].isupper():
        return "business_name"
    return "other"


def extract_paddleocr(photo_path: Path, output_dir: Path) -> dict:
    """Run PaddleOCR on a single photo."""
    stem = photo_path.stem
    json_path = output_dir / f"{stem}_signage.json"
    result = {"photo": str(photo_path), "model": "paddleocr", "output": str(json_path)}

    try:
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
        ocr_result = ocr.ocr(str(photo_path), cls=True)

        text_regions = []
        for line in (ocr_result[0] or []):
            bbox, (text, conf) = line[0], line[1]
            if conf < 0.3:
                continue
            text_regions.append({
                "text": text,
                "confidence": round(conf, 3),
                "bbox": [[int(p[0]), int(p[1])] for p in bbox],
                "type": classify_text(text),
            })

        ocr_data = {
            "photo": photo_path.name,
            "model": "paddleocr",
            "text_regions": text_regions,
        }
        json_path.write_text(json.dumps(ocr_data, indent=2, ensure_ascii=False), encoding="utf-8")

        result["status"] = "success"
        result["text_regions_found"] = len(text_regions)
        result["business_names"] = [r["text"] for r in text_regions if r["type"] == "business_name"]
        return result

    except ImportError:
        result["status"] = "paddleocr_not_installed"
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def extract_tesseract(photo_path: Path, output_dir: Path) -> dict:
    """Run Tesseract OCR as CPU fallback."""
    stem = photo_path.stem
    json_path = output_dir / f"{stem}_signage.json"
    result = {"photo": str(photo_path), "model": "tesseract", "output": str(json_path)}

    try:
        from PIL import Image
        import pytesseract

        img = Image.open(photo_path)
        w, h = img.size
        if max(w, h) > 2048:
            s = 2048 / max(w, h)
            img = img.resize((int(w * s), int(h * s)))

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        text_regions = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            if not text or len(text) < 2:
                continue
            conf = int(data["conf"][i])
            if conf < 30:
                continue

            text_regions.append({
                "text": text,
                "confidence": round(conf / 100.0, 3),
                "bbox": [[data["left"][i], data["top"][i]],
                         [data["left"][i] + data["width"][i], data["top"][i] + data["height"][i]]],
                "type": classify_text(text),
            })

        ocr_data = {
            "photo": photo_path.name,
            "model": "tesseract",
            "text_regions": text_regions,
        }
        json_path.write_text(json.dumps(ocr_data, indent=2, ensure_ascii=False), encoding="utf-8")

        result["status"] = "success"
        result["text_regions_found"] = len(text_regions)
        return result

    except ImportError:
        # Last resort: write empty result
        ocr_data = {"photo": photo_path.name, "model": "none", "text_regions": [],
                     "note": "No OCR engine available (install paddleocr or pytesseract)"}
        json_path.write_text(json.dumps(ocr_data, indent=2, ensure_ascii=False), encoding="utf-8")
        result["status"] = "no_ocr_available"
        result["text_regions_found"] = 0
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def prepare_cloud_session(input_dir: Path, output_dir: Path, limit: int = 200) -> Path:
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        shutil.copy2(p, img_dir / p.name)

    (upload_dir / "run_ocr.py").write_text('''#!/usr/bin/env python3
"""Cloud GPU OCR extraction. Run on A100."""
import json
from pathlib import Path
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
output = Path("output")
output.mkdir(exist_ok=True)

for img_path in sorted(Path("images").glob("*.jpg")):
    result = ocr.ocr(str(img_path), cls=True)
    regions = []
    for line in (result[0] or []):
        bbox, (text, conf) = line[0], line[1]
        if conf < 0.3: continue
        regions.append({"text": text, "confidence": round(conf, 3),
                        "bbox": [[int(p[0]), int(p[1])] for p in bbox]})

    data = {"photo": img_path.name, "model": "paddleocr", "text_regions": regions}
    (output / f"{img_path.stem}_signage.json").write_text(json.dumps(data, indent=2))

print(f"Done: {len(list(output.glob('*.json')))} photos processed")
''', encoding="utf-8")

    print(f"Cloud session: {len(photos)} photos → {upload_dir}")
    return upload_dir


def run_batch(input_dir, output_dir, *, method="auto", limit=0, skip_existing=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    if method == "auto":
        try:
            import paddleocr
            method = "paddle"
        except ImportError:
            method = "tesseract"

    results = []
    for photo in photos:
        json_path = output_dir / f"{photo.stem}_signage.json"
        if skip_existing and json_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        if method == "paddle":
            results.append(extract_paddleocr(photo, output_dir))
        else:
            results.append(extract_tesseract(photo, output_dir))

    return results


def main():
    parser = argparse.ArgumentParser(description="Extract signage via OCR")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--method", default="auto", choices=["auto", "paddle", "tesseract"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--prepare-cloud", action="store_true")
    args = parser.parse_args()

    if args.prepare_cloud:
        prepare_cloud_session(args.input, args.output, args.limit or 200)
        return

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = run_batch(args.input, args.output, method=args.method,
                        limit=args.limit, skip_existing=args.skip_existing)

    manifest_path = args.output / "signage_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r.get("status") == "success")
    regions = sum(r.get("text_regions_found", 0) for r in results)
    print(f"Signage extraction: {ok} processed, {regions} text regions found")


if __name__ == "__main__":
    main()
