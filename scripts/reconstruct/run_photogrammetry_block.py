#!/usr/bin/env python3
"""Run COLMAP block-level photogrammetry for a street.

Instead of per-building reconstruction (which needs 3+ photos each),
this groups all photos on a street into one COLMAP run. The resulting
dense point cloud / mesh is then clipped per building via clip_block_mesh.py.

Usage:
    python scripts/reconstruct/run_photogrammetry_block.py --street "Augusta Ave"
    python scripts/reconstruct/run_photogrammetry_block.py --street "Augusta Ave" --dense
    python scripts/reconstruct/run_photogrammetry_block.py --list-blocks
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _colmap import (
    find_colmap,
    acquire_gpu_lock,
    release_gpu_lock,
    run_sparse_reconstruction,
    run_dense_reconstruction,
    export_model_ply,
    validate_sparse_model,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
COLMAP_PRIORITY = REPO_ROOT / "outputs" / "visual_audit" / "colmap_priority.json"
OUTPUT_DIR = REPO_ROOT / "point_clouds" / "colmap_blocks"
PARAMS_DIR = REPO_ROOT / "params"


def load_photo_index():
    """Load photo index CSV, return address -> [filenames]."""
    by_address = defaultdict(list)
    if not PHOTO_INDEX.exists():
        return by_address
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr].append(fname)
    return by_address


def get_street_for_address(address):
    """Infer street from address string or params."""
    # Try params file
    stem = address.replace(" ", "_").replace(",", "")
    param_file = PARAMS_DIR / f"{stem}.json"
    if param_file.exists():
        try:
            p = json.loads(param_file.read_text(encoding="utf-8"))
            return p.get("site", {}).get("street", "")
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: extract from address (e.g. "123 Augusta Ave" -> "Augusta Ave")
    parts = address.split()
    if len(parts) >= 2:
        # Skip leading numbers
        for i, part in enumerate(parts):
            if not part.replace("-", "").isdigit():
                return " ".join(parts[i:])
    return ""


def collect_block_photos(street):
    """Collect all photo files for a street block."""
    photo_index = load_photo_index()
    block_photos = []

    for address, filenames in photo_index.items():
        addr_street = get_street_for_address(address)
        if street.lower() not in addr_street.lower():
            continue
        for fname in filenames:
            # Find the file on disk
            for search_dir in [PHOTO_DIR]:
                if not search_dir.exists():
                    continue
                matches = list(search_dir.rglob(fname))
                if matches:
                    block_photos.append({
                        "address": address,
                        "filename": fname,
                        "path": matches[0],
                    })
                    break

    return block_photos


def list_blocks():
    """List streets ranked by COLMAP priority."""
    if COLMAP_PRIORITY.exists():
        blocks = json.loads(COLMAP_PRIORITY.read_text(encoding="utf-8"))
        print(f"{'Rank':<5} {'Street':<25} {'Buildings':>10} {'Photos':>8} {'Priority':>10}")
        print("-" * 60)
        for i, b in enumerate(blocks[:15], 1):
            print(f"{i:<5} {b['block']:<25} {b['building_count']:>10} "
                  f"{b['total_photos']:>8} {b['priority_score']:>10.1f}")
    else:
        print("No COLMAP priority file. Run visual audit first.")


def run_colmap_sparse(image_dir, workspace, colmap_bin, gpu_index=0):
    """COLMAP sparse reconstruction (delegates to shared module)."""
    ok, model, log = run_sparse_reconstruction(
        image_dir, workspace, colmap_bin, gpu_index=gpu_index,
    )
    for msg in log:
        print(f"    {msg}")
    return ok, model if ok else (log[-1] if log else "Unknown error")


def run_colmap_dense(sparse_model, image_dir, workspace, colmap_bin, gpu_index=0):
    """COLMAP dense reconstruction (delegates to shared module)."""
    ok, ply, log = run_dense_reconstruction(
        sparse_model, image_dir, workspace, colmap_bin, gpu_index=gpu_index,
    )
    for msg in log:
        print(f"    {msg}")
    return ok, ply if ok else (log[-1] if log else "Unknown error")


def export_sparse_ply(sparse_model, workspace, colmap_bin):
    """Export sparse model as PLY for quick inspection."""
    ply_path = workspace / "sparse_cloud.ply"
    result = export_model_ply(sparse_model, ply_path, colmap_bin)
    if result:
        size_mb = result.stat().st_size / 1024 / 1024
        print(f"    Sparse PLY: {result.name} ({size_mb:.1f} MB)")
    return result


def main():
    parser = argparse.ArgumentParser(description="Run block-level COLMAP photogrammetry.")
    parser.add_argument("--street", type=str, help="Street name (e.g. 'Augusta Ave')")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--dense", action="store_true", help="Also run dense reconstruction")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-blocks", action="store_true")
    args = parser.parse_args()

    if args.list_blocks:
        list_blocks()
        return

    if not args.street:
        print("ERROR: --street required (or use --list-blocks)")
        sys.exit(1)

    colmap_bin = find_colmap()
    if not colmap_bin and not args.dry_run:
        print("ERROR: COLMAP not found. Install COLMAP or add to PATH.")
        sys.exit(1)

    print(f"Block photogrammetry: {args.street}")
    block_photos = collect_block_photos(args.street)
    print(f"  Found {len(block_photos)} photos")

    if not block_photos:
        print("  No photos found for this street. Check photo index CSV.")
        return

    # Group by address for summary
    by_addr = defaultdict(list)
    for p in block_photos:
        by_addr[p["address"]].append(p["filename"])
    print(f"  Across {len(by_addr)} addresses:")
    for addr in sorted(by_addr)[:10]:
        print(f"    {addr}: {len(by_addr[addr])} photos")
    if len(by_addr) > 10:
        print(f"    ... and {len(by_addr) - 10} more")

    slug = args.street.replace(" ", "_")
    workspace = args.output / slug
    img_dir = workspace / "images"

    if args.dry_run:
        print(f"\n  DRY RUN: would copy {len(block_photos)} photos to {img_dir}")
        return

    # Copy photos to workspace
    img_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in block_photos:
        dst = img_dir / p["path"].name
        if not dst.exists():
            shutil.copy2(p["path"], dst)
            copied += 1
    print(f"  Copied {copied} new photos to {img_dir}")

    # Acquire GPU lock
    if not acquire_gpu_lock("run_photogrammetry_block"):
        print("ERROR: GPU is locked by another process. Wait or remove .gpu_lock")
        sys.exit(1)

    start = time.time()
    try:
        # Sparse reconstruction
        print("\n  SPARSE RECONSTRUCTION")
        ok, sparse_model = run_colmap_sparse(img_dir, workspace, colmap_bin, args.gpu_index)
        if not ok:
            print(f"  FAILED: {sparse_model}")
            return

        print(f"  Sparse model: {sparse_model}")
        export_sparse_ply(sparse_model, workspace, colmap_bin)

        # Validate
        validation = validate_sparse_model(Path(sparse_model))
        print(f"  Validation: {validation['images']} images, {validation['points']} points")

        # Dense reconstruction
        if args.dense:
            print("\n  DENSE RECONSTRUCTION")
            ok, ply_path = run_colmap_dense(sparse_model, img_dir, workspace, colmap_bin, args.gpu_index)
            if not ok:
                print(f"  FAILED: {ply_path}")
            else:
                size_mb = Path(ply_path).stat().st_size / 1024 / 1024
                print(f"  Dense PLY: {ply_path} ({size_mb:.1f} MB)")
    finally:
        release_gpu_lock()

    elapsed = time.time() - start
    print(f"\n  Complete in {elapsed:.0f}s")

    # Write report
    report = {
        "street": args.street,
        "photo_count": len(block_photos),
        "address_count": len(by_addr),
        "workspace": str(workspace),
        "sparse_model": sparse_model if ok else None,
        "elapsed_s": round(elapsed),
    }
    report_path = workspace / "block_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Report: {report_path}")


if __name__ == "__main__":
    main()
