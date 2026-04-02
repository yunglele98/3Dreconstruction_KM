#!/usr/bin/env python3
"""Convert Label Studio annotations to COCO instance segmentation format.

Reads Label Studio JSON export and produces COCO-format annotations
compatible with YOLOv11 and other detection frameworks.

Usage:
    python scripts/train/export_coco.py --input data/training/annotations.json
    python scripts/train/export_coco.py --input data/training/annotations.json --output data/training/coco/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"

CLASSES_PATH = TRAINING_DIR / "classes.txt"

DEFAULT_CLASSES = [
    "wall", "window", "door", "roof", "balcony", "shop", "cornice",
    "pilaster", "column", "molding", "sill", "lintel", "arch",
    "shutter", "awning", "sign", "chimney", "bay_window", "porch",
    "foundation", "gutter", "downspout", "fire_escape",
]


def load_classes():
    if CLASSES_PATH.exists():
        return [l.strip() for l in CLASSES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    return DEFAULT_CLASSES


def label_studio_to_coco(ls_data, classes):
    """Convert Label Studio export JSON to COCO format."""
    class_to_id = {c: i for i, c in enumerate(classes)}

    images = []
    annotations = []
    ann_id = 1

    for task_idx, task in enumerate(ls_data):
        # Image info
        data = task.get("data", {})
        image_path = data.get("image", "")
        filename = image_path.split("/")[-1] if "/" in image_path else image_path

        # Get image dimensions from first annotation
        img_width = 1920
        img_height = 1080
        for ann in task.get("annotations", []):
            for result in ann.get("result", []):
                ow = result.get("original_width")
                oh = result.get("original_height")
                if ow and oh:
                    img_width = ow
                    img_height = oh
                    break

        image_id = task_idx + 1
        images.append({
            "id": image_id,
            "file_name": filename,
            "width": img_width,
            "height": img_height,
        })

        # Annotations
        for ann in task.get("annotations", []):
            for result in ann.get("result", []):
                rtype = result.get("type", "")
                value = result.get("value", {})

                labels = (value.get("labels")
                          or value.get("rectanglelabels")
                          or value.get("polygonlabels")
                          or [])
                if not labels:
                    continue
                label = labels[0]
                cat_id = class_to_id.get(label.lower())
                if cat_id is None:
                    continue

                if rtype in ("rectanglelabels", "rectangle"):
                    # Bounding box (Label Studio uses % coordinates)
                    x_pct = value.get("x", 0)
                    y_pct = value.get("y", 0)
                    w_pct = value.get("width", 0)
                    h_pct = value.get("height", 0)

                    x = x_pct / 100 * img_width
                    y = y_pct / 100 * img_height
                    w = w_pct / 100 * img_width
                    h = h_pct / 100 * img_height

                    annotations.append({
                        "id": ann_id,
                        "image_id": image_id,
                        "category_id": cat_id,
                        "bbox": [round(x, 1), round(y, 1), round(w, 1), round(h, 1)],
                        "area": round(w * h, 1),
                        "iscrowd": 0,
                    })
                    ann_id += 1

                elif rtype in ("polygonlabels", "polygon"):
                    # Polygon segmentation
                    points = value.get("points", [])
                    if not points:
                        continue

                    seg_x = [p[0] / 100 * img_width for p in points]
                    seg_y = [p[1] / 100 * img_height for p in points]

                    x_min, x_max = min(seg_x), max(seg_x)
                    y_min, y_max = min(seg_y), max(seg_y)
                    w = x_max - x_min
                    h = y_max - y_min

                    segmentation = []
                    for px, py in zip(seg_x, seg_y):
                        segmentation.extend([round(px, 1), round(py, 1)])

                    annotations.append({
                        "id": ann_id,
                        "image_id": image_id,
                        "category_id": cat_id,
                        "bbox": [round(x_min, 1), round(y_min, 1), round(w, 1), round(h, 1)],
                        "segmentation": [segmentation],
                        "area": round(w * h, 1),
                        "iscrowd": 0,
                    })
                    ann_id += 1

    categories = [{"id": i, "name": c, "supercategory": "facade"} for i, c in enumerate(classes)]

    return {
        "info": {
            "description": "Kensington Market Facade Segmentation",
            "version": "1.0",
            "year": 2026,
            "date_created": datetime.now().isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }


def split_dataset(coco, train_ratio=0.8):
    """Split COCO dataset into train/val."""
    import random
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
    parser = argparse.ArgumentParser(description="Convert Label Studio to COCO format.")
    parser.add_argument("--input", type=Path, default=TRAINING_DIR / "annotations.json")
    parser.add_argument("--output", type=Path, default=TRAINING_DIR / "coco")
    parser.add_argument("--split", action="store_true", help="Split into train/val (80/20)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Annotations file not found: {args.input}")
        print("  Export from Label Studio first, or annotate photos.")
        return

    print(f"Converting Label Studio -> COCO: {args.input}")
    ls_data = json.loads(args.input.read_text(encoding="utf-8"))
    classes = load_classes()

    coco = label_studio_to_coco(ls_data, classes)

    args.output.mkdir(parents=True, exist_ok=True)

    if args.split:
        train, val = split_dataset(coco)
        (args.output / "train.json").write_text(json.dumps(train, indent=2), encoding="utf-8")
        (args.output / "val.json").write_text(json.dumps(val, indent=2), encoding="utf-8")
        print(f"  Train: {len(train['images'])} images, {len(train['annotations'])} annotations")
        print(f"  Val: {len(val['images'])} images, {len(val['annotations'])} annotations")
    else:
        (args.output / "annotations.json").write_text(json.dumps(coco, indent=2), encoding="utf-8")
        print(f"  {len(coco['images'])} images, {len(coco['annotations'])} annotations")

    print(f"  Categories: {len(classes)}")
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
