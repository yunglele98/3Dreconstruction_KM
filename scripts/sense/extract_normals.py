#!/usr/bin/env python3
"""Extract surface normal maps from field photos using DSINE.

Outputs float32 .npy arrays (H x W x 3) and visualization PNGs.
Normal maps help estimate facade orientation and depth discontinuities.

Usage:
    python scripts/sense/extract_normals.py [--limit N]
    python scripts/sense/extract_normals.py --input-dir "PHOTOS KENSINGTON sorted" --output-dir normals/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract surface normal maps using DSINE or omnidata."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=REPO_ROOT / "PHOTOS KENSINGTON sorted",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "normals",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--model",
        default="dsine",
        choices=["dsine", "omnidata"],
        help="Normal estimation model (default: dsine).",
    )
    return parser.parse_args()


def load_model(model_name):
    """Load normal estimation model."""
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if model_name == "dsine":
        try:
            from transformers import pipeline as hf_pipeline
            pipe = hf_pipeline("image-to-image", model="baai/dsine-normal-nyu", device=device)
            print(f"Loaded DSINE on {device}")
            return pipe, device, "dsine_hf"
        except Exception:
            pass

        # Fallback: try loading DSINE directly
        try:
            from dsine import DSINE
            model = DSINE.from_pretrained().to(device).eval()
            print(f"Loaded DSINE (direct) on {device}")
            return model, device, "dsine_direct"
        except ImportError:
            pass

    if model_name == "omnidata":
        try:
            from transformers import pipeline as hf_pipeline
            pipe = hf_pipeline("image-to-image", model="EPFL-VILAB/omnidata-normal", device=device)
            print(f"Loaded Omnidata normals on {device}")
            return pipe, device, "omnidata"
        except Exception:
            pass

    print(f"ERROR: Could not load {model_name} model.")
    print("  pip install transformers torch torchvision")
    sys.exit(1)


def predict_normals(image_path, model, device, model_type):
    """Predict surface normals for a single image."""
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Resize for speed
    max_side = 512
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    if model_type == "dsine_hf" or model_type == "omnidata":
        result = model(img)
        normal_img = result if isinstance(result, Image.Image) else result[0]
        normals = np.array(normal_img).astype(np.float32) / 127.5 - 1.0
    elif model_type == "dsine_direct":
        import torch
        from torchvision import transforms
        transform = transforms.Compose([
            transforms.Resize((384, 384)),
            transforms.ToTensor(),
        ])
        tensor = transform(img).unsqueeze(0).to(device)
        with torch.no_grad():
            normals = model(tensor)[0].permute(1, 2, 0).cpu().numpy()
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    return normals


def save_normals(output_dir, stem, normals):
    """Save normal map as .npy and visualization PNG."""
    npy_path = output_dir / f"{stem}.npy"
    np.save(str(npy_path), normals)

    # Visualization: map [-1,1] to [0,255]
    viz = ((normals + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
    from PIL import Image
    viz_path = output_dir / f"{stem}_viz.png"
    Image.fromarray(viz).save(str(viz_path))

    return npy_path


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.input_dir.exists():
        print(f"ERROR: Input directory not found: {args.input_dir}")
        sys.exit(1)

    photos = sorted(args.input_dir.rglob("*.jpg")) + sorted(args.input_dir.rglob("*.JPG"))
    if args.limit:
        photos = photos[: args.limit]

    print(f"Normal extraction ({args.model}): {len(photos)} photos")

    model, device, model_type = load_model(args.model)
    processed = 0
    skipped = 0
    errors = 0
    start = time.time()

    for i, photo in enumerate(photos, 1):
        stem = photo.stem
        out = args.output_dir / f"{stem}.npy"

        if args.skip_existing and out.exists():
            skipped += 1
            continue

        try:
            normals = predict_normals(photo, model, device, model_type)
            save_normals(args.output_dir, stem, normals)
            processed += 1

            if i % 100 == 0:
                elapsed = time.time() - start
                print(f"  [{i}/{len(photos)}] {stem} ({processed / elapsed:.1f} img/s)")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [{i}/{len(photos)}] {stem}: ERROR - {e}")

    elapsed = time.time() - start
    print(f"\nDone: {processed} processed, {skipped} skipped, {errors} errors in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
