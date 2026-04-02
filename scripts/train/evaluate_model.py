#!/usr/bin/env python3
"""Evaluate facade segmentation model using FiftyOne.

Loads predictions from a trained YOLO model, compares against ground
truth COCO annotations, and computes mAP, per-class AP, confusion matrix.
Launches FiftyOne app for visual inspection.

Usage:
    python scripts/train/evaluate_model.py --model data/training/runs/facade_seg/weights/best.pt
    python scripts/train/evaluate_model.py --model data/training/runs/facade_seg/weights/best.pt --launch
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"


def load_coco_dataset(coco_path, images_dir, name="kensington_facades"):
    """Load COCO dataset into FiftyOne."""
    import fiftyone as fo

    dataset = fo.Dataset.from_dir(
        dataset_type=fo.types.COCODetectionDataset,
        data_path=str(images_dir),
        labels_path=str(coco_path),
        name=name,
        overwrite=True,
    )
    print(f"  Loaded {len(dataset)} samples into FiftyOne")
    return dataset


def add_predictions(dataset, model_path, conf_threshold=0.25):
    """Run YOLO model and add predictions to FiftyOne dataset."""
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    print(f"  Model: {model_path}")

    for sample in dataset:
        img_path = sample.filepath
        results = model(img_path, conf=conf_threshold, verbose=False)

        if not results:
            continue

        detections = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # FiftyOne uses relative coordinates [0, 1]
                img_w = result.orig_shape[1]
                img_h = result.orig_shape[0]

                import fiftyone as fo
                detections.append(fo.Detection(
                    label=model.names[cls_id],
                    bounding_box=[
                        x1 / img_w,
                        y1 / img_h,
                        (x2 - x1) / img_w,
                        (y2 - y1) / img_h,
                    ],
                    confidence=conf,
                ))

        import fiftyone as fo
        sample["predictions"] = fo.Detections(detections=detections)
        sample.save()

    print(f"  Added predictions to {len(dataset)} samples")


def evaluate(dataset, gt_field="ground_truth", pred_field="predictions"):
    """Compute detection metrics."""
    import fiftyone as fo

    results = dataset.evaluate_detections(
        pred_field,
        gt_field=gt_field,
        eval_key="eval",
        compute_mAP=True,
    )

    print(f"\n  mAP@0.5: {results.mAP():.4f}")

    # Per-class AP
    print("\n  Per-class AP:")
    classes = results.classes
    for cls in sorted(classes):
        ap = results.mAP(classes=[cls])
        print(f"    {cls:<20s} {ap:.4f}")

    return results


def export_report(results, output_path):
    """Export evaluation results to JSON."""
    report = {
        "mAP_50": round(results.mAP(), 4),
        "per_class_ap": {},
    }
    for cls in sorted(results.classes):
        report["per_class_ap"][cls] = round(results.mAP(classes=[cls]), 4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n  Report: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate facade segmentation model.")
    parser.add_argument("--model", type=Path,
                        default=TRAINING_DIR / "runs" / "facade_seg" / "weights" / "best.pt")
    parser.add_argument("--coco", type=Path, default=TRAINING_DIR / "coco" / "val.json")
    parser.add_argument("--images", type=Path, default=TRAINING_DIR / "images")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--launch", action="store_true", help="Launch FiftyOne app")
    parser.add_argument("--output", type=Path, default=TRAINING_DIR / "eval_report.json")
    args = parser.parse_args()

    if not args.model.exists():
        print(f"ERROR: Model not found: {args.model}")
        print("  Train first: python scripts/train/train_yolo_facade.py")
        return

    if not args.coco.exists():
        print(f"ERROR: Validation COCO not found: {args.coco}")
        print("  Export first: python scripts/train/export_coco.py --split")
        return

    print("Facade segmentation evaluation")
    dataset = load_coco_dataset(args.coco, args.images)
    add_predictions(dataset, args.model, args.conf)
    results = evaluate(dataset)
    export_report(results, args.output)

    if args.launch:
        import fiftyone as fo
        session = fo.launch_app(dataset)
        print("\n  FiftyOne app launched. Press Ctrl+C to exit.")
        session.wait()


if __name__ == "__main__":
    main()
