#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract monocular depth maps using Depth Anything v2.

Reads field photos, runs Depth Anything v2 inference, and saves .npy depth
arrays + visualization PNGs to depth_maps/.

Three execution modes:
  1. GPU local: loads Depth Anything v2 model directly (requires torch + transformers)
  2. Edge fallback: Sobel-based relative depth estimation (no GPU needed)
  3. Cloud prep: packages photos for cloud GPU execution

Usage:
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --method edge --limit 50
    python scripts/sense/extract_depth.py --prepare-cloud --output cloud_session/depth/
    python scripts/sense/extract_depth.py --input "PHOTOS KENSINGTON/" --output depth_maps/ --skip-existing
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "depth_maps"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    """Find all photo files in *input_dir* (non-recursive)."""
    photos = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in PHOTO_EXTENSIONS
    )
    return photos[:limit] if limit > 0 else photos


def check_depth_anything() -> bool:
    """Check if Depth Anything v2 dependencies are available."""
    try:
        import torch
        from transformers import pipeline
        return True
    except ImportError:
        return False


def extract_depth_gpu(photo_path: Path, output_dir: Path) -> dict:
    """Run Depth Anything v2 inference on GPU."""
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_depth.npy"
    viz_path = output_dir / f"{stem}_depth_viz.png"

    result = {
        "photo": str(photo_path),
        "model": "depth-anything-v2",
        "depth_npy": str(npy_path),
        "depth_viz": str(viz_path),
    }

    try:
        import torch
        from PIL import Image
        from transformers import pipeline

        pipe = pipeline(
            "depth-estimation",
            model="depth-anything/Depth-Anything-V2-Small-hf",
            device="cuda" if torch.cuda.is_available() else "cpu",
        )

        image = Image.open(photo_path).convert("RGB")
        # Resize for memory efficiency
        max_side = 1024
        w, h = image.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            image = image.resize((int(w * scale), int(h * scale)))

        output = pipe(image)
        depth = np.array(output["depth"], dtype=np.float32)

        np.save(npy_path, depth)

        # Save visualization
        depth_norm = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
        depth_vis = (depth_norm * 255).astype(np.uint8)
        Image.fromarray(depth_vis).save(viz_path)

        result["status"] = "success"
        result["shape"] = list(depth.shape)
        result["depth_range"] = [float(depth.min()), float(depth.max())]
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def extract_depth_edge(photo_path: Path, output_dir: Path) -> dict:
    """Estimate relative depth using Sobel edge detection (CPU fallback).

    Not as accurate as Depth Anything but runs without GPU. Uses gradient
    magnitude as a proxy for surface orientation changes.
    """
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_depth.npy"
    viz_path = output_dir / f"{stem}_depth_viz.png"

    result = {
        "photo": str(photo_path),
        "model": "edge-fallback",
        "depth_npy": str(npy_path),
        "depth_viz": str(viz_path),
    }

    if np is None:
        result["status"] = "skipped_no_numpy"
        return result

    try:
        from PIL import Image, ImageFilter

        img = Image.open(photo_path).convert("L")
        # Resize for consistency
        max_side = 1024
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)))

        arr = np.array(img, dtype=np.float32) / 255.0

        # Sobel gradients
        dx = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
        )), dtype=np.float32) / 255.0
        dy = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
        )), dtype=np.float32) / 255.0

        # Edge magnitude as inverse depth proxy
        edges = np.sqrt(dx ** 2 + dy ** 2)

        # Smooth and invert: low edges = flat surfaces = closer to camera
        blurred = np.array(Image.fromarray(
            (edges * 255).astype(np.uint8)
        ).filter(ImageFilter.GaussianBlur(radius=10)), dtype=np.float32) / 255.0

        # Combine with vertical gradient (lower = closer for buildings)
        gradient = np.linspace(0.3, 1.0, arr.shape[0])
        gradient = np.tile(gradient[:, np.newaxis], (1, arr.shape[1]))

        depth = (1.0 - blurred * 0.5) * gradient
        depth = depth.astype(np.float32)

        np.save(npy_path, depth)

        # Visualization
        depth_norm = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
        viz = (depth_norm * 255).astype(np.uint8)
        Image.fromarray(viz).save(viz_path)

        result["status"] = "success"
        result["shape"] = list(depth.shape)
        result["depth_range"] = [float(depth.min()), float(depth.max())]
        result["note"] = "Edge-based estimate (less accurate than Depth Anything v2)"
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def prepare_cloud_session(input_dir: Path, output_dir: Path, limit: int = 200) -> Path:
    """Package photos for cloud GPU Depth Anything v2 session."""
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)

    photos = discover_photos(input_dir, limit=limit)

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        shutil.copy2(p, img_dir / p.name)

    (upload_dir / "run_depth.py").write_text('''#!/usr/bin/env python3
"""Cloud GPU Depth Anything v2 extraction. Run on A100.
Estimated: ~0.5 sec/image, ~$0.15 for 200 images.
"""
import torch, numpy as np, json
from pathlib import Path
from PIL import Image
from transformers import pipeline

pipe = pipeline("depth-estimation",
    model="depth-anything/Depth-Anything-V2-Small-hf",
    device="cuda")

output = Path("output")
output.mkdir(exist_ok=True)
results = []

for img_path in sorted(Path("images").glob("*.jpg")):
    image = Image.open(img_path).convert("RGB")
    w, h = image.size
    if max(w, h) > 1024:
        s = 1024 / max(w, h)
        image = image.resize((int(w*s), int(h*s)))

    result = pipe(image)
    depth = np.array(result["depth"], dtype=np.float32)
    np.save(output / f"{img_path.stem}_depth.npy", depth)

    # Visualization
    d_norm = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
    Image.fromarray((d_norm * 255).astype(np.uint8)).save(
        output / f"{img_path.stem}_depth_viz.png")

    results.append({"photo": img_path.name, "shape": list(depth.shape)})
    if len(results) % 50 == 0:
        print(f"  [{len(results)}] {img_path.stem}")

Path("output/depth_manifest.json").write_text(json.dumps(results, indent=2))
print(f"Done: {len(results)} depth maps")
''', encoding="utf-8")

    print(f"Cloud session: {len(photos)} photos → {upload_dir}")
    print(f"Upload to cloud GPU and run: python run_depth.py")
    print(f"Estimated cost: ~${len(photos) * 0.001:.2f} on A100")
    return upload_dir


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    method: str = "auto",
    limit: int = 0,
    skip_existing: bool = False,
) -> list[dict]:
    """Process all photos in *input_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    # Select method
    if method == "auto":
        method = "gpu" if check_depth_anything() else "edge"

    results = []
    for i, photo in enumerate(photos, 1):
        npy_path = output_dir / f"{photo.stem}_depth.npy"
        if skip_existing and npy_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue

        if method == "gpu":
            result = extract_depth_gpu(photo, output_dir)
        else:
            result = extract_depth_edge(photo, output_dir)

        results.append(result)

        if i % 50 == 0:
            ok = sum(1 for r in results if r.get("status") == "success")
            print(f"  [{i}/{len(photos)}] {ok} successful so far")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract depth maps from photos")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--method", default="auto", choices=["auto", "gpu", "edge"])
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

    results = run_batch(
        args.input, args.output,
        method=args.method, limit=args.limit, skip_existing=args.skip_existing,
    )

    manifest_path = args.output / "depth_manifest.json"
    manifest_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    ok = sum(1 for r in results if r["status"] == "success")
    skip = sum(1 for r in results if r["status"] == "skipped_existing")
    err = sum(1 for r in results if r["status"] == "error")
    method_used = results[0].get("model", "unknown") if results else "none"
    print(f"Depth extraction ({method_used}): {ok} processed, {skip} skipped, {err} errors")


if __name__ == "__main__":
    main()
