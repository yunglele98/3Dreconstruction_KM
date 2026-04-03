#!/usr/bin/env python3
"""Select buildings with enough photos for photogrammetric reconstruction.

Reads the photo index CSV, counts photos per address, and selects
buildings with >= min-views photos as COLMAP reconstruction candidates.

Usage:
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3
    python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3 --output reconstruction_candidates.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DEFAULT = REPO_ROOT / "reconstruction_candidates.json"


def load_photo_index(photo_index_path):
    """Load photo index CSV, return address -> [filenames]."""
    by_address = defaultdict(list)
    if not photo_index_path.exists():
        print(f"WARNING: Photo index not found: {photo_index_path}")
        return by_address
    with open(photo_index_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                by_address[addr].append(fname)
    return by_address


def find_param_file(params_dir, address):
    """Find the param JSON file for a given address."""
    stem = address.replace(" ", "_").replace(",", "")
    param_file = params_dir / f"{stem}.json"
    if param_file.exists():
        return param_file
    # Try case-insensitive search
    for p in params_dir.glob("*.json"):
        if p.name.startswith("_"):
            continue
        if p.stem.replace("_", " ").lower() == address.lower():
            return p
    return None


def is_skipped(param_file):
    """Check if a param file is marked as skipped."""
    try:
        data = json.loads(param_file.read_text(encoding="utf-8"))
        return data.get("skipped", False)
    except (json.JSONDecodeError, OSError):
        return False


def resolve_photo_paths(photo_dir, filenames):
    """Resolve photo filenames to actual paths on disk."""
    resolved = []
    for fname in filenames:
        # Search in photo dir and subdirectories
        direct = photo_dir / fname
        if direct.exists():
            resolved.append(str(direct))
            continue
        matches = list(photo_dir.rglob(fname))
        if matches:
            resolved.append(str(matches[0]))
        else:
            resolved.append(fname)  # keep filename even if not found
    return resolved


def select_candidates(params_dir, photo_dir, min_views, photo_index_path):
    """Select buildings with enough photos for reconstruction."""
    photo_index = load_photo_index(photo_index_path)

    if not photo_index:
        print("No photo index data loaded.")
        return []

    candidates = []
    skipped_count = 0
    below_threshold = 0

    for address, filenames in sorted(photo_index.items()):
        photo_count = len(filenames)

        if photo_count < min_views:
            below_threshold += 1
            continue

        # Find corresponding param file
        param_file = find_param_file(params_dir, address)

        # Skip non-building entries
        if param_file and is_skipped(param_file):
            skipped_count += 1
            continue

        photo_files = resolve_photo_paths(photo_dir, filenames)

        candidate = {
            "address": address,
            "photo_count": photo_count,
            "photo_files": photo_files,
            "param_file": str(param_file) if param_file else None,
        }
        candidates.append(candidate)

    print(f"Photo index: {len(photo_index)} addresses")
    print(f"  Below threshold ({min_views} views): {below_threshold}")
    print(f"  Skipped (non-building): {skipped_count}")
    print(f"  Candidates selected: {len(candidates)}")

    return candidates


def main():
    parser = argparse.ArgumentParser(
        description="Select buildings with enough photos for photogrammetric reconstruction."
    )
    parser.add_argument("--params", type=Path, default=PARAMS_DIR,
                        help="Directory containing building param JSON files")
    parser.add_argument("--photos", type=Path, default=REPO_ROOT / "PHOTOS KENSINGTON",
                        help="Directory containing field photos")
    parser.add_argument("--min-views", type=int, default=3,
                        help="Minimum number of photos required (default: 3)")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help="Output candidates JSON file")
    parser.add_argument("--photo-index", type=Path, default=PHOTO_INDEX,
                        help="Path to photo index CSV")
    args = parser.parse_args()

    if not args.params.exists():
        print(f"ERROR: Params directory not found: {args.params}")
        sys.exit(1)

    candidates = select_candidates(
        args.params, args.photos, args.min_views, args.photo_index
    )

    if not candidates:
        print("No candidates found.")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(candidates)} candidates to {args.output}")


if __name__ == "__main__":
    main()
