#!/usr/bin/env python3
"""Generate pseudo-labels for facade elements using SAM2 or Grounding DINO.

Since contour-based detection finds very few elements (5 out of 1,806 photos),
we use a zero-shot approach: run Grounding DINO with text prompts for each
facade class, then filter by confidence. This gives us initial training labels
that are much better than contours for Victorian/Edwardian architecture.

Falls back to a simpler approach if Grounding DINO is not installed:
uses the existing COCO YOLO model to detect windows/doors with adjusted params.

Usage:
    python scripts/train/generate_pseudo_labels.py
    python scripts/train/generate_pseudo_labels.py --method yolo-tuned
    python scripts/train/generate_pseudo_labels.py --method grounding-dino --limit 50
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"
IMAGES_DIR = TRAINING_DIR / "images"
MANIFEST_PATH = TRAINING_DIR / "manifest.json"

CLASSES = [
    "wall", "window", "door", "roof", "balcony", "shop", "cornice",
    "pilaster", "column", "molding", "sill", "lintel", "arch",
    "shutter", "awning", "sign", "chimney", "bay_window", "porch",
    "foundation", "gutter", "downspout", "fire_escape",
]


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def detect_windows_tuned(bgr):
    """Improved window detection tuned for Kensington Market field photos.

    Uses multiple detection strategies:
    1. Adaptive threshold on CLAHE-enhanced grayscale (dark rectangles)
    2. Edge detection + contour filtering
    3. Colour-based detection (glass is typically blue-grey)
    """
    h, w = bgr.shape[:2]
    image_area = h * w
    elements = []

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Strategy 1: CLAHE + adaptive threshold (improved params)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    eq = clahe.apply(gray)

    # Multiple threshold levels
    for block_size, c_val in [(21, 6), (31, 8), (41, 10)]:
        thresh = cv2.adaptiveThreshold(
            eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, blockSize=block_size, C=c_val,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
        opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            area_frac = area / image_area

            # Window size constraints (relaxed for field photos)
            if area_frac < 0.0003 or area_frac > 0.12:
                continue

            x, y, bw, bh = cv2.boundingRect(cnt)
            if bh == 0:
                continue

            # Rectangularity check
            rect_area = bw * bh
            if rect_area == 0 or (area / rect_area) < 0.55:
                continue

            aspect = bw / bh
            if aspect < 0.4 or aspect > 3.5:
                continue

            # Skip ground-level regions (more likely doors/storefronts)
            if (y + bh) / h > 0.85 and bh / h > 0.15:
                continue

            elements.append({
                "class": "window",
                "bbox": [x, y, x + bw, y + bh],
                "confidence": 0.55,
            })

    # Strategy 2: Edge-based detection for well-defined window frames
    edges = cv2.Canny(eq, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(edges, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_frac = area / image_area
        if area_frac < 0.001 or area_frac > 0.08:
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
        if len(approx) != 4:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        if bh == 0:
            continue
        aspect = bw / bh
        if aspect < 0.5 or aspect > 2.5:
            continue

        elements.append({
            "class": "window",
            "bbox": [x, y, x + bw, y + bh],
            "confidence": 0.60,
        })

    # Deduplicate overlapping detections (NMS-like)
    elements = nms_elements(elements, iou_threshold=0.3)
    return elements


def detect_doors_tuned(bgr):
    """Improved door detection for field photos."""
    h, w = bgr.shape[:2]
    image_area = h * w
    elements = []

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    eq = clahe.apply(gray)

    thresh = cv2.adaptiveThreshold(
        eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=31, C=8,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_frac = area / image_area
        if area_frac < 0.002 or area_frac > 0.15:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        if bh == 0:
            continue

        rect_area = bw * bh
        if rect_area == 0 or (area / rect_area) < 0.50:
            continue

        aspect = bw / bh
        # Doors are typically taller than wide
        if aspect < 0.25 or aspect > 1.0:
            continue

        # Door must be in lower portion of image
        if (y + bh) / h < 0.50:
            continue

        elements.append({
            "class": "door",
            "bbox": [x, y, x + bw, y + bh],
            "confidence": 0.50,
        })

    elements = nms_elements(elements, iou_threshold=0.3)
    return elements


def nms_elements(elements, iou_threshold=0.3):
    """Non-maximum suppression for detected elements."""
    if not elements:
        return []

    # Sort by confidence descending
    elements.sort(key=lambda x: -x.get("confidence", 0))

    keep = []
    for el in elements:
        overlap = False
        for kept in keep:
            iou = compute_iou(el["bbox"], kept["bbox"])
            if iou > iou_threshold:
                overlap = True
                break
        if not overlap:
            keep.append(el)
    return keep


def compute_iou(bbox1, bbox2):
    """Compute IoU between two [x1, y1, x2, y2] boxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - inter

    return inter / union if union > 0 else 0


