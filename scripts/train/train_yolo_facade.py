#!/usr/bin/env python3
"""Fine-tune YOLOv11 on Kensington Market facade segmentation data.

Converts COCO annotations to YOLO format and runs training with
ultralytics. Supports instance segmentation and detection modes.

Usage:
    python scripts/train/train_yolo_facade.py --data data/training/coco/ --epochs 50
    python scripts/train/train_yolo_facade.py --data data/training/coco/ --epochs 100 --model yolo11m-seg
    python scripts/train/train_yolo_facade.py --export-only  # convert COCO to YOLO format
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"
YOLO_DIR = TRAINING_DIR / "yolo"

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


def coco_to_yolo(coco_dir, yolo_dir, image_dir):
    """Convert COCO annotations to YOLO format."""
    classes = load_classes()
    yolo_dir.mkdir(parents=True, exist_ok=True)

    for split in ["train", "val"]:
        coco_path = coco_dir / f"{split}.json"
        if not coco_path.exists():
            # Try single annotations file
            coco_path = coco_dir / "annotations.json"
            if not coco_path.exists():
                continue

        coco = json.loads(coco_path.read_text(encoding="utf-8"))

        # Create YOLO split directories
        img_split_dir = yolo_dir / "images" / split
        lbl_split_dir = yolo_dir / "labels" / split
        img_split_dir.mkdir(parents=True, exist_ok=True)
        lbl_split_dir.mkdir(parents=True, exist_ok=True)

        # Index annotations by image_id
        anns_by_image = {}
        for ann in coco.get("annotations", []):
            img_id = ann["image_id"]
            if img_id not in anns_by_image:
                anns_by_image[img_id] = []
            anns_by_image[img_id].append(ann)

        converted = 0
        for img_info in coco.get("images", []):
            img_id = img_info["id"]
            filename = img_info["file_name"]
            w = img_info["width"]
            h = img_info["height"]

            # Copy/symlink image
            src_img = image_dir / filename
            dst_img = img_split_dir / filename
            if src_img.exists() and not dst_img.exists():
                shutil.copy2(src_img, dst_img)

            # Convert annotations
            anns = anns_by_image.get(img_id, [])
            label_path = lbl_split_dir / Path(filename).with_suffix(".txt").name
            lines = []
            for ann in anns:
                cat_id = ann["category_id"]
                bbox = ann["bbox"]  # [x, y, w, h] in pixels

                # YOLO format: class cx cy w h (normalized 0-1)
                cx = (bbox[0] + bbox[2] / 2) / w
                cy = (bbox[1] + bbox[3] / 2) / h
                bw = bbox[2] / w
                bh = bbox[3] / h

                # Segmentation (if available)
                seg = ann.get("segmentation")
                if seg and isinstance(seg, list) and len(seg) > 0:
                    # YOLO seg format: class x1 y1 x2 y2 ... (normalized)
                    points = seg[0]
                    norm_points = []
                    for k in range(0, len(points), 2):
                        norm_points.append(f"{points[k] / w:.6f}")
                        norm_points.append(f"{points[k + 1] / h:.6f}")
                    lines.append(f"{cat_id} " + " ".join(norm_points))
                else:
                    lines.append(f"{cat_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            label_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
            converted += 1

        print(f"  {split}: {converted} images converted")

    # Write data.yaml
    yaml_content = f"""# Kensington Market Facade Segmentation
path: {yolo_dir.resolve()}
train: images/train
val: images/val

nc: {len(classes)}
names: {classes}
"""
    yaml_path = yolo_dir / "data.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    print(f"  YOLO config: {yaml_path}")
    return yaml_path


def train(yaml_path, model_name="yolo11n-seg", epochs=50, imgsz=640, batch=8):
    """Train YOLOv11 on facade data."""
    from ultralytics import YOLO

    print(f"\nTraining {model_name} for {epochs} epochs...")
    model = YOLO(f"{model_name}.pt")

    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        project=str(TRAINING_DIR / "runs"),
        name="facade_seg",
        exist_ok=True,
        patience=20,
        save=True,
        plots=True,
    )

    print(f"\nTraining complete.")
    print(f"  Best model: {TRAINING_DIR / 'runs' / 'facade_seg' / 'weights' / 'best.pt'}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Fine-tune YOLOv11 on facade data.")
    parser.add_argument("--data", type=Path, default=TRAINING_DIR / "coco")
    parser.add_argument("--images", type=Path, default=TRAINING_DIR / "images")
    parser.add_argument("--model", type=str, default="yolo11n-seg",
                        help="Model variant (yolo11n-seg, yolo11m-seg, yolo11l-seg)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--export-only", action="store_true", help="Only convert COCO to YOLO")
    args = parser.parse_args()

    if not args.data.exists():
        print(f"ERROR: COCO data not found at {args.data}")
        print("  Run: python scripts/train/export_coco.py --split")
        return

    yaml_path = coco_to_yolo(args.data, YOLO_DIR, args.images)

    if args.export_only:
        print("YOLO format exported. Run without --export-only to train.")
        return

    train(yaml_path, args.model, args.epochs, args.imgsz, args.batch)


if __name__ == "__main__":
    main()
