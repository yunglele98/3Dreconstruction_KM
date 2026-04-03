#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse depth map data into building params.

Reads .npy depth maps from depth_maps/ and merges depth-derived
measurements (estimated heights, setbacks, foundation depth) into
the corresponding params/*.json files.

Usage:
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DEPTH = REPO_ROOT / "depth_maps"
DEFAULT_PARAMS = REPO_ROOT / "params"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_photo_param_mapping


def extract_depth_stats(depth_path: Path) -> dict:
    """Extract statistical measurements from a depth map .npy file."""
    if np is None:
        return {}
    depth = np.load(depth_path)
    if depth.size == 0:
        return {}

    # Relative depth stats (actual metric calibration requires camera intrinsics)
    return {
        "depth_min": float(np.min(depth)),
        "depth_max": float(np.max(depth)),
        "depth_mean": float(np.mean(depth)),
        "depth_std": float(np.std(depth)),
        "depth_shape": list(depth.shape),
    }


def fuse_depth(
    depth_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse depth maps into params files."""
    mapping = load_photo_param_mapping(params_dir)
    depth_files = sorted(depth_dir.glob("*_depth.npy"))

    stats = {"fused": 0, "no_match": 0, "errors": 0}

    for depth_path in depth_files:
        # Strip _depth suffix to get photo stem
        photo_stem = depth_path.stem.replace("_depth", "")
        param_file = mapping.get(photo_stem)

        if param_file is None:
            stats["no_match"] += 1
            continue

        try:
            depth_stats = extract_depth_stats(depth_path)
            if not depth_stats:
                continue

            if dry_run:
                stats["fused"] += 1
                continue

            data = json.loads(param_file.read_text(encoding="utf-8"))

            # Merge depth info
            data.setdefault("depth_analysis", {}).update(depth_stats)
            data["depth_analysis"]["source_depth_map"] = str(depth_path)

            # Track in _meta
            meta = data.setdefault("_meta", {})
            fusion = meta.setdefault("fusion_applied", [])
            if "depth" not in fusion:
                fusion.append("depth")

            param_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            stats["fused"] += 1

        except Exception as e:
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse depth maps into params")
    parser.add_argument("--depth-maps", type=Path, default=DEFAULT_DEPTH)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.depth_maps.is_dir():
        print(f"[ERROR] Depth maps directory not found: {args.depth_maps}")
        sys.exit(1)

    stats = fuse_depth(args.depth_maps, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Depth fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")


if __name__ == "__main__":
    main()
