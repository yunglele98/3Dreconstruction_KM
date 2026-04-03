#!/usr/bin/env python3
"""Orchestrate the full custom YOLO training pipeline for Kensington facades.

End-to-end pipeline:
  1. Bootstrap pseudo-annotations from contour detections
  2. Convert to YOLO format (COCO -> YOLO)
  3. Fine-tune YOLOv11 on Kensington facade data
  4. Evaluate with FiftyOne metrics
  5. Re-run segment_facades.py with custom weights
  6. Re-fuse segmentation into params

Usage:
    python scripts/train/run_training_pipeline.py
    python scripts/train/run_training_pipeline.py --skip-train  # just bootstrap + convert
    python scripts/train/run_training_pipeline.py --epochs 100 --model yolo11s-seg
    python scripts/train/run_training_pipeline.py --weights data/training/runs/facade_seg/weights/best.pt --resegment-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRAINING_DIR = REPO_ROOT / "data" / "training"
BEST_WEIGHTS = TRAINING_DIR / "runs" / "facade_seg" / "weights" / "best.pt"


def run_step(description, cmd, cwd=None):
    """Run a pipeline step with clear logging."""
    print(f"\n{'='*60}")
    print(f"  STEP: {description}")
    print(f"  CMD:  {' '.join(str(c) for c in cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        [sys.executable] + [str(c) for c in cmd],
        cwd=str(cwd or REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"\n[ERROR] Step failed: {description}")
        print(f"  Exit code: {result.returncode}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Run full YOLO training pipeline.")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--model", type=str, default="yolo11s-seg",
                        help="YOLO model variant")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--skip-train", action="store_true",
                        help="Skip training, only bootstrap + convert")
    parser.add_argument("--skip-bootstrap", action="store_true",
                        help="Skip bootstrapping (use existing COCO data)")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Skip FiftyOne evaluation")
    parser.add_argument("--resegment-only", action="store_true",
                        help="Only re-run segmentation + fusion with existing weights")
    parser.add_argument("--weights", type=Path, default=None,
                        help="Path to trained weights (for --resegment-only)")
    args = parser.parse_args()

    weights = args.weights or BEST_WEIGHTS

    print("Kensington Market Custom YOLO Training Pipeline")
    print(f"  Model: {args.model}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Batch: {args.batch}")
    print(f"  Image size: {args.imgsz}")

    if args.resegment_only:
        if not weights.exists():
            print(f"\n[ERROR] Weights not found: {weights}")
            print("  Train first, or specify --weights path.")
            sys.exit(1)

        # Step 5: Re-run segmentation with custom weights
        ok = run_step(
            "Re-run facade segmentation with custom YOLO weights",
            ["scripts/sense/segment_facades.py",
             "--custom-weights", str(weights),
             "--annotate"],
        )
        if not ok:
            sys.exit(1)

        # Step 6: Re-fuse into params
        ok = run_step(
            "Re-fuse segmentation into building params",
            ["scripts/enrich/fuse_segmentation.py", "--force"],
        )
        if not ok:
            sys.exit(1)

        print("\n" + "="*60)
        print("  PIPELINE COMPLETE (resegment-only)")
        print("="*60)
        return

    # Step 1: Bootstrap pseudo-annotations
    if not args.skip_bootstrap:
        ok = run_step(
            "Bootstrap pseudo-annotations from contour detections",
            ["scripts/train/bootstrap_annotations.py", "--format", "both"],
        )
        if not ok:
            sys.exit(1)

    # Step 2: Convert COCO -> YOLO format
    coco_dir = TRAINING_DIR / "coco"
    if not coco_dir.exists():
        print(f"\n[ERROR] COCO data not found at {coco_dir}")
        print("  Run bootstrap step first.")
        sys.exit(1)

    ok = run_step(
        "Convert COCO annotations to YOLO format",
        ["scripts/train/train_yolo_facade.py",
         "--data", str(coco_dir),
         "--export-only"],
    )
    if not ok:
        sys.exit(1)

    if args.skip_train:
        print("\n  Training skipped (--skip-train). Data is ready for training.")
        print(f"  YOLO config: {TRAINING_DIR / 'yolo' / 'data.yaml'}")
        print(f"  Manual train: yolo train model={args.model}.pt data={TRAINING_DIR / 'yolo' / 'data.yaml'} epochs={args.epochs}")
        return

    # Step 3: Train YOLOv11
    ok = run_step(
        f"Fine-tune {args.model} for {args.epochs} epochs",
        ["scripts/train/train_yolo_facade.py",
         "--data", str(coco_dir),
         "--model", args.model,
         "--epochs", str(args.epochs),
         "--batch", str(args.batch),
         "--imgsz", str(args.imgsz)],
    )
    if not ok:
        print("\n[WARN] Training failed. Check GPU/CUDA availability.")
        print("  Manual train: yolo train model=yolo11s.pt data=data/training/yolo/data.yaml epochs=50")
        sys.exit(1)

    # Step 4: Evaluate with FiftyOne
    if not args.skip_eval:
        if BEST_WEIGHTS.exists():
            ok = run_step(
                "Evaluate model with FiftyOne",
                ["scripts/train/evaluate_model.py",
                 "--model", str(BEST_WEIGHTS)],
            )
            if not ok:
                print("[WARN] Evaluation failed (FiftyOne may not be installed).")
        else:
            print(f"\n[WARN] Trained weights not found at {BEST_WEIGHTS}")
            print("  Skipping evaluation.")

    # Step 5: Re-run segmentation with custom weights
    if BEST_WEIGHTS.exists():
        ok = run_step(
            "Re-run facade segmentation with custom YOLO weights",
            ["scripts/sense/segment_facades.py",
             "--custom-weights", str(BEST_WEIGHTS),
             "--annotate"],
        )
        if not ok:
            print("[WARN] Re-segmentation failed.")

        # Step 6: Re-fuse into params
        ok = run_step(
            "Re-fuse segmentation into building params",
            ["scripts/enrich/fuse_segmentation.py", "--force"],
        )
        if not ok:
            print("[WARN] Re-fusion failed.")
    else:
        print(f"\n[WARN] No trained weights found. Skipping re-segmentation.")

    print("\n" + "="*60)
    print("  PIPELINE COMPLETE")
    print("="*60)
    print(f"\n  Weights: {BEST_WEIGHTS}")
    print(f"  Eval report: {TRAINING_DIR / 'eval_report.json'}")
    print(f"  Segmentation: segmentation/")
    print(f"  Params: params/")


if __name__ == "__main__":
    main()
