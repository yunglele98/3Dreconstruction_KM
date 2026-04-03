#!/usr/bin/env python3
"""Run DUSt3R single/few-view 3D reconstruction for buildings below COLMAP threshold.

For buildings with only 1-2 photos (not enough for COLMAP), DUSt3R can
produce a point cloud from a single image pair or even a single view.
Falls back to placeholder .ply files when DUSt3R is not installed.

Usage:
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2 --output point_clouds/dust3r/
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "point_clouds" / "dust3r"


def load_photo_index(photo_index_path):
    """Load photo index CSV, return address -> [filenames]."""
    by_address = defaultdict(list)
    if not photo_index_path.exists():
        return by_address
    with open(photo_index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr].append(fname)
    return by_address


def find_param_file(params_dir, address):
    """Find the param JSON file for a given address."""
    stem = address.replace(" ", "_").replace(",", "")
    param_file = params_dir / f"{stem}.json"
    if param_file.exists():
        return param_file
    return None


def is_skipped(param_file):
    """Check if a param file is marked as skipped."""
    try:
        data = json.loads(param_file.read_text(encoding="utf-8"))
        return data.get("skipped", False)
    except (json.JSONDecodeError, OSError):
        return False


def sanitize_name(address):
    """Convert address to filesystem-safe name."""
    return address.replace(" ", "_").replace(",", "").replace("/", "_")


def resolve_photo_path(photo_dir, filename):
    """Resolve a photo filename to its path on disk."""
    direct = photo_dir / filename
    if direct.exists():
        return direct
    matches = list(photo_dir.rglob(filename))
    return matches[0] if matches else None


def check_dust3r():
    """Check if DUSt3R is available."""
    try:
        import dust3r  # noqa: F401
        return True
    except ImportError:
        return False


def run_dust3r_reconstruction(image_paths, output_path):
    """Run DUSt3R reconstruction on image(s)."""
    try:
        from dust3r.inference import inference
        from dust3r.model import AsymmetricCroCo3DStereo
        from dust3r.utils.image import load_images
        from dust3r.cloud_opt import global_aligner, GlobalAlignerMode

        model = AsymmetricCroCo3DStereo.from_pretrained(
            "naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt"
        )
        model = model.cuda() if __import__("torch").cuda.is_available() else model

        images = load_images([str(p) for p in image_paths], size=512)

        if len(images) == 1:
            # Single view: duplicate for self-pair
            pairs = [(images[0], images[0])]
        else:
            pairs = [(images[i], images[j])
                     for i in range(len(images))
                     for j in range(i + 1, len(images))]

        output = inference(pairs, model, device="cuda" if __import__("torch").cuda.is_available() else "cpu")

        mode = GlobalAlignerMode.PointCloudOptimizer if len(images) > 2 else GlobalAlignerMode.PairViewer
        scene = global_aligner(output, device="cpu", mode=mode)
        pts3d = scene.get_pts3d()

        # Write PLY
        write_ply(output_path, pts3d)
        return True, str(output_path)

    except Exception as e:
        return False, f"DUSt3R error: {e}"


def write_placeholder_ply(output_path, address):
    """Write a minimal placeholder PLY file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write a minimal binary PLY with a single point at origin
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"comment placeholder for {address}\n"
        "comment Run with DUSt3R installed for real reconstruction\n"
        "element vertex 1\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    )
    with open(output_path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(struct.pack("<fff", 0.0, 0.0, 0.0))


def write_ply(output_path, pts3d):
    """Write points to PLY file."""
    import numpy as np
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Flatten point arrays
    all_pts = []
    for pts in pts3d:
        if hasattr(pts, "detach"):
            pts = pts.detach().cpu().numpy()
        pts = pts.reshape(-1, 3)
        all_pts.append(pts)
    points = np.concatenate(all_pts, axis=0)

    # Filter out invalid points
    valid = np.isfinite(points).all(axis=1)
    points = points[valid]

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(points)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    )
    with open(output_path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(points.astype(np.float32).tobytes())


def main():
    parser = argparse.ArgumentParser(
        description="Run DUSt3R single/few-view 3D reconstruction."
    )
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON",
                        help="Photo directory")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Params directory")
    parser.add_argument("--max-views", type=int, default=2,
                        help="Maximum photo count to process (buildings with more go to COLMAP)")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for point clouds")
    parser.add_argument("--photo-index", type=Path, default=PHOTO_INDEX,
                        help="Path to photo index CSV")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only first N buildings")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip buildings that already have output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    photo_index = load_photo_index(args.photo_index)
    if not photo_index:
        print("ERROR: No photo index data. Check --photo-index path.")
        sys.exit(1)

    has_dust3r = check_dust3r()
    if not has_dust3r:
        print("WARNING: DUSt3R not installed. Will create placeholder .ply files.")
        print("  Install DUSt3R for real single-view reconstruction.")

    # Filter to buildings with 1..max_views photos
    targets = []
    for address, filenames in sorted(photo_index.items()):
        count = len(filenames)
        if count < 1 or count > args.max_views:
            continue
        param_file = find_param_file(args.params, address)
        if param_file and is_skipped(param_file):
            continue
        targets.append({
            "address": address,
            "filenames": filenames,
            "param_file": str(param_file) if param_file else None,
        })

    if args.limit:
        targets = targets[:args.limit]

    print(f"DUSt3R reconstruction: {len(targets)} buildings (1-{args.max_views} views)")
    print(f"  Output: {args.output}")

    if args.dry_run:
        for t in targets:
            slug = sanitize_name(t["address"])
            existing = (args.output / f"{slug}.ply").exists()
            status = "EXISTS" if existing else "PENDING"
            print(f"  [{status}] {t['address']} ({len(t['filenames'])} photos)")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    results = {"OK": 0, "SKIP": 0, "FAIL": 0, "PLACEHOLDER": 0}
    for i, target in enumerate(targets, 1):
        address = target["address"]
        filenames = target["filenames"]
        slug = sanitize_name(address)
        ply_path = args.output / f"{slug}.ply"

        if args.skip_existing and ply_path.exists():
            results["SKIP"] += 1
            continue

        print(f"  [{i}/{len(targets)}] {address} ({len(filenames)} photos)")

        if not has_dust3r:
            write_placeholder_ply(ply_path, address)
            results["PLACEHOLDER"] += 1
            print(f"    [PLACEHOLDER] {ply_path.name}")
            continue

        # Resolve photo paths
        image_paths = []
        for fname in filenames:
            p = resolve_photo_path(args.input, fname)
            if p:
                image_paths.append(p)

        if not image_paths:
            results["FAIL"] += 1
            print(f"    [FAIL] No photos found on disk")
            continue

        ok, msg = run_dust3r_reconstruction(image_paths, ply_path)
        if ok:
            results["OK"] += 1
            size_kb = ply_path.stat().st_size / 1024
            print(f"    [OK] {ply_path.name} ({size_kb:.0f} KB)")
        else:
            results["FAIL"] += 1
            print(f"    [FAIL] {msg}")

    print(f"\nComplete: {results}")


if __name__ == "__main__":
    main()
