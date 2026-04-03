#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Run COLMAP photogrammetry on candidate buildings.

Takes reconstruction_candidates.json and runs COLMAP sparse + dense
reconstruction per building. Outputs point clouds to point_clouds/colmap/.

Usage:
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/
    python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/ --dry-run
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_colmap_pipeline(
    address: str,
    photo_paths: list[str],
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Run COLMAP SfM + MVS for a single building.

    In production: calls COLMAP feature_extractor, exhaustive_matcher,
    mapper, image_undistorter, patch_match_stereo, stereo_fusion.
    Currently a stub.
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

    # Placeholder: create workspace structure
    (building_dir / "sparse").mkdir(exist_ok=True)
    (building_dir / "dense").mkdir(exist_ok=True)

    status = {
        "address": address,
        "photos": photo_paths,
        "sparse_points": 0,
        "dense_points": 0,
        "note": "COLMAP pipeline pending — requires COLMAP installation",
    }
    (building_dir / "colmap_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )

    result["status"] = "workspace_prepared"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run COLMAP photogrammetry")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "point_clouds" / "colmap")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if args.limit > 0:
        candidates = candidates[:args.limit]

    results = []
    for c in candidates:
        result = run_colmap_pipeline(
            c["address"], c.get("photos", []), args.output,
            dry_run=args.dry_run,
        )
        results.append(result)

    manifest_path = args.output / "colmap_manifest.json"
    if not args.dry_run:
        args.output.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Processed {len(results)} buildings")


if __name__ == "__main__":
    main()
