#!/usr/bin/env python3
"""Select buildings with sufficient photo coverage for COLMAP photogrammetry.

Cross-references params/ with photo_address_index.csv to find buildings
with >= min_views geotagged photos. Outputs ranked candidate list.

Usage:
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --street "Augusta Ave"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load photo index CSV, return lowercased address -> [filenames].

    Args:
        index_path: Path to CSV with columns filename, address_or_location, source.

    Returns:
        Dict mapping lowercased address to list of photo filenames.
    """
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


def select_candidates(
    params_dir: Path,
    photo_index_path: Path,
    audit_priority_path: Path,
    min_views: int = 3,
    street_filter: str | None = None,
) -> list[dict]:
    """Select buildings with enough photos for photogrammetry.

    Args:
        params_dir: Directory with building param JSON files.
        photo_index_path: Path to photo_address_index.csv.
        audit_priority_path: Path to visual audit priority JSON (optional boost).
        min_views: Minimum number of photos required.
        street_filter: If set, only include buildings on this street.

    Returns:
        List of candidate dicts sorted by priority (contributing first, then photo count).
    """
    photo_index = load_photo_index(photo_index_path)

    # Load audit priority scores if available
    audit_scores: dict[str, float] = {}
    if audit_priority_path.exists():
        try:
            audit_data = json.loads(audit_priority_path.read_text(encoding="utf-8"))
            for entry in audit_data:
                addr = (entry.get("address") or "").lower()
                if addr:
                    audit_scores[addr] = entry.get("priority_score", 0)
        except (json.JSONDecodeError, OSError):
            pass

    candidates = []
    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            continue

        try:
            data = json.loads(param_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Skip non-buildings
        if data.get("skipped"):
            continue

        address = (
            data.get("_meta", {}).get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )
        street = data.get("site", {}).get("street", "")

        # Street filter
        if street_filter and street_filter.lower() not in street.lower():
            continue

        # Count photos for this address
        photo_count = len(photo_index.get(address.lower(), []))
        photos = photo_index.get(address.lower(), [])

        if photo_count < min_views:
            continue

        contributing = data.get("hcd_data", {}).get("contributing") == "Yes"
        construction_date = data.get("hcd_data", {}).get("construction_date", "")
        audit_score = audit_scores.get(address.lower(), 0)

        candidates.append({
            "address": address,
            "street": street,
            "param_file": str(param_file.name),
            "photo_count": photo_count,
            "photos": photos,
            "contributing": contributing,
            "construction_date": construction_date,
            "audit_score": audit_score,
        })

    # Sort: contributing first, then by photo count descending, then audit score
    candidates.sort(
        key=lambda c: (c["contributing"], c["photo_count"], c["audit_score"]),
        reverse=True,
    )

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Select photogrammetry candidates")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photo-index", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv")
    parser.add_argument("--audit-priority", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit" / "colmap_priority.json")
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--street", type=str, default=None)
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "reconstruction_candidates.json")
    args = parser.parse_args()

    candidates = select_candidates(
        args.params, args.photo_index, args.audit_priority,
        min_views=args.min_views, street_filter=args.street,
    )

    args.output.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Selected {len(candidates)} candidates (min {args.min_views} views)")
    for c in candidates[:10]:
        tag = "[HCD]" if c["contributing"] else "     "
        print(f"  {tag} {c['address']}: {c['photo_count']} photos")

    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")


if __name__ == "__main__":
    main()
