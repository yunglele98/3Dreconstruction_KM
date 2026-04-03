#!/usr/bin/env python3
"""Single-view 3D reconstruction using DUSt3R/MASt3R.

Fallback path for buildings with only 1-2 photos where COLMAP
photogrammetry cannot run. Generates point clouds from minimal views.

Usage:
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --address "22 Lippincott St"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GPU_LOCK = REPO_ROOT / ".gpu_lock"


def acquire_gpu_lock() -> bool:
    """Attempt to acquire GPU lock. Returns True if acquired."""
    if GPU_LOCK.exists():
        logger.warning(f"GPU locked by another process ({GPU_LOCK.read_text().strip()})")
        return False
    GPU_LOCK.write_text(f"dust3r_{__import__('os').getpid()}", encoding="utf-8")
    return True


def release_gpu_lock():
    """Release GPU lock."""
    if GPU_LOCK.exists():
        GPU_LOCK.unlink()


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV."""
    by_address: dict[str, list[str]] = defaultdict(list)
    if not index_path.exists():
        return dict(by_address)
    with open(index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr.lower()].append(fname)
    return dict(by_address)


def load_dust3r_model(device: str = "cuda"):
    """Load DUSt3R model. Returns None if unavailable."""
    try:
        from dust3r.model import AsymmetricCroCo3DStereo
        model = AsymmetricCroCo3DStereo.from_pretrained(
            "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
        )
        if device == "cuda":
            import torch
            if torch.cuda.is_available():
                model = model.cuda()
        model.eval()
        logger.info("Loaded DUSt3R model")
        return model
    except Exception as e:
        logger.warning(f"Could not load DUSt3R: {e}")
        return None


def reconstruct_single_view(image_paths: list[Path], output_dir: Path, model=None) -> dict:
    """Reconstruct point cloud from 1-2 views.

    If DUSt3R model is available, uses it for dense reconstruction.
    Otherwise generates a planar point cloud from the image as placeholder.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if model is not None and len(image_paths) >= 2:
        try:
            from dust3r.inference import inference
            from dust3r.utils.image import load_images
            from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

            images = load_images(image_paths, size=512)
            pairs = [(images[0], images[1])]
            output = inference(pairs, model, device="cuda", batch_size=1)
            scene = global_aligner(output, device="cuda",
                                   mode=GlobalAlignerMode.PairViewer)
            pts3d = scene.get_pts3d()
            pts = pts3d[0].detach().cpu().numpy().reshape(-1, 3)

            ply_path = output_dir / "fused.ply"
            _write_ply(ply_path, pts)
            return {"success": True, "points": len(pts), "method": "dust3r", "path": str(ply_path)}
        except Exception as e:
            logger.error(f"DUSt3R inference failed: {e}")

    # Fallback: generate a flat point cloud from the image
    from PIL import Image
    img = Image.open(image_paths[0]).convert("RGB")
    w, h = img.size
    img_np = np.array(img)

    # Create a grid of 3D points on a plane
    scale = 5.0  # metres
    step = max(1, min(w, h) // 100)
    points = []
    colors = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            px = (x / w - 0.5) * scale
            py = (0.5 - y / h) * scale
            pz = 0.0
            points.append([px, py, pz])
            colors.append(img_np[y, x])

    pts = np.array(points, dtype=np.float32)
    cols = np.array(colors, dtype=np.uint8)

    ply_path = output_dir / "fused.ply"
    _write_ply(ply_path, pts, cols)
    return {"success": True, "points": len(pts), "method": "planar_fallback", "path": str(ply_path)}


def _write_ply(path: Path, points: np.ndarray, colors: np.ndarray | None = None):
    """Write a simple PLY point cloud file."""
    n = len(points)
    has_color = colors is not None and len(colors) == n

    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {n}",
        "property float x",
        "property float y",
        "property float z",
    ]
    if has_color:
        header.extend([
            "property uchar red",
            "property uchar green",
            "property uchar blue",
        ])
    header.append("end_header")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")
        for i in range(n):
            line = f"{points[i][0]:.6f} {points[i][1]:.6f} {points[i][2]:.6f}"
            if has_color:
                line += f" {colors[i][0]} {colors[i][1]} {colors[i][2]}"
            f.write(line + "\n")


def find_candidates(params_dir: Path, photo_index: dict, max_views: int = 2) -> list[dict]:
    """Find buildings with 1-max_views photos (DUSt3R candidates)."""
    candidates = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped"):
            continue

        address = data.get("_meta", {}).get("address") or data.get("building_name", f.stem.replace("_", " "))
        photos = photo_index.get(address.lower(), [])

        if 1 <= len(photos) <= max_views:
            candidates.append({
                "address": address,
                "param_file": f.name,
                "photos": photos,
            })

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Single-view reconstruction with DUSt3R")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "point_clouds" / "dust3r")
    parser.add_argument("--max-views", type=int, default=2)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not acquire_gpu_lock():
        print("GPU is locked. Wait for current job to finish.")
        sys.exit(1)

    try:
        photo_index = load_photo_index(args.photo_index)
        model = load_dust3r_model(args.device)

        if args.address:
            photos = photo_index.get(args.address.lower(), [])
            if not photos:
                print(f"No photos found for {args.address}")
                sys.exit(1)
            image_paths = [args.input / p for p in photos if (args.input / p).exists()]
            out_dir = args.output / args.address.replace(" ", "_")
            result = reconstruct_single_view(image_paths, out_dir, model)
            print(f"{args.address}: {result}")
        else:
            candidates = find_candidates(args.params, photo_index, args.max_views)
            if args.limit:
                candidates = candidates[:args.limit]
            print(f"Found {len(candidates)} DUSt3R candidates")
            for c in candidates:
                image_paths = [args.input / p for p in c["photos"] if (args.input / p).exists()]
                if not image_paths:
                    continue
                out_dir = args.output / c["address"].replace(" ", "_")
                result = reconstruct_single_view(image_paths, out_dir, model)
                print(f"  {c['address']}: {result['points']} points ({result['method']})")
    finally:
        release_gpu_lock()


if __name__ == "__main__":
    main()
