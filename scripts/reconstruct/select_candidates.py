#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Select photogrammetry candidates.

Cross-references params/*.json with the photo index CSV to identify
buildings that have enough views (>= min_views) for multi-view
reconstruction via COLMAP.

Usage:
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3 --street "Augusta Ave"
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_photo_index(index_path: Path) -> dict[str, list[str]]:
    """Load the photo-address index CSV.

    Returns a dict mapping lowercase address → list of filenames.
    """
    addr_photos: dict[str, list[str]] = defaultdict(list)
    with open(index_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip().lower()
            filename = (row.get("filename") or "").strip()
            if addr and filename:
                addr_photos[addr].append(filename)
    return dict(addr_photos)


def select_candidates(
    params_dir: Path,
    photo_index_path: Path,
    audit_path: Path,
    *,
    min_views: int = 3,
    street_filter: str | None = None,
) -> list[dict]:
    """Select buildings eligible for photogrammetric reconstruction.

    Returns list of candidate dicts sorted by photo count (descending).
    """
    photo_index = load_photo_index(photo_index_path)
    candidates = []

    for param_file in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if param_file.name.startswith("_"):
            continue

        data = json.loads(param_file.read_text(encoding="utf-8"))

        # Skip non-building files
        if data.get("skipped"):
            continue

        address = (
            data.get("_meta", {}).get("address")
            or data.get("building_name")
            or param_file.stem.replace("_", " ")
        )
        street = data.get("site", {}).get("street", "")

        if street_filter and street != street_filter:
            continue

        addr_lower = address.lower()
        photos = photo_index.get(addr_lower, [])
        photo_count = len(photos)

        if photo_count < min_views:
            continue

        hcd = data.get("hcd_data", {})
        contributing = (hcd.get("contributing") or "").lower() == "yes"

        candidates.append({
            "address": address,
            "street": street,
            "param_file": str(param_file),
            "photo_count": photo_count,
            "photos": photos,
            "contributing": contributing,
            "construction_date": hcd.get("construction_date", ""),
            "typology": hcd.get("typology", ""),
        })

    # Sort by photo count descending, contributing first
    candidates.sort(key=lambda c: (-int(c["contributing"]), -c["photo_count"]))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Select photogrammetry candidates")
    parser.add_argument("--params", type=Path, default=REPO_ROOT / "params")
    parser.add_argument("--photos", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--street", type=str, default=None, dest="street_filter")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "reconstruction_candidates.json")
    args = parser.parse_args()

    index_path = args.photos / "csv" / "photo_address_index.csv"
    if not index_path.exists():
        print(f"[ERROR] Photo index not found: {index_path}")
        sys.exit(1)

    candidates = select_candidates(
        args.params, index_path, Path("/dev/null"),
        min_views=args.min_views, street_filter=args.street_filter,
    )

    args.output.write_text(
        json.dumps(candidates, indent=2), encoding="utf-8"
    )
    print(f"Selected {len(candidates)} candidates (min {args.min_views} views)")
    for c in candidates[:10]:
        flag = " [contributing]" if c["contributing"] else ""
        print(f"  {c['address']}: {c['photo_count']} photos{flag}")


if __name__ == "__main__":
    main()
