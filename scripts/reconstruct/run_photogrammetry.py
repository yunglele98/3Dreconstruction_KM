#!/usr/bin/env python3
"""Run per-building COLMAP photogrammetry for reconstruction candidates.

Processes each candidate from select_candidates.py output, running
COLMAP sparse reconstruction per building. Falls back to placeholder
output when COLMAP is not available.

Usage:
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/ --dry-run
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
CANDIDATES_DEFAULT = REPO_ROOT / "reconstruction_candidates.json"
OUTPUT_DIR = REPO_ROOT / "point_clouds" / "colmap"


def find_colmap():
    """Locate COLMAP executable."""
    candidates = [
        shutil.which("colmap"),
        "C:/Users/liam1/Apps/COLMAP/bin/colmap",
        "C:/Program Files/COLMAP/COLMAP.bat",
        "/usr/bin/colmap",
        "/usr/local/bin/colmap",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def sanitize_name(address):
    """Convert address to filesystem-safe directory name."""
    return address.replace(" ", "_").replace(",", "").replace("/", "_")


def run_colmap_sparse(image_dir, workspace, colmap_bin, gpu_index=0):
    """Run COLMAP sparse reconstruction for a single building."""
    db_path = workspace / "database.db"
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        ("Feature extraction", [
            colmap_bin, "feature_extractor",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--ImageReader.single_camera", "0",
            "--FeatureExtraction.use_gpu", str(int(gpu_index >= 0)),
            "--FeatureExtraction.gpu_index", str(max(gpu_index, 0)),
            "--SiftExtraction.max_num_features", "8192",
            "--FeatureExtraction.max_image_size", "2048",
        ], 1800),
        ("Exhaustive matching", [
            colmap_bin, "exhaustive_matcher",
            "--database_path", str(db_path),
            "--FeatureMatching.use_gpu", str(int(gpu_index >= 0)),
            "--FeatureMatching.gpu_index", str(max(gpu_index, 0)),
        ], 1800),
        ("Mapping", [
            colmap_bin, "mapper",
            "--database_path", str(db_path),
            "--image_path", str(image_dir),
            "--output_path", str(sparse_dir),
        ], 1800),
    ]

    for name, cmd, timeout in steps:
        print(f"      {name}...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                return False, f"{name} failed: {result.stderr[:300]}"
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out after {timeout}s"

    models = sorted(sparse_dir.iterdir()) if sparse_dir.exists() else []
    if not models:
        return False, "No sparse model produced"

    return True, str(models[0])


def export_sparse_ply(sparse_model, workspace, colmap_bin):
    """Export sparse model as PLY."""
    ply_path = workspace / "sparse_cloud.ply"
    cmd = [
        colmap_bin, "model_converter",
        "--input_path", str(sparse_model),
        "--output_path", str(ply_path),
        "--output_type", "PLY",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and ply_path.exists():
            return ply_path
    except subprocess.TimeoutExpired:
        pass
    return None


def create_placeholder(workspace, address, photo_count):
    """Create placeholder output when COLMAP is not available."""
    workspace.mkdir(parents=True, exist_ok=True)
    placeholder = {
        "address": address,
        "photo_count": photo_count,
        "status": "placeholder",
        "note": "COLMAP not found. Run with COLMAP installed to produce real point clouds.",
    }
    placeholder_path = workspace / "placeholder.json"
    placeholder_path.write_text(
        json.dumps(placeholder, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return placeholder_path


def process_candidate(candidate, output_dir, colmap_bin, gpu_index=0, skip_existing=True):
    """Process a single reconstruction candidate."""
    address = candidate["address"]
    photo_files = candidate.get("photo_files", [])
    slug = sanitize_name(address)
    workspace = output_dir / slug

    # Skip if already processed
    if skip_existing and workspace.exists():
        sparse_dir = workspace / "sparse"
        ply = workspace / "sparse_cloud.ply"
        if (sparse_dir.exists() and list(sparse_dir.iterdir())) or ply.exists():
            return "SKIP", "Already processed"

    if not colmap_bin:
        placeholder = create_placeholder(workspace, address, len(photo_files))
        return "PLACEHOLDER", f"No COLMAP -> {placeholder.name}"

    # Copy photos to workspace images dir
    img_dir = workspace / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for photo_path_str in photo_files:
        src = Path(photo_path_str)
        if src.exists():
            dst = img_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1

    image_count = len(list(img_dir.glob("*")))
    if image_count < 3:
        return "SKIP", f"Only {image_count} images copied (need 3+)"

    # Run COLMAP
    start = time.time()
    ok, sparse_model = run_colmap_sparse(img_dir, workspace, colmap_bin, gpu_index)
    elapsed = time.time() - start

    if not ok:
        return "FAIL", f"{sparse_model} ({elapsed:.0f}s)"

    # Export PLY
    ply = export_sparse_ply(sparse_model, workspace, colmap_bin)
    ply_info = f", PLY: {ply.name}" if ply else ""

    return "OK", f"Sparse model in {elapsed:.0f}s{ply_info}"


def main():
    parser = argparse.ArgumentParser(
        description="Run per-building COLMAP photogrammetry."
    )
    parser.add_argument("--candidates", type=Path, default=CANDIDATES_DEFAULT,
                        help="Candidates JSON from select_candidates.py")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory for point clouds")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only first N candidates")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip buildings that already have output (default: true)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show planned operations without executing")
    args = parser.parse_args()

    if not args.candidates.exists():
        print(f"ERROR: Candidates file not found: {args.candidates}")
        print("Run select_candidates.py first.")
        sys.exit(1)

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if args.limit:
        candidates = candidates[:args.limit]

    colmap_bin = find_colmap()
    if not colmap_bin:
        print("WARNING: COLMAP not found. Will create placeholder outputs.")
        print("  Install COLMAP for real photogrammetric reconstruction.")

    print(f"Per-building photogrammetry: {len(candidates)} candidates")
    print(f"  Output: {args.output}")
    if colmap_bin:
        print(f"  COLMAP: {colmap_bin}")

    if args.dry_run:
        for c in candidates:
            slug = sanitize_name(c["address"])
            existing = (args.output / slug / "sparse").exists()
            status = "EXISTS" if existing else "PENDING"
            print(f"  [{status}] {c['address']} ({c['photo_count']} photos)")
        return

    args.output.mkdir(parents=True, exist_ok=True)

    results = {"OK": 0, "SKIP": 0, "FAIL": 0, "PLACEHOLDER": 0}
    for i, candidate in enumerate(candidates, 1):
        print(f"\n  [{i}/{len(candidates)}] {candidate['address']} ({candidate['photo_count']} photos)")
        status, msg = process_candidate(
            candidate, args.output, colmap_bin, args.gpu_index, args.skip_existing
        )
        results[status] = results.get(status, 0) + 1
        print(f"    [{status}] {msg}")

    print(f"\nComplete: {results}")


if __name__ == "__main__":
    main()
