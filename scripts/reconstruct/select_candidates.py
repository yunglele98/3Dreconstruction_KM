#!/usr/bin/env python3
"""Select COLMAP photogrammetry candidates based on photo availability.

Scans params/ for buildings with 3+ matched photos and ranks them by
photo count, heritage contribution status, and visual audit gap score.

Usage:
    python scripts/reconstruct/select_candidates.py
    python scripts/reconstruct/select_candidates.py --min-views 3 --output candidates.json
    python scripts/reconstruct/select_candidates.py --street "Augusta Ave"
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_DIR = REPO_ROOT / "params"
PHOTO_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTO_INDEX = REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"
AUDIT_REPORT = REPO_ROOT / "outputs" / "visual_audit" / "audit_report_merged.json"
OUTPUT_DEFAULT = REPO_ROOT / "outputs" / "reconstruction_candidates.json"


def load_photo_index(index_path: Path) -> dict:
    """Load photo-to-address mapping from CSV index.

    Returns dict of normalized_address -> list of photo filenames.
    """
    import csv
    counts = defaultdict(list)
    if not index_path.exists():
        return counts
    with open(index_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                counts[addr.lower()].append(fname)
    return counts


def load_audit_scores(audit_path: Path) -> dict:
    """Load gap scores from merged audit report."""
    if not audit_path.exists():
        return {}
    try:
        data = json.loads(audit_path.read_text(encoding="utf-8"))
        scores = {}
        for entry in data.get("buildings", data.get("results", [])):
            if isinstance(entry, dict):
                addr = entry.get("address", "")
                score = entry.get("fused_gap_score", entry.get("gap_score", 0))
                scores[addr] = score
        return scores
    except (json.JSONDecodeError, OSError):
        return {}


def select_candidates(
    params_dir: Path,
    photo_index_path: Path,
    audit_path: Path,
    min_views: int = 3,
    street_filter: str = "",
) -> list:
    """Select and rank COLMAP candidates."""
    photo_index = load_photo_index(photo_index_path)
    audit_scores = load_audit_scores(audit_path)
    candidates = []

    for f in sorted(params_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            params = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if params.get("skipped"):
            continue

        address = params.get("_meta", {}).get("address", f.stem.replace("_", " "))
        street = params.get("site", {}).get("street", "")

        if street_filter and street_filter.lower() not in street.lower():
            continue

        # Count photos from the CSV index (multiple views of same building)
        addr_lower = address.lower()
        matched_photos = list(photo_index.get(addr_lower, []))

        # Also check partial matches (e.g. "106 Bellevue" in "106 Bellevue Ave")
        if not matched_photos:
            for idx_addr, photos in photo_index.items():
                if addr_lower in idx_addr or idx_addr in addr_lower:
                    for p in photos:
                        if p not in matched_photos:
                            matched_photos.append(p)

        # Add from param observations if not already counted
        po = params.get("photo_observations", {})
        if isinstance(po, dict) and po.get("photo"):
            p = po["photo"]
            if p not in matched_photos:
                matched_photos.append(p)
        dfa = params.get("deep_facade_analysis", {})
        if isinstance(dfa, dict) and dfa.get("source_photo"):
            src = dfa["source_photo"]
            if src not in matched_photos:
                matched_photos.append(src)

        photo_count = len(matched_photos)
        if photo_count < min_views:
            continue

        # Heritage contribution status
        hcd = params.get("hcd_data", {})
        contributing = (hcd.get("contributing") or "").lower() == "yes"
        era = hcd.get("construction_date", "")

        # Gap score (higher = worse quality = higher priority for reconstruction)
        gap_score = audit_scores.get(address, 0)

        # Priority score: contributing x3, gap_score weight, photo bonus
        priority = (3.0 if contributing else 1.0) * max(gap_score, 1) + photo_count * 0.5

        candidates.append({
            "address": address,
            "file": f.name,
            "street": street,
            "photo_count": photo_count,
            "photos": matched_photos[:10],
            "contributing": contributing,
            "era": era,
            "gap_score": gap_score,
            "priority_score": round(priority, 2),
            "typology": hcd.get("typology", ""),
            "has_photogrammetric_mesh": params.get("_meta", {}).get("has_photogrammetric_mesh", False),
        })

    # Sort by priority descending
    candidates.sort(key=lambda c: c["priority_score"], reverse=True)
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Select COLMAP photogrammetry candidates.")
    parser.add_argument("--params", type=Path, default=PARAMS_DIR)
    parser.add_argument("--photo-index", type=Path, default=PHOTO_INDEX)
    parser.add_argument("--audit", type=Path, default=AUDIT_REPORT)
    parser.add_argument("--min-views", type=int, default=3)
    parser.add_argument("--street", type=str, default="")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    candidates = select_candidates(
        args.params, args.photo_index, args.audit,
        min_views=args.min_views, street_filter=args.street,
    )

    # Group by street for summary
    by_street = defaultdict(int)
    for c in candidates:
        by_street[c["street"]] += 1

    result = {
        "min_views": args.min_views,
        "total_candidates": len(candidates),
        "by_street": dict(sorted(by_street.items(), key=lambda x: -x[1])),
        "candidates": candidates,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"COLMAP candidates: {len(candidates)} buildings with >= {args.min_views} photos")
    print(f"Top streets:")
    for street, count in sorted(by_street.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:4d}  {street}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
