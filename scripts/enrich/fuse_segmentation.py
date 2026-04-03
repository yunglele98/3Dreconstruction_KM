#!/usr/bin/env python3
"""Stage 3 — ENRICH: Fuse facade segmentation results into building params.

Reads per-photo element JSON from segmentation/ and merges detected
element counts (windows, doors, decorative features) into params.

Usage:
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SEG = REPO_ROOT / "segmentation"
DEFAULT_PARAMS = REPO_ROOT / "params"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_photo_param_mapping


def load_segmentation(seg_dir: Path) -> dict:
    """Load the elements.json from a segmentation output directory."""
    elements_path = seg_dir / "elements.json"
    if not elements_path.exists():
        return {}
    return json.loads(elements_path.read_text(encoding="utf-8"))


def count_elements(seg_data: dict) -> dict[str, int]:
    """Count detected elements by class."""
    counts: dict[str, int] = {}
    for det in seg_data.get("detections", []):
        cls = det.get("class", "unknown")
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def fuse_segmentation(
    seg_dir: Path, params_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fuse segmentation results into params files."""
    mapping = load_photo_param_mapping(params_dir)
    stats = {"fused": 0, "no_match": 0, "errors": 0}

    for photo_dir in sorted(seg_dir.iterdir()):
        if not photo_dir.is_dir():
            continue

        photo_stem = photo_dir.name
        param_file = mapping.get(photo_stem)
        if param_file is None:
            stats["no_match"] += 1
            continue

        try:
            seg_data = load_segmentation(photo_dir)
            if not seg_data:
                continue

            element_counts = count_elements(seg_data)
            if not element_counts:
                continue

            if dry_run:
                stats["fused"] += 1
                continue

            data = json.loads(param_file.read_text(encoding="utf-8"))

            data.setdefault("segmentation_analysis", {}).update({
                "element_counts": element_counts,
                "source_photo": photo_stem,
                "model": seg_data.get("model", ""),
            })

            meta = data.setdefault("_meta", {})
            fusion = meta.setdefault("fusion_applied", [])
            if "segmentation" not in fusion:
                fusion.append("segmentation")

            param_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            stats["fused"] += 1

        except Exception:
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse segmentation into params")
    parser.add_argument("--segmentation", type=Path, default=DEFAULT_SEG)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.segmentation.is_dir():
        print(f"[ERROR] Segmentation directory not found: {args.segmentation}")
        sys.exit(1)

    stats = fuse_segmentation(args.segmentation, args.params, dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Segmentation fusion: {stats['fused']} fused, "
          f"{stats['no_match']} unmatched, {stats['errors']} errors")


if __name__ == "__main__":
    main()
