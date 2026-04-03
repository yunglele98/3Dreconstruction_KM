#!/usr/bin/env python3
"""Segment facade elements (windows, doors, storefronts) from field photos.

Uses YOLOv11+SAM2 when available, otherwise falls back to a simple
edge-based rectangle detector as a placeholder.

Usage:
    python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON sorted/" --output segmentation/
    python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON sorted/" --output segmentation/ --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
OUTPUT_DIR = REPO_ROOT / "segmentation"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Facade element classes for segmentation output
ELEMENT_CLASSES = [
    "window", "door", "storefront", "balcony", "cornice",
    "sign", "awning", "chimney", "porch", "bay_window",
]


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


def _try_import_ml_models():
    """Try to import YOLOv11 + SAM2."""
    try:
        from ultralytics import YOLO
        from segment_anything import sam_model_registry, SamPredictor
        yolo = YOLO("yolov11n.pt")
        sam_checkpoint = "sam2_hiera_small.pt"
        sam = sam_model_registry["hiera_s"](checkpoint=sam_checkpoint)
        predictor = SamPredictor(sam)
        return yolo, predictor
    except Exception:
        return None, None


def segment_ml(image_path, output_dir, yolo, sam_predictor):
    """Segment using YOLOv11 detection + SAM2 masks."""
    img = Image.open(image_path).convert("RGB")
    img_arr = np.array(img)

    results = yolo(img_arr, verbose=False)
    elements = []

    sam_predictor.set_image(img_arr)

    for det in results[0].boxes:
        x1, y1, x2, y2 = det.xyxy[0].tolist()
        conf = float(det.conf[0])
        cls_id = int(det.cls[0])
        cls_name = results[0].names.get(cls_id, "unknown")

        # Map YOLO COCO classes to facade elements
        facade_class = _map_coco_to_facade(cls_name)
        if not facade_class:
            continue

        elements.append({
            "class": facade_class,
            "confidence": round(conf, 3),
            "bbox": [round(x1), round(y1), round(x2), round(y2)],
        })

    # Save elements JSON
    stem = image_path.stem
    elements_data = {
        "image": image_path.name,
        "width": img.size[0],
        "height": img.size[1],
        "method": "yolov11+sam2",
        "elements": elements,
    }
    json_out = output_dir / f"{stem}_elements.json"
    json_out.write_text(json.dumps(elements_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save mask (combined)
    mask = np.zeros((img.size[1], img.size[0]), dtype=np.uint8)
    for idx, el in enumerate(elements, 1):
        x1, y1, x2, y2 = el["bbox"]
        mask[y1:y2, x1:x2] = min(idx * 30, 255)
    Image.fromarray(mask).save(output_dir / f"{stem}_mask.png")
    return True


def _map_coco_to_facade(coco_class):
    """Map COCO detection class to facade element class."""
    mapping = {
        "window": "window",
        "door": "door",
        "clock": "window",  # round windows sometimes detected as clocks
    }
    return mapping.get(coco_class)


def segment_fallback(image_path, output_dir):
    """Fallback: detect rectangular regions as potential windows/doors."""
    img = Image.open(image_path).convert("L")
    w, h = img.size

    # Resize for processing
    max_side = 1024
    scale = 1.0
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    pw, ph = img.size

    arr = np.array(img, dtype=np.float32)

    # Edge detection via Sobel
    dx = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
    )), dtype=np.float32)
    dy = np.array(img.filter(ImageFilter.Kernel(
        (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
    )), dtype=np.float32)
    edges = np.sqrt(dx**2 + dy**2)

    # Threshold edges
    threshold = np.percentile(edges, 85)
    binary = (edges > threshold).astype(np.uint8)

    # Find rectangular regions by scanning for dark rectangles (windows)
    elements = []
    # Simple grid scan: look for darker rectangular patches
    min_win_w = int(pw * 0.04)
    min_win_h = int(ph * 0.05)
    max_win_w = int(pw * 0.25)
    max_win_h = int(ph * 0.25)

    # Scan with a sliding window at a few scales
    step = max(min_win_w, 8)
    for win_w, win_h in [(min_win_w * 2, min_win_h * 2), (min_win_w * 3, min_win_h * 3)]:
        if win_w > max_win_w or win_h > max_win_h:
            continue
        for y in range(0, ph - win_h, step):
            for x in range(0, pw - win_w, step):
                patch = arr[y:y + win_h, x:x + win_w]
                patch_mean = patch.mean()
                # Windows tend to be darker than surrounding facade
                surround_y0 = max(0, y - 5)
                surround_y1 = min(ph, y + win_h + 5)
                surround_x0 = max(0, x - 5)
                surround_x1 = min(pw, x + win_w + 5)
                surround = arr[surround_y0:surround_y1, surround_x0:surround_x1]
                surround_mean = surround.mean()

                if patch_mean < surround_mean - 20:
                    # Check edge density around border (windows have strong edges)
                    border_top = binary[y, x:x + win_w].mean()
                    border_bot = binary[min(y + win_h - 1, ph - 1), x:x + win_w].mean()
                    border_left = binary[y:y + win_h, x].mean()
                    border_right = binary[y:y + win_h, min(x + win_w - 1, pw - 1)].mean()
                    border_score = (border_top + border_bot + border_left + border_right) / 4

                    if border_score > 0.15:
                        # Scale back to original coordinates
                        ox1 = int(x / scale)
                        oy1 = int(y / scale)
                        ox2 = int((x + win_w) / scale)
                        oy2 = int((y + win_h) / scale)

                        # Check overlap with existing detections
                        overlaps = False
                        for el in elements:
                            ex1, ey1, ex2, ey2 = el["bbox"]
                            ix1 = max(ox1, ex1)
                            iy1 = max(oy1, ey1)
                            ix2 = min(ox2, ex2)
                            iy2 = min(oy2, ey2)
                            if ix1 < ix2 and iy1 < iy2:
                                inter = (ix2 - ix1) * (iy2 - iy1)
                                area = (ox2 - ox1) * (oy2 - oy1)
                                if inter / area > 0.3:
                                    overlaps = True
                                    break
                        if not overlaps:
                            # Classify: bottom third = door candidate, else window
                            cls = "door" if oy1 > h * 0.6 else "window"
                            elements.append({
                                "class": cls,
                                "confidence": round(0.3 + border_score * 0.5, 3),
                                "bbox": [ox1, oy1, ox2, oy2],
                            })

    # Cap at reasonable number
    elements = sorted(elements, key=lambda e: e["confidence"], reverse=True)[:30]

    stem = image_path.stem
    elements_data = {
        "image": image_path.name,
        "width": w,
        "height": h,
        "method": "fallback-edge-detection",
        "elements": elements,
    }
    json_out = output_dir / f"{stem}_elements.json"
    json_out.write_text(json.dumps(elements_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate mask image
    mask = np.zeros((h, w), dtype=np.uint8)
    for idx, el in enumerate(elements, 1):
        x1, y1, x2, y2 = el["bbox"]
        mask[y1:y2, x1:x2] = min(idx * 30, 255)
    Image.fromarray(mask).save(output_dir / f"{stem}_mask.png")
    return True


def main():
    parser = argparse.ArgumentParser(description="Segment facade elements from field photos.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR,
                        help="Photo directory or single image file")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for segmentation results")
    parser.add_argument("--model", type=str, default="yolov11+sam2",
                        help="Model to use (yolov11+sam2)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of photos to process")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    photos = _collect_images(args.input, args.limit)
    if not photos:
        print(f"No images found in {args.input}")
        sys.exit(1)

    # Try ML models
    yolo, sam_predictor = (None, None)
    if args.model == "yolov11+sam2":
        yolo, sam_predictor = _try_import_ml_models()
    method = "yolov11+sam2" if yolo else "fallback-edge-detection"
    print(f"Facade segmentation ({method}): {len(photos)} photos -> {args.output}")

    processed = 0
    skipped = 0
    failed = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        json_out = args.output / f"{stem}_elements.json"

        # Skip existing
        if json_out.exists():
            skipped += 1
            continue

        print(f"Processing {i}/{len(photos)}: {photo.name}")
        try:
            if yolo and sam_predictor:
                segment_ml(photo, args.output, yolo, sam_predictor)
            else:
                segment_fallback(photo, args.output)
            processed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {failed} failed ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
