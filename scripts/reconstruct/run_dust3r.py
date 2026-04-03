#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Single/few-view reconstruction via DUSt3R/MASt3R.

For buildings with 1-2 photos (below COLMAP threshold), runs DUSt3R
to produce a coarse point cloud and depth estimate.

Usage:
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2
    python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2 --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_dust3r_single(
    address: str,
    photo_paths: list[str],
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Run DUSt3R on a single building's photos.

    In production: loads DUSt3R model, processes image pair(s), outputs
    point cloud and confidence map.
    """
    safe_name = address.replace(" ", "_")
    building_dir = output_dir / safe_name

    result = {
        "address": address,
        "photo_count": len(photo_paths),
        "output_dir": str(building_dir),
    }

    if dry_run:
        result["status"] = "would_process"
        return result

    building_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "address": address,
        "photos": photo_paths,
        "method": "dust3r",
        "points": 0,
        "note": "DUSt3R pipeline pending — requires DUSt3R installation",
    }
    (building_dir / "dust3r_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result["status"] = "workspace_prepared"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DUSt3R single-view reconstruction")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "point_clouds" / "dust3r")
    parser.add_argument("--max-views", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"DUSt3R reconstruction: max-views={args.max_views}")
    print(f"  Input: {args.input}")
    print(f"  Output: {args.output}")
    if args.dry_run:
        print("  [DRY RUN]")


if __name__ == "__main__":
    main()
