#!/usr/bin/env python3
"""Fuse facade segmentation results into building params.

Reads per-photo segmentation JSONs from Stage 1 and updates
windows_detail, doors_detail, and storefront fields in params.

Usage:
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
    python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/ --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Protected fields that segmentation must never overwrite
PROTECTED = {"total_height_m", "facade_width_m", "facade_depth_m",
             "site", "city_data", "hcd_data"}


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV, return lowercased address -> [filenames]."""
    by_address: dict[str, list[str]] = defaultdict(list)
    if not index_path.exists():
        return dict(by_address)
    with open(index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr.lower()].append(fname)
    return dict(by_address)


def analyze_segmentation(seg_path: Path) -> dict:
    """Extract architectural element counts from segmentation JSON.

    Returns counts and positions of detected facade elements.
    """
    data = json.loads(seg_path.read_text(encoding="utf-8"))
    elements = data.get("elements", [])
    img_h = data.get("height", 1)

    counts = defaultdict(int)
    for elem in elements:
        cls = elem.get("class", "unknown")
        counts[cls] += 1

    # Estimate window counts per floor from vertical positions
    windows_by_floor = defaultdict(int)
    for elem in elements:
        if elem.get("class") != "window":
            continue
        bbox = elem.get("bbox", [0, 0, 0, 0])
        # Vertical center of window
        y_center = (bbox[1] + bbox[3]) / 2 / img_h
        if y_center > 0.7:
            windows_by_floor[0] += 1  # ground floor
        elif y_center > 0.35:
            windows_by_floor[1] += 1  # second floor
        else:
            windows_by_floor[2] += 1  # third floor / attic

    has_storefront = counts.get("storefront", 0) > 0
    door_count = counts.get("door", 0)

    return {
        "element_counts": dict(counts),
        "windows_by_floor": dict(windows_by_floor),
        "has_storefront": has_storefront,
        "door_count": door_count,
        "total_elements": sum(counts.values()),
    }


def fuse_segmentation_into_params(
    segmentation_dir: Path,
    params_dir: Path,
    photo_index_path: Path,
    apply: bool = False,
) -> dict:
    """Fuse segmentation analysis into building params.

    Only updates fields that are missing or clearly less detailed than
    the segmentation-derived values. Never overwrites protected fields.
    """
    photo_index = load_photo_index(photo_index_path)
    stats = {"updated": 0, "skipped": 0, "no_seg": 0}

    for param_file in sorted(params_dir.glob("*.json")):
        if param_file.name.startswith("_"):
            continue

        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("skipped"):
            stats["skipped"] += 1
            continue

        meta = data.get("_meta", {})
        if "segmentation" in (meta.get("fusion_applied") or []):
            stats["skipped"] += 1
            continue

        address = (
            meta.get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )

        photos = photo_index.get(address.lower(), [])
        if not photos:
            stats["no_seg"] += 1
            continue

        # Find segmentation results
        all_analyses = []
        for photo in photos:
            stem = Path(photo).stem
            seg_path = segmentation_dir / f"{stem}_segments.json"
            if seg_path.exists():
                try:
                    analysis = analyze_segmentation(seg_path)
                    all_analyses.append(analysis)
                except Exception as e:
                    logger.warning(f"Error analyzing {seg_path}: {e}")

        if not all_analyses:
            stats["no_seg"] += 1
            continue

        # Use the analysis with most detected elements
        best = max(all_analyses, key=lambda a: a["total_elements"])

        changed = False

        # Update window counts if segmentation found more detail
        if best["windows_by_floor"]:
            floors = data.get("floors", 1)
            current_wpf = data.get("windows_per_floor", [])
            seg_wpf = [best["windows_by_floor"].get(i, 0) for i in range(floors)]

            # Only update if segmentation has non-zero counts and current is generic
            if any(w > 0 for w in seg_wpf):
                if not current_wpf or all(w == current_wpf[0] for w in current_wpf):
                    data["windows_per_floor"] = seg_wpf[:floors]
                    changed = True

        # Update storefront detection
        if best["has_storefront"] and not data.get("has_storefront"):
            data["has_storefront"] = True
            changed = True

        # Update door count if currently 0 or 1
        if best["door_count"] > 0 and data.get("door_count", 0) <= 1:
            data["door_count"] = best["door_count"]
            changed = True

        if changed:
            if "_meta" not in data:
                data["_meta"] = {}
            if "fusion_applied" not in data["_meta"]:
                data["_meta"]["fusion_applied"] = []
            if "segmentation" not in data["_meta"]["fusion_applied"]:
                data["_meta"]["fusion_applied"].append("segmentation")

            if apply:
                param_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            stats["updated"] += 1
        else:
            stats["skipped"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fuse segmentation into params")
    parser.add_argument("--segmentation", type=Path, default=REPO_ROOT / "segmentation")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = fuse_segmentation_into_params(
        args.segmentation, args.params, args.photo_index, args.apply
    )
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"Segmentation fusion ({mode}): {stats}")


if __name__ == "__main__":
    main()
