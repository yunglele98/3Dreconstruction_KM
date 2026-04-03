#!/usr/bin/env python3
"""Stage 1 — SENSE: Extract surface normal maps using DSINE.

Reads field photos and estimates per-pixel surface normals for facade
geometry reconstruction. Normals feed into depth refinement, mesh
alignment, and material creation.

Modes:
  1. GPU: DSINE model via HuggingFace (requires torch)
  2. Edge fallback: Sobel gradient-based normal estimation (CPU)
  3. Cloud prep: packages photos for cloud GPU execution

Usage:
    python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON/" --output normals/
    python scripts/sense/extract_normals.py --input "PHOTOS KENSINGTON/" --output normals/ --method edge
    python scripts/sense/extract_normals.py --prepare-cloud --output cloud_session/normals/
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
DEFAULT_OUTPUT = REPO_ROOT / "normals"


def discover_photos(input_dir: Path, *, limit: int = 0) -> list[Path]:
    photos = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in PHOTO_EXTENSIONS)
    return photos[:limit] if limit > 0 else photos


def extract_normals_edge(photo_path: Path, output_dir: Path) -> dict:
    """Estimate surface normals from Sobel gradients (CPU fallback)."""
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_normals.npy"
    viz_path = output_dir / f"{stem}_normals_viz.png"

    result = {"photo": str(photo_path), "model": "sobel-normals",
              "normals_npy": str(npy_path), "normals_viz": str(viz_path)}

    if np is None:
        result["status"] = "skipped_no_numpy"
        return result

    try:
        from PIL import Image, ImageFilter

        img = Image.open(photo_path).convert("L")
        w, h = img.size
        if max(w, h) > 1024:
            s = 1024 / max(w, h)
            img = img.resize((int(w * s), int(h * s)))

        # Sobel gradients
        dx = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=1
        )), dtype=np.float32) / 255.0
        dy = np.array(img.filter(ImageFilter.Kernel(
            (3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=1
        )), dtype=np.float32) / 255.0

        # Normal = normalize(-dx, -dy, 1)
        strength = 2.0
        nx = -dx * strength
        ny = -dy * strength
        nz = np.ones_like(nx)
        mag = np.sqrt(nx**2 + ny**2 + nz**2) + 1e-8
        normals = np.stack([nx / mag, ny / mag, nz / mag], axis=-1).astype(np.float32)

        np.save(npy_path, normals)

        # Visualization: map [-1,1] → [0,255]
        viz = ((normals + 1) * 0.5 * 255).astype(np.uint8)
        Image.fromarray(viz).save(viz_path)

        result["status"] = "success"
        result["shape"] = list(normals.shape)
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def extract_normals_gpu(photo_path: Path, output_dir: Path) -> dict:
    """Extract normals using DSINE model on GPU."""
    stem = photo_path.stem
    npy_path = output_dir / f"{stem}_normals.npy"
    viz_path = output_dir / f"{stem}_normals_viz.png"

    result = {"photo": str(photo_path), "model": "dsine",
              "normals_npy": str(npy_path), "normals_viz": str(viz_path)}

    try:
        import torch
        from PIL import Image
        from transformers import pipeline

        pipe = pipeline("image-to-image", model="Intel/dpt-large",
                        device="cuda" if torch.cuda.is_available() else "cpu")

        img = Image.open(photo_path).convert("RGB")
        w, h = img.size
        if max(w, h) > 1024:
            s = 1024 / max(w, h)
            img = img.resize((int(w * s), int(h * s)))

        output = pipe(img)
        normals = np.array(output, dtype=np.float32) / 127.5 - 1.0

        np.save(npy_path, normals)
        viz = ((normals + 1) * 0.5 * 255).astype(np.uint8)
        Image.fromarray(viz).save(viz_path)

        result["status"] = "success"
        result["shape"] = list(normals.shape)
        return result

    except Exception as e:
        # Fall back to edge method
        return extract_normals_edge(photo_path, output_dir)


def prepare_cloud_session(input_dir: Path, output_dir: Path, limit: int = 200) -> Path:
    upload_dir = output_dir / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    img_dir = upload_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for p in photos:
        shutil.copy2(p, img_dir / p.name)

    (upload_dir / "run_normals.py").write_text('''#!/usr/bin/env python3
"""Cloud GPU normal extraction. Run on A100."""
import numpy as np, json
from pathlib import Path
from PIL import Image
from transformers import pipeline

pipe = pipeline("image-to-image", model="Intel/dpt-large", device="cuda")
output = Path("output")
output.mkdir(exist_ok=True)

for img_path in sorted(Path("images").glob("*.jpg")):
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    if max(w, h) > 1024:
        s = 1024 / max(w, h)
        img = img.resize((int(w*s), int(h*s)))

    result = pipe(img)
    normals = np.array(result, dtype=np.float32) / 127.5 - 1.0
    np.save(output / f"{img_path.stem}_normals.npy", normals)
    viz = ((normals + 1) * 0.5 * 255).astype(np.uint8)
    Image.fromarray(viz).save(output / f"{img_path.stem}_normals_viz.png")

print(f"Done: {len(list(output.glob('*.npy')))} normal maps")
''', encoding="utf-8")

    print(f"Cloud session: {len(photos)} photos → {upload_dir}")
    return upload_dir


def run_batch(input_dir, output_dir, *, method="auto", limit=0, skip_existing=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    photos = discover_photos(input_dir, limit=limit)

    if method == "auto":
        try:
            import torch
            method = "gpu"
        except ImportError:
            method = "edge"

    results = []
    for photo in photos:
        npy_path = output_dir / f"{photo.stem}_normals.npy"
        if skip_existing and npy_path.exists():
            results.append({"photo": str(photo), "status": "skipped_existing"})
            continue
        if method == "gpu":
            results.append(extract_normals_gpu(photo, output_dir))
        else:
            results.append(extract_normals_edge(photo, output_dir))

    return results


def main():
    parser = argparse.ArgumentParser(description="Extract surface normals")
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

    results = run_batch(args.input, args.output, method=args.method,
                        limit=args.limit, skip_existing=args.skip_existing)

    manifest_path = args.output / "normals_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r.get("status") == "success")
    print(f"Normals: {ok} processed")


if __name__ == "__main__":
    main()
