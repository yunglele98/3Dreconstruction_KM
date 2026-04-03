#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Run COLMAP photogrammetry on candidate buildings.

Takes reconstruction_candidates.json (from select_candidates.py) and runs
COLMAP sparse + optionally dense reconstruction per building. Outputs point
clouds to point_clouds/colmap/.

Supports:
- GPU lock (single-GPU machine safety)
- Resume (skips buildings with existing sparse models)
- Validation (checks sparse model quality post-run)

Usage:
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --dense
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --limit 5 --dry-run
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _colmap import (
    REPO_ROOT,
    find_colmap,
    acquire_gpu_lock,
    release_gpu_lock,
    run_sparse_reconstruction,
    run_dense_reconstruction,
    export_model_ply,
    validate_sparse_model,
)

PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_DIR_ALT = REPO_ROOT / "PHOTOS KENSINGTON"
DEFAULT_OUTPUT = REPO_ROOT / "point_clouds" / "colmap"


def resolve_photo_path(filename: str) -> Path | None:
    """Find a photo file on disk given its filename."""
    for search_dir in [PHOTO_DIR, PHOTO_DIR_ALT]:
        if not search_dir.exists():
            continue
        # Direct match
        direct = search_dir / filename
        if direct.exists():
            return direct
        # Recursive search
        matches = list(search_dir.rglob(filename))
        if matches:
            return matches[0]
    return None


def prepare_workspace(
    address: str,
    photo_filenames: list[str],
    output_dir: Path,
) -> tuple[Path, Path, int]:
    """Copy photos into a per-building COLMAP workspace.

    Returns (workspace, image_dir, photos_copied).
    """
    safe_name = address.replace(" ", "_").replace(",", "")
    workspace = output_dir / safe_name
    image_dir = workspace / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for fname in photo_filenames:
        src = resolve_photo_path(fname)
        if src is None:
            continue
        dst = image_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
            copied += 1

    return workspace, image_dir, copied


def is_already_reconstructed(workspace: Path) -> bool:
    """Check if this building already has a sparse model."""
    sparse_dir = workspace / "sparse"
    if not sparse_dir.exists():
        return False
    models = list(sparse_dir.iterdir())
    return len(models) > 0


def run_building(
    candidate: dict,
    output_dir: Path,
    colmap_bin: str,
    *,
    dense: bool = False,
    gpu_index: int = 0,
    skip_existing: bool = True,
) -> dict:
    """Run COLMAP reconstruction for a single building."""
    address = candidate["address"]
    photos = candidate.get("photos", [])
    result = {
        "address": address,
        "photo_count": len(photos),
    }

    safe_name = address.replace(" ", "_").replace(",", "")
    workspace = output_dir / safe_name

    # Resume: skip if already done
    if skip_existing and is_already_reconstructed(workspace):
        validation = validate_sparse_model(workspace / "sparse" / "0")
        result["status"] = "skipped_existing"
        result["validation"] = validation
        return result

    # Prepare workspace
    workspace_path, image_dir, copied = prepare_workspace(
        address, photos, output_dir,
    )
    result["workspace"] = str(workspace_path)
    result["photos_copied"] = copied

    if copied < 3:
        result["status"] = "insufficient_photos"
        result["reason"] = f"Only {copied} photos resolved (need 3+)"
        return result

    start = time.time()

    # Sparse reconstruction
    ok, sparse_model, log = run_sparse_reconstruction(
        image_dir, workspace_path, colmap_bin,
        gpu_index=gpu_index,
    )
    result["sparse_log"] = log

    if not ok:
        result["status"] = "sparse_failed"
        result["elapsed_s"] = round(time.time() - start)
        return result

    result["sparse_model"] = sparse_model

    # Validate sparse model
    validation = validate_sparse_model(Path(sparse_model))
    result["validation"] = validation

    # Export sparse PLY
    ply_path = export_model_ply(
        sparse_model, workspace_path / "sparse_cloud.ply", colmap_bin,
    )
    if ply_path:
        result["sparse_ply"] = str(ply_path)
        result["sparse_ply_size_mb"] = round(ply_path.stat().st_size / 1024 / 1024, 2)

    # Dense reconstruction
    if dense and ok:
        ok_dense, ply_dense, dense_log = run_dense_reconstruction(
            sparse_model, image_dir, workspace_path, colmap_bin,
            gpu_index=gpu_index,
        )
        result["dense_log"] = dense_log
        if ok_dense:
            result["dense_ply"] = ply_dense
            result["dense_ply_size_mb"] = round(
                Path(ply_dense).stat().st_size / 1024 / 1024, 2
            )

    result["status"] = "success"
    result["elapsed_s"] = round(time.time() - start)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run COLMAP photogrammetry per building")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dense", action="store_true", help="Also run dense reconstruction")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="Max buildings (0=all)")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if args.limit > 0:
        candidates = candidates[:args.limit]

    if args.dry_run:
        print(f"[DRY RUN] Would process {len(candidates)} buildings")
        for c in candidates[:10]:
            print(f"  {c['address']}: {c['photo_count']} photos")
        return

    colmap_bin = find_colmap()
    if not colmap_bin:
        print("[ERROR] COLMAP not found. Install COLMAP or add to PATH.")
        sys.exit(1)

    # Acquire GPU lock
    if not acquire_gpu_lock("run_photogrammetry"):
        print("[ERROR] GPU is locked by another process. Wait or remove .gpu_lock")
        sys.exit(1)

    try:
        results = []
        total_start = time.time()

        for i, candidate in enumerate(candidates, 1):
            print(f"\n[{i}/{len(candidates)}] {candidate['address']} "
                  f"({candidate['photo_count']} photos)")

            result = run_building(
                candidate, args.output, colmap_bin,
                dense=args.dense, gpu_index=args.gpu_index,
                skip_existing=args.skip_existing,
            )
            results.append(result)
            print(f"  → {result['status']}")

        total_elapsed = round(time.time() - total_start)
    finally:
        release_gpu_lock()

    # Write manifest
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped_existing"),
        "failed": sum(1 for r in results if r["status"] in ("sparse_failed", "insufficient_photos")),
        "total_elapsed_s": total_elapsed,
        "results": results,
    }
    manifest_path = args.output / "colmap_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nDone: {manifest['success']} success, {manifest['skipped']} skipped, "
          f"{manifest['failed']} failed in {total_elapsed}s")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