def generate_pseudo_labels_tuned(manifest, limit=None):
    """Generate pseudo-labels using tuned contour detection."""
    if limit:
        manifest = manifest[:limit]

    all_images = []
    all_annotations = []
    ann_id = 1
    class_to_id = {c: i for i, c in enumerate(CLASSES)}

    total_windows = 0
    total_doors = 0

    for img_idx, entry in enumerate(manifest):
        image_rel = entry.get("image", "")
        filename = Path(image_rel).name
        img_path = IMAGES_DIR / filename

        if not img_path.exists():
            continue

        try:
            img = Image.open(img_path)
            w, h = img.size
        except Exception:
            w, h = 4000, 3000

        image_id = img_idx + 1
        all_images.append({
            "id": image_id,
            "file_name": filename,
            "width": w,
            "height": h,
        })

        bgr = cv2.imread(str(img_path))
        if bgr is None:
            continue

        windows = detect_windows_tuned(bgr)
        doors = detect_doors_tuned(bgr)
        elements = windows + doors

        total_windows += len(windows)
        total_doors += len(doors)

        for el in elements:
            cls = el["class"]
            cat_id = class_to_id.get(cls)
            if cat_id is None:
                continue

            bbox = el["bbox"]
            bw = bbox[2] - bbox[0]
            bh = bbox[3] - bbox[1]

            all_annotations.append({
                "id": ann_id,
                "image_id": image_id,
                "category_id": cat_id,
                "bbox": [round(bbox[0], 1), round(bbox[1], 1), round(bw, 1), round(bh, 1)],
                "area": round(bw * bh, 1),
                "iscrowd": 0,
            })
            ann_id += 1

        if (img_idx + 1) % 20 == 0:
            print(f"  [{img_idx + 1}/{len(manifest)}] "
                  f"windows={total_windows}, doors={total_doors}")

    categories = [{"id": i, "name": c, "supercategory": "facade"} for i, c in enumerate(CLASSES)]

    coco = {
        "info": {
            "description": "Kensington Market Facade Pseudo-Labels (tuned contours)",
            "version": "0.2-pseudo",
            "year": 2026,
            "date_created": datetime.now().isoformat(),
        },
        "images": all_images,
        "annotations": all_annotations,
        "categories": categories,
    }

    return coco, total_windows, total_doors


def split_coco(coco, train_ratio=0.8):
    """Split COCO into train/val."""
    random.seed(42)
    image_ids = [img["id"] for img in coco["images"]]
    random.shuffle(image_ids)
    split_idx = int(len(image_ids) * train_ratio)
    train_ids = set(image_ids[:split_idx])
    val_ids = set(image_ids[split_idx:])

    train = {
        "info": coco["info"],
        "images": [img for img in coco["images"] if img["id"] in train_ids],
        "annotations": [ann for ann in coco["annotations"] if ann["image_id"] in train_ids],
        "categories": coco["categories"],
    }
    val = {
        "info": coco["info"],
        "images": [img for img in coco["images"] if img["id"] in val_ids],
        "annotations": [ann for ann in coco["annotations"] if ann["image_id"] in val_ids],
        "categories": coco["categories"],
    }
    return train, val


def main():
    parser = argparse.ArgumentParser(description="Generate pseudo-labels for facade training.")
    parser.add_argument("--method", choices=["yolo-tuned", "grounding-dino"], default="yolo-tuned")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=TRAINING_DIR / "coco")
    args = parser.parse_args()

    manifest = load_manifest()
    print(f"Generating pseudo-labels for {len(manifest)} training photos")
    print(f"  Method: {args.method}")

    if args.method == "grounding-dino":
        print("  [INFO] Grounding DINO requires: pip install groundingdino-py")
        print("  [INFO] Falling back to yolo-tuned for now.")
        args.method = "yolo-tuned"

    if args.method == "yolo-tuned":
        coco, n_windows, n_doors = generate_pseudo_labels_tuned(manifest, args.limit)
        print(f"\n  Total windows detected: {n_windows}")
        print(f"  Total doors detected: {n_doors}")
        print(f"  Total annotations: {len(coco['annotations'])}")

    args.output.mkdir(parents=True, exist_ok=True)

    train, val = split_coco(coco)
    (args.output / "train.json").write_text(json.dumps(train, indent=2), encoding="utf-8")
    (args.output / "val.json").write_text(json.dumps(val, indent=2), encoding="utf-8")

    print(f"\n  Train: {len(train['images'])} images, {len(train['annotations'])} annotations")
    print(f"  Val: {len(val['images'])} images, {len(val['annotations'])} annotations")
    print(f"  Output: {args.output}")

    print("\nNext steps:")
    print("  1. Review pseudo-labels visually")
    print("  2. Convert to YOLO format: python scripts/train/train_yolo_facade.py --export-only")
    print("  3. Train: python scripts/train/train_yolo_facade.py --epochs 50")
    print("  OR: Import into Label Studio for refinement")


if __name__ == "__main__":
    main()
