#!/usr/bin/env python3
"""Fuse depth maps from Stage 1 into building params.

Reads depth map .npy files, estimates facade setbacks, foundation heights,
and eave overhangs. Updates params/*.json depth_notes and roof_detail.

Usage:
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
    python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/ --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV, return lowercased address -> [filenames]."""
    from collections import defaultdict
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


def analyze_depth_map(depth_path: Path) -> dict:
    """Extract architectural measurements from a depth map.

    Analyzes vertical depth profile to estimate:
    - setback (relative depth of facade from street)
    - foundation height (bottom band depth change)
    - eave overhang (top band depth change)
    """
    depth = np.load(depth_path)
    h, w = depth.shape

    # Vertical profile (average across horizontal center 60%)
    x_start = int(w * 0.2)
    x_end = int(w * 0.8)
    center_strip = depth[:, x_start:x_end]
    v_profile = np.mean(center_strip, axis=1)

    # Foundation: bottom 10% depth gradient
    bottom_band = v_profile[int(h * 0.9):]
    foundation_depth_change = float(np.std(bottom_band))

    # Eave: top 10% depth gradient
    top_band = v_profile[:int(h * 0.1)]
    eave_depth_change = float(np.std(top_band))

    # Setback: median depth of central facade region
    facade_region = depth[int(h * 0.2):int(h * 0.8), x_start:x_end]
    setback_estimate = float(np.median(facade_region))

    # Estimate foundation height (ratio of bottom gradient to total)
    foundation_height_est = max(0.2, min(0.8, foundation_depth_change * 3.0))

    # Estimate eave overhang from top gradient
    eave_overhang_est = max(150, min(600, int(eave_depth_change * 2000)))

    return {
        "setback_m_est": round(setback_estimate * 3.0, 2),  # Scale to metres
        "foundation_height_m_est": round(foundation_height_est, 2),
        "eave_overhang_mm_est": eave_overhang_est,
        "depth_map_stats": {
            "mean": round(float(np.mean(depth)), 4),
            "std": round(float(np.std(depth)), 4),
            "min": round(float(np.min(depth)), 4),
            "max": round(float(np.max(depth)), 4),
        },
    }


def fuse_depth_into_params(
    depth_maps_dir: Path,
    params_dir: Path,
    photo_index_path: Path,
    apply: bool = False,
) -> dict:
    """Fuse depth map analysis into building params.

    Args:
        depth_maps_dir: Directory with .npy depth maps.
        params_dir: Directory with building param JSON files.
        photo_index_path: Path to photo address index CSV.
        apply: If True, write changes to param files.

    Returns:
        Stats dict.
    """
    photo_index = load_photo_index(photo_index_path)
    stats = {"updated": 0, "skipped": 0, "no_depth": 0}

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

        # Check if already fused
        meta = data.get("_meta", {})
        if "depth" in (meta.get("fusion_applied") or []):
            stats["skipped"] += 1
            continue

        address = (
            meta.get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )

        # Find matching photos
        photos = photo_index.get(address.lower(), [])
        if not photos:
            stats["no_depth"] += 1
            continue

        # Find depth maps for these photos
        depth_analyses = []
        for photo in photos:
            stem = Path(photo).stem
            depth_path = depth_maps_dir / f"{stem}.npy"
            if depth_path.exists():
                try:
                    analysis = analyze_depth_map(depth_path)
                    depth_analyses.append(analysis)
                except Exception as e:
                    logger.warning(f"Error analyzing {depth_path}: {e}")

        if not depth_analyses:
            stats["no_depth"] += 1
            continue

        # Average measurements across photos
        avg_setback = np.mean([a["setback_m_est"] for a in depth_analyses])
        avg_foundation = np.mean([a["foundation_height_m_est"] for a in depth_analyses])
        avg_eave = int(np.mean([a["eave_overhang_mm_est"] for a in depth_analyses]))

        # Update depth_notes (only fill missing)
        if "deep_facade_analysis" not in data:
            data["deep_facade_analysis"] = {}
        if "depth_notes" not in data["deep_facade_analysis"]:
            data["deep_facade_analysis"]["depth_notes"] = {}

        dn = data["deep_facade_analysis"]["depth_notes"]
        if "setback_m_est" not in dn:
            dn["setback_m_est"] = round(float(avg_setback), 2)
        if "foundation_height_m_est" not in dn:
            dn["foundation_height_m_est"] = round(float(avg_foundation), 2)
        if "eave_overhang_mm_est" not in dn:
            dn["eave_overhang_mm_est"] = avg_eave

        # Update roof_detail eave overhang
        if "roof_detail" not in data:
            data["roof_detail"] = {}
        if "eave_overhang_mm" not in data["roof_detail"]:
            data["roof_detail"]["eave_overhang_mm"] = avg_eave

        # Track fusion
        if "_meta" not in data:
            data["_meta"] = {}
        if "fusion_applied" not in data["_meta"]:
            data["_meta"]["fusion_applied"] = []
        if "depth" not in data["_meta"]["fusion_applied"]:
            data["_meta"]["fusion_applied"].append("depth")

        if apply:
            param_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        stats["updated"] += 1
        logger.info(f"  {address}: setback={avg_setback:.2f}m, "
                     f"foundation={avg_foundation:.2f}m, eave={avg_eave}mm")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fuse depth maps into params")
    parser.add_argument("--depth-maps", type=Path, default=REPO_ROOT / "depth_maps")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = fuse_depth_into_params(
        args.depth_maps, args.params, args.photo_index, args.apply
    )
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"Depth fusion ({mode}): {stats}")


if __name__ == "__main__":
    main()
