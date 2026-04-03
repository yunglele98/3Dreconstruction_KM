#!/usr/bin/env python3
"""Bootstrap pseudo-annotations from existing contour detections.

Reads segmentation JSON outputs (produced by segment_facades.py) for
the 200 training photos and converts them into Label Studio pre-annotation
format. This gives annotators a head start -- they refine rather than
draw from scratch.

Also generates direct COCO annotations for immediate YOLO training
(useful even without manual refinement).

Usage:
    python scripts/train/bootstrap_annotations.py
    python scripts/train/bootstrap_annotations.py --output data/training/coco/ --format coco
    python scripts/train/bootstrap_annotations.py --output data/training/preannotations.json --format label-studio
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"
SEG_DIR = REPO_ROOT / "segmentation"
IMAGES_DIR = TRAINING_DIR / "images"
MANIFEST_PATH = TRAINING_DIR / "manifest.json"

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


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def get_image_size(image_path):
    """Get image width, height."""
    try:
        with Image.open(image_path) as img:
            return img.size  # (width, height)
    except Exception:
        return (4000, 3000)  # fallback for 12MP photos


def load_seg_for_photo(photo_stem):
    """Load segmentation results for a training photo."""
    seg_path = SEG_DIR / f"{photo_stem}_elements.json"
    if seg_path.exists():
        try:
            return json.loads(seg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def to_label_studio_preannotations(manifest, classes):
    """Convert contour detections to Label Studio pre-annotation format."""
    tasks = []

    for entry in manifest:
        image_rel = entry.get("image", "")
        filename = Path(image_rel).name
        stem = Path(filename).stem
        address = entry.get("address", "")

        seg = load_seg_for_photo(stem)
        if not seg:
            # Still include the task, just no pre-annotations
            tasks.append({
                "data": {
                    "image": f"/data/local-files/?d={image_rel}",
                    "address": address,
                },
            })
            continue

        # Get actual image dimensions
        img_path = IMAGES_DIR / filename
        w, h = get_image_size(img_path)

        # Build Label Studio result format
        results = []
        elements = seg.get("elements", [])
        for el in elements:
            cls = el.get("class", "")
            if cls not in classes:
                continue
            bbox = el.get("bbox", [0, 0, 0, 0])
            x1, y1, x2, y2 = bbox

            # Label Studio uses percentage coordinates
            x_pct = (x1 / w) * 100
            y_pct = (y1 / h) * 100
            w_pct = ((x2 - x1) / w) * 100
            h_pct = ((y2 - y1) / h) * 100

            result_id = str(uuid.uuid4())[:8]
            results.append({
                "id": result_id,
                "type": "rectanglelabels",
                "from_name": "label",
                "to_name": "image",
                "original_width": w,
                "original_height": h,
                "value": {
                    "x": round(x_pct, 2),
                    "y": round(y_pct, 2),
                    "width": round(w_pct, 2),
                    "height": round(h_pct, 2),
                    "rotation": 0,
                    "rectanglelabels": [cls],
                },
            })

        task = {
            "data": {
                "image": f"/data/local-files/?d={image_rel}",
                "address": address,
            },
        }

        if results:
            task["predictions"] = [{
                "model_version": "contour_v1",
                "score": 0.70,
                "result": results,
            }]

        tasks.append(task)

    return tasks


def to_coco(manifest, classes):
    """Convert contour detections to COCO format for direct YOLO training."""
    class_to_id = {c: i for i, c in enumerate(classes)}

    images = []
    annotations = []
    ann_id = 1

    for img_idx, entry in enumerate(manifest):
        image_rel = entry.get("image", "")
        filename = Path(image_rel).name
        stem = Path(filename).stem

        img_path = IMAGES_DIR / filename
        w, h = get_image_size(img_path)

        image_id = img_idx + 1
        images.append({
            "id": image_id,
            "file_name": filename,
            "width": w,
            "height": h,
        })

        seg = load_seg_for_photo(stem)
        if not seg:
            continue

        elements = seg.get("elements", [])
        for el in elements:
            cls = el.get("class", "")
            cat_id = class_to_id.get(cls)
            if cat_id is None:
                continue

            bbox = el.get("bbox", [0, 0, 0, 0])
            x1, y1, x2, y2 = bbox
            bw = x2 - x1
            bh = y2 - y1

            if bw <= 0 or bh <= 0:
                continue

            annotations.append({
                "id": ann_id,
                "image_id": image_id,
                "category_id": cat_id,
                "bbox": [round(x1, 1), round(y1, 1), round(bw, 1), round(bh, 1)],
                "area": round(bw * bh, 1),
                "iscrowd": 0,
            })
            ann_id += 1

    categories = [{"id": i, "name": c, "supercategory": "facade"} for i, c in enumerate(classes)]

    return {
        "info": {
            "description": "Kensington Market Facade Segmentation (bootstrapped from contours)",
            "version": "0.1-bootstrap",
            "year": 2026,
            "date_created": datetime.now().isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }


def split_coco(coco, train_ratio=0.8):
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
    parser = argparse.ArgumentParser(description="Bootstrap annotations from contour detections.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--format", choices=["label-studio", "coco", "both"], default="both")
    parser.add_argument("--split", action="store_true", default=True,
                        help="Split COCO into train/val (80/20)")
    args = parser.parse_args()

    manifest = load_manifest()
    classes = load_classes()

    print(f"Bootstrapping annotations for {len(manifest)} training photos")
    print(f"  Classes: {len(classes)}")
    print(f"  Segmentation dir: {SEG_DIR}")

    # Count how many have segmentation
    seg_count = 0
    total_elements = 0
    for entry in manifest:
        stem = Path(entry.get("image", "")).stem
        seg = load_seg_for_photo(stem)
        if seg:
            seg_count += 1
            total_elements += len(seg.get("elements", []))

    print(f"  Photos with segmentation: {seg_count}/{len(manifest)}")
    print(f"  Total elements to bootstrap: {total_elements}")

    if args.format in ("label-studio", "both"):
        ls_output = args.output or (TRAINING_DIR / "preannotations.json")
        tasks = to_label_studio_preannotations(manifest, classes)

        annotated = sum(1 for t in tasks if t.get("predictions"))
        ls_output.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\n  Label Studio pre-annotations: {ls_output}")
        print(f"    Tasks: {len(tasks)} ({annotated} with pre-annotations)")

    if args.format in ("coco", "both"):
        coco_dir = args.output if (args.output and args.format == "coco") else (TRAINING_DIR / "coco")
        coco_dir.mkdir(parents=True, exist_ok=True)

        coco = to_coco(manifest, classes)
        print(f"\n  COCO annotations: {coco_dir}")
        print(f"    Images: {len(coco['images'])}")
        print(f"    Annotations: {len(coco['annotations'])}")

        if args.split:
            train, val = split_coco(coco)
            (coco_dir / "train.json").write_text(
                json.dumps(train, indent=2), encoding="utf-8"
            )
            (coco_dir / "val.json").write_text(
                json.dumps(val, indent=2), encoding="utf-8"
            )
            print(f"    Train: {len(train['images'])} images, {len(train['annotations'])} annotations")
            print(f"    Val: {len(val['images'])} images, {len(val['annotations'])} annotations")
        else:
            (coco_dir / "annotations.json").write_text(
                json.dumps(coco, indent=2), encoding="utf-8"
            )

    print("\nDone. Next steps:")
    print("  1. Import preannotations.json into Label Studio for refinement")
    print("  2. Or train directly on bootstrapped COCO data:")
    print("     python scripts/train/train_yolo_facade.py --data data/training/coco/ --epochs 50")


if __name__ == "__main__":
    main()
