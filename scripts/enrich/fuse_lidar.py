#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse iPad LiDAR scan data into building params.

Reads per-building LiDAR clips (.laz/.las) and extracts precise
dimensions (height, width, depth) to merge into params.

Usage:
    python scripts/enrich/fuse_lidar.py --lidar lidar/building/ --params params/
    python scripts/enrich/fuse_lidar.py --lidar lidar/building/ --params params/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIDAR = REPO_ROOT / "data" / "lidar" / "building"
DEFAULT_PARAMS = REPO_ROOT / "params"

LIDAR_EXTENSIONS = {".laz", ".las", ".ply"}


def discover_lidar_files(lidar_dir: Path) -> dict[str, Path]:
    """Map address stems to LiDAR files."""
    files = {}
    for f in lidar_dir.rglob("*"):
        if f.suffix.lower() in LIDAR_EXTENSIONS:
            files[f.stem] = f
    return files


def extract_lidar_dims(lidar_path: Path) -> dict:
    """Extract dimensions from a LiDAR point cloud.

    In production: loads with laspy/open3d, computes bounding box.
    Currently returns placeholder metadata.
    """
    return {
        "lidar_file": str(lidar_path),
        "status": "pending_processing",
        "note": "Requires laspy or open3d for point cloud processing",
    }


def fuse_lidar(
    lidar_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse LiDAR data into params files."""
    lidar_files = discover_lidar_files(lidar_dir)
    stats = {"fused": 0, "no_match": 0, "errors": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue
        data = json.loads(param_file.read_text(encoding="utf-8"))
        if data.get("skipped"):
            continue

        stem = param_file.stem
        lidar_path = lidar_files.get(stem)
        if lidar_path is None:
            stats["no_match"] += 1
            continue

        try:
            lidar_data = extract_lidar_dims(lidar_path)

            if dry_run:
                stats["fused"] += 1
                continue

            data.setdefault("lidar_analysis", {}).update(lidar_data)
            meta = data.setdefault("_meta", {})
            fusion = meta.setdefault("fusion_applied", [])
            if "lidar" not in fusion:
                fusion.append("lidar")

            param_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            stats["fused"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse LiDAR data into params")
    parser.add_argument("--lidar", type=Path, default=DEFAULT_LIDAR)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.lidar.is_dir():
        print(f"[ERROR] LiDAR directory not found: {args.lidar}")
        sys.exit(1)

    stats = fuse_lidar(args.lidar, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}LiDAR fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")


if __name__ == "__main__":
    main()
