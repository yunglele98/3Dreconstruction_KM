#!/usr/bin/env python3
"""Stage 0 ACQUIRE: Ingest iPad LiDAR scans (.usdz, .obj, .ply, .laz).

Copies scan files from an input directory into a structured output directory,
organized by address (derived from filename or parent folder name).

Usage:
    python scripts/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/
    python scripts/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/ --dry-run
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_EXTENSIONS = {".usdz", ".obj", ".ply", ".laz"}


def sanitize_address(name):
    """Convert a filename or folder name into a clean address key."""
    stem = Path(name).stem
    # Replace underscores with spaces, strip extra whitespace
    return stem.replace("_", " ").strip()


def discover_scans(input_dir):
    """Find all scan files in input_dir recursively."""
    scans = []
    for ext in sorted(SCAN_EXTENSIONS):
        scans.extend(sorted(input_dir.rglob(f"*{ext}")))
    return scans


def derive_address(scan_path, input_dir):
    """Derive an address string from the scan file path.

    Strategy: if the scan lives in a subfolder under input_dir, use the
    immediate parent folder name as the address.  Otherwise fall back to
    the filename stem.
    """
    rel = scan_path.relative_to(input_dir)
    if len(rel.parts) > 1:
        return sanitize_address(rel.parts[0])
    return sanitize_address(scan_path.stem)


def ingest_scans(input_dir, output_dir, dry_run=False):
    """Copy scans from input_dir into output_dir organized by address."""
    scans = discover_scans(input_dir)
    print(f"[ACQUIRE] Found {len(scans)} scan file(s) in {input_dir}")

    ingested = 0
    skipped = 0
    manifest = []

    for scan in scans:
        address = derive_address(scan, input_dir)
        address_dir = output_dir / address.replace(" ", "_")
        dest = address_dir / scan.name

        if dest.exists():
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would copy {scan} -> {dest}")
            ingested += 1
            continue

        address_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scan, dest)
        ingested += 1
        manifest.append({
            "address": address,
            "source": str(scan),
            "destination": str(dest),
            "format": scan.suffix.lstrip("."),
            "size_bytes": dest.stat().st_size,
        })

    # Write manifest
    if manifest and not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "ingest_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "source_dir": str(input_dir),
                "scans": manifest,
            }, f, indent=2)
        print(f"[ACQUIRE] Manifest written to {manifest_path}")

    print(f"[ACQUIRE] Ingested {ingested}, skipped {skipped} (already exist)")
    return ingested, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Ingest iPad LiDAR scans into the pipeline."
    )
    parser.add_argument(
        "--input", type=str, default="scans/montreal/",
        help="Input directory containing raw scans (default: scans/montreal/)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ipad_scans/",
        help="Output directory for organized scans (default: data/ipad_scans/)",
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

    ingested, skipped = ingest_scans(input_dir, output_dir, dry_run=args.dry_run)
    if ingested == 0 and skipped == 0:
        print("[WARN] No scan files found. Supported formats:", ", ".join(sorted(SCAN_EXTENSIONS)))


if __name__ == "__main__":
    main()
