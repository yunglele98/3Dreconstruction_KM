#!/usr/bin/env python3
"""Analyze photo coverage and identify gaps in the dataset.

Reads the photo index CSV and params to compute per-street and per-building
photo coverage statistics, identify gaps, and recommend COLMAP strategies.

Usage:
    python scripts/reconstruct/analyze_photo_coverage.py
    python scripts/reconstruct/analyze_photo_coverage.py --photo-index "PHOTOS KENSINGTON/csv/photo_address_index.csv" --params params/ --output outputs/photo_coverage/
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_INDEX_DEFAULT = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PARAMS_DEFAULT = REPO_ROOT / "params"
OUTPUT_DEFAULT = REPO_ROOT / "outputs" / "photo_coverage"


def load_photo_index(photo_index_path):
    """Load photo index CSV, return address -> [row dicts]."""
    by_address = defaultdict(list)
    if not photo_index_path.exists():
        print(f"WARNING: Photo index not found: {photo_index_path}")
        return by_address
    with open(photo_index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            if addr:
                by_address[addr].append(row)
    return by_address


def load_active_buildings(params_dir):
    """Load all non-skipped, non-metadata building param files."""
    buildings = {}
    if not params_dir.exists():
        return buildings
    for p in sorted(params_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("skipped", False):
            continue
        address = (
            data.get("_meta", {}).get("address")
            or data.get("building_name")
            or p.stem.replace("_", " ")
        )
        street = (data.get("site", {}).get("street") or "").strip()
        buildings[address] = {
            "param_file": str(p),
            "street": street,
            "address": address,
            "hcd_contributing": (
                (data.get("hcd_data", {}).get("contributing") or "").lower() == "yes"
            ),
        }
    return buildings


def get_street_from_address(address, buildings):
    """Get street name for an address, with fallback heuristic."""
    if address in buildings:
        s = buildings[address].get("street", "")
        if s:
            return s
    # Fallback: extract street from address string
    parts = address.split()
    if len(parts) >= 2:
        for i, part in enumerate(parts):
            if not part.replace("-", "").isdigit():
                return " ".join(parts[i:])
    return "Unknown"


def classify_coverage(photo_count):
    """Classify coverage quality based on photo count."""
    if photo_count == 0:
        return "none"
    elif photo_count <= 2:
        return "single_angle"
    elif photo_count <= 5:
        return "limited"
    else:
        return "multi_angle"


def recommend_strategy(avg_photos_per_building, total_photos, building_count):
    """Recommend COLMAP strategy for a street."""
    if building_count == 0:
        return "no_buildings"
    if avg_photos_per_building >= 5 and total_photos >= 15:
        return "block"
    elif avg_photos_per_building >= 3:
        return "per_building"
    elif avg_photos_per_building >= 1:
        return "dust3r"
    else:
        return "parametric_only"


def main():
    parser = argparse.ArgumentParser(
        description="Analyze photo coverage and identify gaps in the dataset."
    )
    parser.add_argument("--photo-index", type=Path, default=PHOTO_INDEX_DEFAULT,
                        help="Path to photo index CSV")
    parser.add_argument("--params", type=Path, default=PARAMS_DEFAULT,
                        help="Directory containing building param JSON files")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help="Output directory for coverage reports")
    args = parser.parse_args()

    if not args.photo_index.exists():
        print(f"ERROR: Photo index not found: {args.photo_index}")
        sys.exit(1)

    print(f"Loading photo index: {args.photo_index}")
    photo_index = load_photo_index(args.photo_index)
    print(f"  {len(photo_index)} addresses with photos")

    print(f"Loading building params: {args.params}")
    buildings = load_active_buildings(args.params)
    print(f"  {len(buildings)} active buildings")

    # Build per-building analysis
    all_addresses = set(buildings.keys()) | set(photo_index.keys())
    building_analysis = []

    for address in sorted(all_addresses):
        photos = photo_index.get(address, [])
        photo_count = len(photos)
        street = get_street_from_address(address, buildings)
        is_active = address in buildings
        is_contributing = buildings.get(address, {}).get("hcd_contributing", False)

        entry = {
            "address": address,
            "street": street,
            "photo_count": photo_count,
            "coverage_quality": classify_coverage(photo_count),
            "has_params": is_active,
            "hcd_contributing": is_contributing,
        }

        if photos:
            entry["photo_files"] = [
                (r.get("filename") or "").strip() for r in photos
            ]

        building_analysis.append(entry)

    # Build per-street analysis
    street_groups = defaultdict(list)
    for b in building_analysis:
        street = b.get("street") or "Unknown"
        if street:
            street_groups[street].append(b)

    street_analysis = []
    for street, entries in sorted(street_groups.items()):
        if street == "Unknown":
            continue
        buildings_count = len([e for e in entries if e["has_params"]])
        with_photos = len([e for e in entries if e["photo_count"] > 0])
        total_photos = sum(e["photo_count"] for e in entries)
        avg_photos = total_photos / buildings_count if buildings_count > 0 else 0

        colmap_viable = len([e for e in entries if e["photo_count"] >= 3])
        dust3r_only = len([e for e in entries if 1 <= e["photo_count"] <= 2])
        no_photos = len([
            e for e in entries if e["photo_count"] == 0 and e["has_params"]
        ])

        strategy = recommend_strategy(avg_photos, total_photos, buildings_count)

        street_analysis.append({
            "street": street,
            "buildings_count": buildings_count,
            "buildings_with_photos": with_photos,
            "coverage_pct": round(
                with_photos / buildings_count * 100, 1
            ) if buildings_count > 0 else 0,
            "total_photos": total_photos,
            "avg_photos_per_building": round(avg_photos, 1),
            "colmap_viable_3plus": colmap_viable,
            "dust3r_only_1_2": dust3r_only,
            "no_photos": no_photos,
            "recommended_strategy": strategy,
        })

    # Sort streets by coverage percentage
    street_analysis.sort(key=lambda s: s["coverage_pct"], reverse=True)

    # Gap analysis
    no_photo_buildings = [
        b for b in building_analysis
        if b["photo_count"] == 0 and b["has_params"]
    ]
    low_photo_buildings = [
        b for b in building_analysis
        if 1 <= b["photo_count"] <= 2 and b["has_params"]
    ]
    colmap_ready = [
        b for b in building_analysis
        if b["photo_count"] >= 3 and b["has_params"]
    ]

    # Priority targets: contributing heritage buildings with few/no photos
    priority_targets = [
        b for b in building_analysis
        if b["hcd_contributing"] and b["photo_count"] < 3
    ]
    priority_targets.sort(key=lambda b: b["photo_count"])

    # Print summary table
    print(f"\n{'Street':<25} {'Bldgs':>6} {'w/Photo':>8} {'Cov%':>6} "
          f"{'Photos':>7} {'Avg':>5} {'COLMAP':>7} {'DUSt3R':>7} "
          f"{'None':>5} {'Strategy':<15}")
    print("-" * 105)
    for s in street_analysis:
        print(f"{s['street']:<25} {s['buildings_count']:>6} "
              f"{s['buildings_with_photos']:>8} {s['coverage_pct']:>5.1f}% "
              f"{s['total_photos']:>7} {s['avg_photos_per_building']:>5.1f} "
              f"{s['colmap_viable_3plus']:>7} {s['dust3r_only_1_2']:>7} "
              f"{s['no_photos']:>5} {s['recommended_strategy']:<15}")

    active_with_photos = len([
        b for b in building_analysis if b["photo_count"] > 0 and b["has_params"]
    ])
    active_total = len([b for b in building_analysis if b["has_params"]])

    print(f"\nOverall:")
    print(f"  Active buildings: {active_total}")
    print(f"  With photos: {active_with_photos} "
          f"({round(active_with_photos / active_total * 100, 1) if active_total else 0}%)")
    print(f"  COLMAP viable (3+): {len(colmap_ready)}")
    print(f"  DUSt3R only (1-2): {len(low_photo_buildings)}")
    print(f"  No photos: {len(no_photo_buildings)}")
    print(f"  Priority targets (contributing, <3 photos): {len(priority_targets)}")

    # Write outputs
    args.output.mkdir(parents=True, exist_ok=True)

    report = {
        "summary": {
            "total_addresses_in_index": len(photo_index),
            "active_buildings": active_total,
            "buildings_with_photos": active_with_photos,
            "coverage_pct": round(
                active_with_photos / active_total * 100, 1
            ) if active_total else 0,
            "colmap_viable": len(colmap_ready),
            "dust3r_only": len(low_photo_buildings),
            "no_photos": len(no_photo_buildings),
            "priority_targets": len(priority_targets),
        },
        "per_street": street_analysis,
        "per_building": building_analysis,
    }

    report_path = args.output / "photo_coverage_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {report_path}")

    gaps = {
        "no_photos": [
            {
                "address": b["address"],
                "street": b["street"],
                "hcd_contributing": b["hcd_contributing"],
            }
            for b in no_photo_buildings
        ],
        "low_photos_1_2": [
            {
                "address": b["address"],
                "street": b["street"],
                "photo_count": b["photo_count"],
                "hcd_contributing": b["hcd_contributing"],
            }
            for b in low_photo_buildings
        ],
        "priority_acquisition_targets": [
            {
                "address": b["address"],
                "street": b["street"],
                "photo_count": b["photo_count"],
            }
            for b in priority_targets
        ],
    }

    gaps_path = args.output / "coverage_gaps.json"
    gaps_path.write_text(
        json.dumps(gaps, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {gaps_path}")


if __name__ == "__main__":
    main()
