"""
extract_depth.py

Extract monocular depth maps from field photos using Depth Anything v2 Small.
Outputs float32 .npy arrays and plasma-colourmap PNG visualizations.

Usage:
    python scripts/sense/extract_depth.py [--limit N] [--input-dir PATH] [--output-dir PATH]
"""

import argparse
import sys
from pathlib import Path

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract monocular depth maps using Depth Anything v2 Small."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("PHOTOS KENSINGTON sorted"),
        help="Root directory containing <street>/*.jpg photos.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("depth_maps"),
        help="Directory to write .npy and _viz.png outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after processing N photos (useful for testing).",
    )
    return parser.parse_args()


def load_pipeline():
    """Load Depth Anything v2 Small via the transformers depth-estimation pipeline."""
    try:
        from transformers import pipeline as hf_pipeline
    except ImportError:
        print("ERROR: transformers is not installed. Run: pip install transformers torch torchvision")
        sys.exit(1)

    model_id = "depth-anything/Depth-Anything-V2-Small-hf"
    print(f"Loading model: {model_id}")

    try:
        import torch
        device = 0 if torch.cuda.is_available() else -1
        device_label = "GPU 0" if device == 0 else "CPU"
        print(f"Using device: {device_label}")
    except ImportError:
        device = -1
        print("torch not found, falling back to CPU")

    pipe = hf_pipeline(
        task="depth-estimation",
        model=model_id,
        device=device,
    )
    print("Model loaded.")
    return pipe


def collect_photos(input_dir: Path) -> list:
    """Collect all .jpg / .JPG files recursively under input_dir, sorted."""
    photos = sorted(input_dir.rglob("*.jpg")) + sorted(input_dir.rglob("*.JPG"))
    # Deduplicate (case-insensitive filesystems may return both)
    seen = set()
    unique = []
    for p in sorted(photos):
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def save_outputs(depth_array: np.ndarray, stem: str, output_dir: Path):
    """Write float32 .npy and plasma-colourmap _viz.png for one depth map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    depth_f32 = depth_array.astype(np.float32)

    # --- numpy array ---
    npy_path = output_dir / f"{stem}.npy"
    np.save(npy_path, depth_f32)

    # --- visualization ---
    viz_path = output_dir / f"{stem}_viz.png"

    d_min = float(depth_f32.min())
    d_max = float(depth_f32.max())
    if d_max > d_min:
        normalized = (depth_f32 - d_min) / (d_max - d_min)
    else:
        normalized = np.zeros_like(depth_f32)

    h, w = normalized.shape
    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    ax.imshow(normalized, cmap="plasma")
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(viz_path, dpi=100, bbox_inches="tight", pad_inches=0)
    plt.close(fig)

    return npy_path, viz_path


def main():
    args = parse_args()

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir
    limit = args.limit

    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir.resolve()}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    photos = collect_photos(input_dir)
    if not photos:
        print(f"No .jpg files found under: {input_dir.resolve()}")
        sys.exit(0)

    total_available = len(photos)
    if limit is not None:
        photos = photos[:limit]

    already_done = sum(1 for p in photos if (output_dir / f"{p.stem}.npy").exists())
    print(f"Photos found   : {total_available}")
    print(f"To process     : {len(photos)}" + (f" (--limit {limit})" if limit else ""))
    print(f"Already done   : {already_done} (will skip)")

    pipe = load_pipeline()

    from PIL import Image

    processed = 0
    skipped = 0
    errors = 0

    for i, photo_path in enumerate(photos):
        stem = photo_path.stem
        npy_path = output_dir / f"{stem}.npy"

        if npy_path.exists():
            skipped += 1
            total_done = processed + skipped
            if total_done % 50 == 0:
                pct = 100.0 * total_done / len(photos)
                print(f"  Progress: {total_done}/{len(photos)} ({pct:.1f}%) -- processed {processed}, skipped {skipped}, errors {errors}")
            continue

        try:
            image = Image.open(photo_path).convert("RGB")
            result = pipe(image)
            depth = result["depth"]  # PIL Image or ndarray depending on transformers version

            depth_array = np.array(depth, dtype=np.float32)
            save_outputs(depth_array, stem, output_dir)
            processed += 1

        except Exception as exc:
            errors += 1
            print(f"  ERROR [{photo_path.name}]: {exc}")
            continue

        total_done = processed + skipped
        if total_done % 50 == 0 and total_done > 0:
            pct = 100.0 * total_done / len(photos)
            print(f"  Progress: {total_done}/{len(photos)} ({pct:.1f}%) -- processed {processed}, skipped {skipped}, errors {errors}")

    print()
    print("Done.")
    print(f"  Processed : {processed}")
    print(f"  Skipped   : {skipped}")
    print(f"  Errors    : {errors}")
    print(f"  Output dir: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
