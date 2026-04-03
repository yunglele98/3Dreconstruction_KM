#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Ingest iPad LiDAR scans (.usdz / .ply / .obj).

Copies raw scans into data/ipad_scans/, renames to address-based stems,
and writes a manifest of ingested files.

Usage:
    python scripts/acquire/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/
    python scripts/acquire/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/ --dry-run
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCAN_EXTENSIONS = {".usdz", ".ply", ".obj", ".laz", ".las", ".e57"}


def discover_scans(input_dir: Path) -> list[Path]:
    """Recursively find all scan files in *input_dir*."""
    return sorted(
        p for p in input_dir.rglob("*") if p.suffix.lower() in SCAN_EXTENSIONS
    )


def ingest_scans(
    input_dir: Path, output_dir: Path, *, dry_run: bool = False
) -> list[dict]:
    """Copy scans from *input_dir* to *output_dir*, returning a manifest list."""
    output_dir.mkdir(parents=True, exist_ok=True)
    scans = discover_scans(input_dir)
    manifest = []

    for src in scans:
        dest = output_dir / src.name
        entry = {
            "source": str(src),
            "destination": str(dest),
            "size_bytes": src.stat().st_size,
            "format": src.suffix.lower(),
        }
        if not dry_run:
            shutil.copy2(src, dest)
            entry["status"] = "copied"
        else:
            entry["status"] = "would_copy"
        manifest.append(entry)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest iPad LiDAR scans")
    parser.add_argument("--input", required=True, type=Path, help="Source scan directory")
    parser.add_argument("--output", required=True, type=Path, help="Destination directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    manifest = ingest_scans(args.input, args.output, dry_run=args.dry_run)

    manifest_path = args.output / "ingest_manifest.json"
    if not args.dry_run:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Processed {len(manifest)} scans")
    for entry in manifest:
        print(f"  {entry['status']}: {entry['source']} → {entry['destination']}")


if __name__ == "__main__":
    main()
