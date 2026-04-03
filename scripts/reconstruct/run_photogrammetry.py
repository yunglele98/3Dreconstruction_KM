#!/usr/bin/env python3
"""Run COLMAP photogrammetry for individual building candidates.

Per-building pipeline for buildings with 3+ dedicated photos.
For street-level block runs, use run_photogrammetry_block.py instead.

Usage:
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --address "22 Lippincott St"
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --dense --limit 10
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
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
OUTPUT_DIR = REPO_ROOT / "point_clouds" / "colmap"
GPU_LOCK = REPO_ROOT / ".gpu_lock"


def find_colmap() -> str | None:
    """Locate COLMAP executable."""
    candidates = [
        shutil.which("colmap"),
        "/usr/bin/colmap",
        "/usr/local/bin/colmap",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def acquire_gpu_lock() -> bool:
    if GPU_LOCK.exists():
        return False
    GPU_LOCK.write_text(f"colmap_{__import__('os').getpid()}", encoding="utf-8")
    return True


def release_gpu_lock():
    if GPU_LOCK.exists():
        GPU_LOCK.unlink()


def prepare_images(candidate: dict, photo_dir: Path, workspace: Path) -> Path:
    """Copy candidate photos into a COLMAP workspace."""
    img_dir = workspace / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    for photo in candidate.get("photos", []):
        src = photo_dir / photo
        if src.exists():
            shutil.copy2(src, img_dir / photo)

    return img_dir


def run_sparse(image_dir: Path, workspace: Path, colmap_bin: str, gpu_index: int = 0) -> tuple[bool, str]:
    """Run COLMAP sparse reconstruction."""
    db_path = workspace / "database.db"
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        ("Feature extraction", [
            colmap_bin, "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--ImageReader.single_camera", "0",
            "--SiftExtraction.max_num_features", "8192",
            "--FeatureExtraction.max_image_size", "2048",
        ]),
        ("Exhaustive matching", [
            colmap_bin, "exhaustive_matcher",
            "--database_path", str(db_path),
        ]),
        ("Mapping", [
            colmap_bin, "mapper",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--output_path", str(sparse_dir),
        ]),
    ]

    for name, cmd in steps:
        print(f"    {name}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if result.returncode != 0:
                return False, f"{name} failed: {result.stderr[:300]}"
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out"

    models = sorted(sparse_dir.iterdir()) if sparse_dir.exists() else []
    if not models:
        return False, "No sparse model produced"
    return True, str(models[0])


def run_dense(sparse_model: str, image_dir: Path, workspace: Path,
              colmap_bin: str) -> tuple[bool, str]:
    """Run COLMAP dense reconstruction and fusion."""
    dense_dir = workspace / "dense"
    dense_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        ("Undistort", [
            colmap_bin, "image_undistorter",
            "--image_path", str(image_dir),
            "--input_path", sparse_model,
            "--output_path", str(dense_dir),
            "--output_type", "COLMAP",
        ]),
        ("Patch match stereo", [
            colmap_bin, "patch_match_stereo",
            "--workspace_path", str(dense_dir),
            "--workspace_format", "COLMAP",
        ]),
    ]

    for name, cmd in steps:
        print(f"    {name}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                return False, f"{name} failed: {result.stderr[:300]}"
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out"

    # Fusion
    ply_path = workspace / "fused.ply"
    cmd = [colmap_bin, "stereo_fusion",
           "--workspace_path", str(dense_dir),
           "--workspace_format", "COLMAP",
           "--output_path", str(ply_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not ply_path.exists():
        return False, "Fusion failed"

    return True, str(ply_path)


def export_sparse_ply(sparse_model: str, workspace: Path, colmap_bin: str) -> Path | None:
    """Export sparse model as PLY."""
    ply_path = workspace / "sparse_cloud.ply"
    cmd = [colmap_bin, "model_converter",
           "--input_path", sparse_model,
           "--output_path", str(ply_path),
           "--output_type", "PLY"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return ply_path if ply_path.exists() else None


def reconstruct_building(candidate: dict, photo_dir: Path, output_dir: Path,
                         colmap_bin: str, dense: bool = False) -> dict:
    """Run full COLMAP pipeline for one building."""
    address = candidate["address"]
    slug = address.replace(" ", "_").replace(",", "")
    workspace = output_dir / slug

    result = {
        "address": address,
        "photos": candidate["photo_count"],
        "sparse_ok": False,
        "dense_ok": False,
        "sparse_ply": None,
        "dense_ply": None,
        "error": "",
    }

    img_dir = prepare_images(candidate, photo_dir, workspace)
    actual_count = len(list(img_dir.glob("*")))
    if actual_count < 2:
        result["error"] = f"Only {actual_count} photos found on disk"
        return result

    print(f"  {address}: {actual_count} photos -> {workspace.name}")

    ok, sparse_model = run_sparse(img_dir, workspace, colmap_bin)
    result["sparse_ok"] = ok
    if not ok:
        result["error"] = sparse_model
        return result

    sparse_ply = export_sparse_ply(sparse_model, workspace, colmap_bin)
    if sparse_ply:
        result["sparse_ply"] = str(sparse_ply)

    if dense:
        ok, ply_path = run_dense(sparse_model, img_dir, workspace, colmap_bin)
        result["dense_ok"] = ok
        if ok:
            result["dense_ply"] = ply_path
        else:
            result["error"] = ply_path

    return result


def main():
    parser = argparse.ArgumentParser(description="Per-building COLMAP photogrammetry")
    parser.add_argument("--candidates", type=Path,
                        default=REPO_ROOT / "reconstruction_candidates.json")
    parser.add_argument("--photo-dir", type=Path, default=PHOTO_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--address", type=str, default=None)
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    colmap_bin = find_colmap()
    if not colmap_bin and not args.dry_run:
        print("ERROR: COLMAP not found. Install or add to PATH.")
        sys.exit(1)

    data = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = data.get("candidates", data) if isinstance(data, dict) else data

    if args.address:
        candidates = [c for c in candidates if args.address.lower() in c["address"].lower()]
    if args.limit:
        candidates = candidates[:args.limit]

    # Filter to colmap-appropriate methods
    colmap_candidates = [c for c in candidates
                         if c.get("recommended_method", "").startswith("colmap")]

    print(f"COLMAP pipeline: {len(colmap_candidates)} candidates")
    if args.dry_run:
        for c in colmap_candidates:
            print(f"  {c['address']}: {c['photo_count']} photos, {c.get('recommended_method')}")
        return

    if not acquire_gpu_lock():
        print("GPU is locked by another process.")
        sys.exit(1)

    try:
        results = []
        for c in colmap_candidates:
            r = reconstruct_building(c, args.photo_dir, args.output, colmap_bin, args.dense)
            results.append(r)
            status = "OK" if r["sparse_ok"] else f"FAIL: {r['error']}"
            print(f"  -> {status}")

        # Write results
        report_path = args.output / "colmap_results.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

        ok_count = sum(1 for r in results if r["sparse_ok"])
        print(f"\nComplete: {ok_count}/{len(results)} successful")
    finally:
        release_gpu_lock()


if __name__ == "__main__":
    main()
