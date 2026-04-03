#!/usr/bin/env python3
"""Single/few-view 3D reconstruction using DUSt3R/MASt3R.

For buildings with 1-2 photos (insufficient for COLMAP), uses DUSt3R
to produce a rough point cloud from minimal views.

Usage:
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON sorted" --params params/
    python scripts/reconstruct/run_dust3r.py --address "22 Lippincott St" --max-views 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
OUTPUT_DIR = REPO_ROOT / "point_clouds" / "dust3r"


def parse_args():
    parser = argparse.ArgumentParser(description="Single-view 3D via DUSt3R/MASt3R.")
    parser.add_argument("--input", type=Path, default=PHOTO_DIR)
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--max-views", type=int, default=2, help="Max photos per building (1 or 2)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    return parser.parse_args()


def load_dust3r():
    """Load DUSt3R model."""
    try:
        import torch
        from dust3r.model import AsymmetricCroCo3DStereo
        from dust3r.inference import inference
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = AsymmetricCroCo3DStereo.from_pretrained(
            "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
        ).to(device)
        print(f"Loaded DUSt3R on {device}")
        return model, device
    except ImportError:
        print("ERROR: dust3r not installed.")
        print("  pip install git+https://github.com/naver/dust3r.git")
        sys.exit(1)


def find_buildings_needing_dust3r(params_dir, max_views=2):
    """Find buildings with 1-2 matched photos (not enough for COLMAP)."""
    buildings = []
    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if p.get("skipped"):
            continue

        matched = p.get("matched_photos", [])
        if not isinstance(matched, list):
            matched = []

        # Also check photo_observations
        po = p.get("photo_observations", {})
        if isinstance(po, dict) and po.get("photo"):
            if po["photo"] not in matched:
                matched.append(po["photo"])

        # DUSt3R candidates: 1-2 photos (not enough for COLMAP's 3+)
        if 1 <= len(matched) <= max_views:
            addr = f.stem.replace("_", " ")
            buildings.append({
                "address": addr,
                "file": str(f),
                "photos": matched,
                "photo_count": len(matched),
            })

    return buildings


def reconstruct_single_view(photo_path, model, device):
    """Run DUSt3R on a single image (self-paired)."""
    import torch
    from dust3r.utils.image import load_images
    from dust3r.inference import inference
    from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

    images = load_images([str(photo_path), str(photo_path)], size=512)
    output = inference([tuple(images)], model, device, batch_size=1)

    scene = global_aligner(output, device=device, mode=GlobalAlignerMode.PairViewer)
    pts3d = scene.get_pts3d()
    pts = pts3d[0].detach().cpu().numpy().reshape(-1, 3)

    # Filter outliers
    center = np.median(pts, axis=0)
    dists = np.linalg.norm(pts - center, axis=2 if pts.ndim == 3 else 1)
    mask = dists < np.percentile(dists, 95)
    pts = pts[mask]

    return pts


def reconstruct_stereo(photo_paths, model, device):
    """Run DUSt3R on a pair of images."""
    import torch
    from dust3r.utils.image import load_images
    from dust3r.inference import inference
    from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

    images = load_images([str(p) for p in photo_paths], size=512)
    pairs = [(images[0], images[1])]
    output = inference(pairs, model, device, batch_size=1)

    mode = GlobalAlignerMode.PairViewer if len(photo_paths) == 2 else GlobalAlignerMode.PointCloudOptimizer
    scene = global_aligner(output, device=device, mode=mode)
    pts3d = scene.get_pts3d()

    all_pts = []
    for pts in pts3d:
        p = pts.detach().cpu().numpy().reshape(-1, 3)
        all_pts.append(p)
    pts = np.concatenate(all_pts, axis=0)

    # Filter outliers
    center = np.median(pts, axis=0)
    dists = np.linalg.norm(pts - center, axis=1)
    mask = dists < np.percentile(dists, 95)
    pts = pts[mask]

    return pts


def save_ply(path, points):
    """Save point cloud as PLY."""
    header = f"""ply
format ascii 1.0
element vertex {len(points)}
property float x
property float y
property float z
end_header
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for pt in points:
            f.write(f"{pt[0]:.6f} {pt[1]:.6f} {pt[2]:.6f}\n")


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    buildings = find_buildings_needing_dust3r(args.params, args.max_views)

    if args.address:
        buildings = [b for b in buildings if args.address.lower() in b["address"].lower()]
    if args.limit:
        buildings = buildings[: args.limit]

    print(f"DUSt3R reconstruction: {len(buildings)} buildings with 1-{args.max_views} photos")

    if not buildings:
        print("No candidates found.")
        return

    model, device = load_dust3r()

    # Build photo path index
    photo_index = {}
    for d in [PHOTO_DIR, REPO_ROOT / "PHOTOS KENSINGTON sorted"]:
        if d.exists():
            for p in d.rglob("*.[jJ][pP][gG]"):
                photo_index[p.name] = p

    results = []
    start = time.time()

    for i, bldg in enumerate(buildings, 1):
        address = bldg["address"]
        slug = address.replace(" ", "_").replace(",", "")
        ply_path = args.output / f"{slug}.ply"

        if args.skip_existing and ply_path.exists():
            continue

        photo_paths = [photo_index[f] for f in bldg["photos"] if f in photo_index]
        if not photo_paths:
            continue

        print(f"  [{i}/{len(buildings)}] {address} ({len(photo_paths)} photos)...")

        try:
            if len(photo_paths) == 1:
                pts = reconstruct_single_view(photo_paths[0], model, device)
            else:
                pts = reconstruct_stereo(photo_paths[:2], model, device)

            save_ply(ply_path, pts)
            print(f"    {len(pts)} points -> {ply_path.name}")
            results.append({"address": address, "status": "success", "points": len(pts)})

        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"address": address, "status": "failed", "error": str(e)[:200]})

    elapsed = time.time() - start
    succeeded = sum(1 for r in results if r["status"] == "success")
    print(f"\nDone: {succeeded}/{len(results)} in {elapsed:.0f}s")

    report = args.output / "dust3r_run_report.json"
    report.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
