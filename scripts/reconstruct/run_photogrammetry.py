#!/usr/bin/env python3
"""Run COLMAP photogrammetry on candidate buildings.

For each candidate with 3+ matched photos, runs COLMAP sparse + dense
reconstruction to produce a point cloud and optionally a mesh.

Usage:
    python scripts/reconstruct/run_photogrammetry.py
    python scripts/reconstruct/run_photogrammetry.py --candidates outputs/reconstruction_candidates.json
    python scripts/reconstruct/run_photogrammetry.py --address "22 Lippincott St"
    python scripts/reconstruct/run_photogrammetry.py --street "Augusta Ave" --limit 5
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CANDIDATES = REPO_ROOT / "outputs" / "reconstruction_candidates.json"
DEFAULT_OUTPUT = REPO_ROOT / "point_clouds" / "colmap"
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
PHOTO_SORTED_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"


def find_colmap():
    """Locate COLMAP executable."""
    candidates = [
        shutil.which("colmap"),
        "C:/Program Files/COLMAP/COLMAP.bat",
        "C:/tools/COLMAP/COLMAP.bat",
        "/usr/bin/colmap",
        "/usr/local/bin/colmap",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def find_photos_for_address(address, photos_list):
    """Resolve photo filenames to absolute paths."""
    resolved = []
    # Build filename index
    photo_index = {}
    for d in [PHOTO_DIR, PHOTO_SORTED_DIR]:
        if not d.exists():
            continue
        for p in d.rglob("*.jpg"):
            photo_index[p.name] = p
        for p in d.rglob("*.JPG"):
            photo_index[p.name] = p

    for fname in photos_list:
        path = photo_index.get(fname)
        if path and path.exists():
            resolved.append(path)
    return resolved


def run_colmap_sparse(image_dir, workspace, colmap_bin, gpu_index=0):
    """Run COLMAP sparse reconstruction (feature extraction + matching + mapping)."""
    db_path = workspace / "database.db"
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    # Feature extraction
    cmd_extract = [
        colmap_bin, "feature_extractor",
        "--database_path", str(db_path),
        "--image_path", str(image_dir),
        "--ImageReader.single_camera", "1",
        "--FeatureExtraction.use_gpu", str(int(gpu_index >= 0)),
        "--FeatureExtraction.gpu_index", str(max(gpu_index, 0)),
    ]
    print(f"    Feature extraction...")
    result = subprocess.run(cmd_extract, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return False, f"feature_extractor failed: {result.stderr[:300]}"

    # Exhaustive matching (small image sets)
    cmd_match = [
        colmap_bin, "exhaustive_matcher",
        "--database_path", str(db_path),
        "--FeatureMatching.use_gpu", str(int(gpu_index >= 0)),
        "--FeatureMatching.gpu_index", str(max(gpu_index, 0)),
    ]
    print(f"    Matching...")
    result = subprocess.run(cmd_match, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return False, f"exhaustive_matcher failed: {result.stderr[:300]}"

    # Sparse reconstruction (mapper)
    cmd_mapper = [
        colmap_bin, "mapper",
        "--database_path", str(db_path),
        "--image_path", str(image_dir),
        "--output_path", str(sparse_dir),
    ]
    print(f"    Mapping...")
    result = subprocess.run(cmd_mapper, capture_output=True, text=True, timeout=1200)
    if result.returncode != 0:
        return False, f"mapper failed: {result.stderr[:300]}"

    # Check if reconstruction succeeded
    models = list(sparse_dir.iterdir())
    if not models:
        return False, "No sparse model produced"

    return True, str(models[0])


def run_colmap_dense(sparse_model, image_dir, workspace, colmap_bin, gpu_index=0):
    """Run COLMAP dense reconstruction (undistort + patch_match + fusion)."""
    dense_dir = workspace / "dense"
    dense_dir.mkdir(parents=True, exist_ok=True)

    # Undistort images
    cmd_undistort = [
        colmap_bin, "image_undistorter",
        "--image_path", str(image_dir),
        "--input_path", str(sparse_model),
        "--output_path", str(dense_dir),
        "--output_type", "COLMAP",
    ]
    print(f"    Undistorting...")
    result = subprocess.run(cmd_undistort, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return False, f"undistorter failed: {result.stderr[:300]}"

    # Patch match stereo
    cmd_stereo = [
        colmap_bin, "patch_match_stereo",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--PatchMatchStereo.gpu_index", str(max(gpu_index, 0)),
    ]
    print(f"    Patch match stereo...")
    result = subprocess.run(cmd_stereo, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        return False, f"patch_match_stereo failed: {result.stderr[:300]}"

    # Stereo fusion -> point cloud
    ply_path = workspace / "fused.ply"
    cmd_fusion = [
        colmap_bin, "stereo_fusion",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--output_path", str(ply_path),
    ]
    print(f"    Fusion...")
    result = subprocess.run(cmd_fusion, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return False, f"fusion failed: {result.stderr[:300]}"

    if not ply_path.exists():
        return False, "No fused.ply produced"

    return True, str(ply_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Run COLMAP photogrammetry on candidates.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dense", action="store_true", help="Also run dense reconstruction")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    colmap_bin = find_colmap()
    if not colmap_bin and not args.dry_run:
        print("ERROR: COLMAP not found. Install from https://colmap.github.io/")
        sys.exit(1)

    if not args.candidates.exists():
        print(f"ERROR: Candidates file not found: {args.candidates}")
        print("  Run: python scripts/reconstruct/select_candidates.py")
        sys.exit(1)

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", [])

    # Filter
    if args.address:
        candidates = [c for c in candidates if args.address.lower() in c.get("address", "").lower()]
    if args.street:
        candidates = [c for c in candidates if args.street.lower() in c.get("street", "").lower()]
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"COLMAP photogrammetry: {len(candidates)} candidates")
    if colmap_bin:
        print(f"  COLMAP: {colmap_bin}")
    print(f"  Output: {args.output}")
    if args.dry_run:
        print("  DRY RUN MODE")

    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    start = time.time()

    for i, cand in enumerate(candidates, 1):
        address = cand.get("address", "unknown")
        photos = cand.get("photos", cand.get("matched_photos", []))
        slug = address.replace(" ", "_").replace(",", "")

        print(f"\n[{i}/{len(candidates)}] {address} ({len(photos)} photos)")

        if len(photos) < 3:
            print(f"  Skipped: only {len(photos)} photos (need 3+)")
            results.append({"address": address, "status": "skipped", "reason": "insufficient_photos"})
            continue

        # Resolve photo paths
        photo_paths = find_photos_for_address(address, photos)
        if len(photo_paths) < 3:
            print(f"  Skipped: only {len(photo_paths)} photos found on disk")
            results.append({"address": address, "status": "skipped", "reason": "photos_not_found"})
            continue

        workspace = args.output / slug
        ply_path = workspace / "fused.ply"

        if ply_path.exists():
            print(f"  Already reconstructed, skipping")
            results.append({"address": address, "status": "cached", "ply": str(ply_path)})
            continue

        if args.dry_run:
            print(f"  Would process: {len(photo_paths)} photos -> {workspace}")
            results.append({"address": address, "status": "dry_run", "photos": len(photo_paths)})
            continue

        # Copy photos to workspace
        img_dir = workspace / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        for p in photo_paths:
            dst = img_dir / p.name
            if not dst.exists():
                shutil.copy2(p, dst)

        # Run sparse
        ok, msg = run_colmap_sparse(img_dir, workspace, colmap_bin, args.gpu_index)
        if not ok:
            print(f"  FAILED (sparse): {msg}")
            results.append({"address": address, "status": "failed", "stage": "sparse", "error": msg})
            continue

        print(f"  Sparse OK: {msg}")

        # Run dense if requested
        if args.dense:
            ok, msg = run_colmap_dense(msg, img_dir, workspace, colmap_bin, args.gpu_index)
            if not ok:
                print(f"  FAILED (dense): {msg}")
                results.append({"address": address, "status": "failed", "stage": "dense", "error": msg})
                continue
            print(f"  Dense OK: {msg}")

        results.append({"address": address, "status": "success", "workspace": str(workspace)})

    elapsed = time.time() - start
    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"\nDone: {succeeded} success, {failed} failed in {elapsed:.0f}s")

    # Write results
    report_path = args.output / "colmap_run_report.json"
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
