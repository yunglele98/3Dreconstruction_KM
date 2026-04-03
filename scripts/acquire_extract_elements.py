#!/usr/bin/env python3
"""Stage 0 ACQUIRE: Extract architectural elements from iPad LiDAR scans.

Reads ingested scan files and classifies them into element categories
(windows, doors, cornices, etc.) based on filename keywords or companion
metadata JSON files.  Outputs organized element files by type.

Usage:
    python scripts/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
    python scripts/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/ --dry-run
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_EXTENSIONS = {".usdz", ".obj", ".ply", ".laz"}

# Keywords mapped to element categories
ELEMENT_KEYWORDS = {
    "windows": ["window", "sash", "casement", "glazing", "pane"],
    "doors": ["door", "entrance", "entry", "portal", "doorway"],
    "cornices": ["cornice", "cornice_band", "dentil", "modillion"],
    "columns": ["column", "pilaster", "post", "pier"],
    "brackets": ["bracket", "corbel", "console"],
    "lintels": ["lintel", "voussoir", "arch", "keystone"],
    "railings": ["railing", "handrail", "balustrade", "banister"],
    "trim": ["trim", "moulding", "molding", "fascia", "casing"],
    "storefronts": ["storefront", "shopfront", "display_window"],
    "roofing": ["roof", "shingle", "gable", "dormer", "chimney"],
    "foundations": ["foundation", "base", "plinth", "sill"],
    "misc": [],  # catch-all
}


def classify_element(filename, metadata=None):
    """Determine element category from filename keywords or metadata.

    Returns the category string (e.g. 'windows', 'doors').
    """
    name_lower = filename.lower()

    # Check metadata first if available
    if metadata and isinstance(metadata, dict):
        cat = (metadata.get("element_type") or metadata.get("category") or "").lower()
        for category, keywords in ELEMENT_KEYWORDS.items():
            if category == "misc":
                continue
            if cat in keywords or cat == category:
                return category

    # Fall back to filename keyword matching
    for category, keywords in ELEMENT_KEYWORDS.items():
        if category == "misc":
            continue
        for kw in keywords:
            if kw in name_lower:
                return category

    return "misc"


def load_metadata(scan_path):
    """Try to load a companion .json metadata file for a scan."""
    meta_path = scan_path.with_suffix(".json")
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def discover_scans(input_dir):
    """Find all scan files recursively."""
    scans = []
    for ext in sorted(SCAN_EXTENSIONS):
        scans.extend(sorted(input_dir.rglob(f"*{ext}")))
    return scans


def extract_elements(input_dir, output_dir, dry_run=False):
    """Classify and organize scanned elements by type."""
    scans = discover_scans(input_dir)
    print(f"[ACQUIRE] Found {len(scans)} scan file(s) in {input_dir}")

    counts = {}
    skipped = 0
    catalog = []

    for scan in scans:
        metadata = load_metadata(scan)
        category = classify_element(scan.name, metadata)

        dest_dir = output_dir / category
        dest = dest_dir / scan.name

        if dest.exists():
            skipped += 1
            continue

        counts[category] = counts.get(category, 0) + 1

        if dry_run:
            print(f"  [DRY-RUN] {scan.name} -> {category}/")
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scan, dest)

        # Copy companion metadata if present
        if metadata:
            meta_dest = dest.with_suffix(".json")
            with open(meta_dest, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

        # Derive address from parent folder name
        rel = scan.relative_to(input_dir)
        address = rel.parts[0].replace("_", " ") if len(rel.parts) > 1 else "unknown"

        catalog.append({
            "element_id": f"{category}_{counts[category]:04d}",
            "category": category,
            "source_file": str(scan),
            "destination": str(dest),
            "address": address,
            "format": scan.suffix.lstrip("."),
            "has_metadata": metadata is not None,
        })

    # Write element catalog
    if catalog and not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        catalog_path = output_dir / "element_catalog.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump({
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "source_dir": str(input_dir),
                "counts_by_category": counts,
                "elements": catalog,
            }, f, indent=2)
        print(f"[ACQUIRE] Catalog written to {catalog_path}")

    total = sum(counts.values())
    print(f"[ACQUIRE] Extracted {total} element(s) into {len(counts)} categories, skipped {skipped} (already exist)")
    for cat, n in sorted(counts.items()):
        print(f"  {cat}: {n}")
    return total, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Extract architectural elements from iPad LiDAR scans."
    )
    parser.add_argument(
        "--input", type=str, default="data/ipad_scans/",
        help="Input directory with ingested scans (default: data/ipad_scans/)",
    )
    parser.add_argument(
        "--output", type=str, default="assets/scanned_elements/",
        help="Output directory for organized elements (default: assets/scanned_elements/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without copying files.",
    )
    args = parser.parse_args()

    input_dir = (REPO_ROOT / args.input).resolve()
    output_dir = (REPO_ROOT / args.output).resolve()

    if not input_dir.exists():
        print(f"[ERROR] Input directory does not exist: {input_dir}")
        sys.exit(1)

    extract_elements(input_dir, output_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
