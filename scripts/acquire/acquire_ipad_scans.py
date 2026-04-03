#!/usr/bin/env python3
"""Stage 0c: Import iPad LiDAR scans into standardized structure.

Ingests .ply/.obj scans from Polycam, 3D Scanner App, or Scaniverse exports
and organizes them with metadata for downstream element extraction.

Montreal proxy scanning (Hochelaga-Maisonneuve): same-era building stock as
Kensington (1880s-1910s row houses, bay-and-gable, brick). iPad scans provide
reusable cornice/voussoir/bracket libraries, tileable PBR textures, and
geometry validation meshes.

Usage:
    python scripts/acquire/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/
    python scripts/acquire/acquire_ipad_scans.py --input scans/montreal/ --output data/ipad_scans/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MESH_EXTENSIONS = {".ply", ".obj", ".glb", ".gltf", ".fbx", ".stl"}
TEXTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

SCAN_TYPES = {
    "facade_element",  # Cornice, voussoir, bracket, window surround
    "brick_closeup",   # Tileable PBR texture source
    "full_facade",     # Full building facade mesh
    "storefront",      # Commercial ground floor
    "streetscape",     # Panoramic street context
    "urban_design",    # Adaptive reuse, infill, green infrastructure examples
}


def discover_scans(input_dir: Path) -> list[dict]:
    """Walk input directory and identify scan bundles.

    Each subdirectory (or loose mesh file) becomes one scan entry.
    A scan bundle is a directory containing at least one mesh file,
    optionally with texture maps.
    """
    scans = []

    # Check subdirectories first
    for child in sorted(input_dir.iterdir()):
        if child.is_dir():
            meshes = [f for f in child.iterdir() if f.suffix.lower() in MESH_EXTENSIONS]
            textures = [f for f in child.iterdir() if f.suffix.lower() in TEXTURE_EXTENSIONS]
            if meshes:
                scans.append({
                    "name": child.name,
                    "source_dir": str(child),
                    "meshes": [f.name for f in meshes],
                    "textures": [f.name for f in textures],
                    "is_bundle": True,
                })

    # Loose mesh files at top level
    for f in sorted(input_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in MESH_EXTENSIONS:
            # Skip if already captured inside a bundle
            scans.append({
                "name": f.stem,
                "source_dir": str(input_dir),
                "meshes": [f.name],
                "textures": [],
                "is_bundle": False,
            })

    return scans


def ingest_scan(scan: dict, output_dir: Path, dry_run: bool = False) -> dict:
    """Copy a scan bundle into the output directory with metadata."""
    scan_name = scan["name"]
    dest = output_dir / scan_name
    source = Path(scan["source_dir"])

    if dry_run:
        logger.info("  [DRY-RUN] Would copy %s → %s", source, dest)
        return {"name": scan_name, "status": "dry_run", "dest": str(dest)}

    dest.mkdir(parents=True, exist_ok=True)

    copied_files = []
    for mesh_name in scan["meshes"]:
        src = source / mesh_name
        dst = dest / mesh_name
        if src.exists():
            shutil.copy2(src, dst)
            copied_files.append(mesh_name)

    for tex_name in scan["textures"]:
        src = source / tex_name
        dst = dest / tex_name
        if src.exists():
            shutil.copy2(src, dst)
            copied_files.append(tex_name)

    # Write metadata
    metadata = {
        "scan_name": scan_name,
        "imported_at": datetime.now().isoformat(),
        "source_path": str(source),
        "meshes": scan["meshes"],
        "textures": scan["textures"],
        "scan_type": None,  # User classifies via /scan-imported command
        "era": None,
        "element_types": [],
        "notes": "",
    }
    meta_path = dest / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    copied_files.append("metadata.json")

    logger.info("  Imported %s: %d files → %s", scan_name, len(copied_files), dest)
    return {"name": scan_name, "status": "imported", "files": copied_files, "dest": str(dest)}


def main():
    parser = argparse.ArgumentParser(description="Import iPad LiDAR scans")
    parser.add_argument("--input", required=True, type=Path,
                        help="Source directory containing scan exports")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent.parent.parent / "data" / "ipad_scans",
                        help="Destination directory (default: data/ipad_scans/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without copying")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.input.is_dir():
        logger.error("Input directory does not exist: %s", args.input)
        return

    scans = discover_scans(args.input)
    if not scans:
        logger.warning("No scans found in %s", args.input)
        return

    logger.info("Found %d scan(s) in %s", len(scans), args.input)

    results = []
    for scan in scans:
        result = ingest_scan(scan, args.output, dry_run=args.dry_run)
        results.append(result)

    # Write ingest manifest
    if not args.dry_run:
        manifest_path = args.output / "_ingest_manifest.json"
        manifest = {
            "ingested_at": datetime.now().isoformat(),
            "source": str(args.input),
            "scans": results,
            "total": len(results),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    imported = sum(1 for r in results if r["status"] == "imported")
    logger.info("\nDone: %d/%d scans imported", imported, len(scans))


if __name__ == "__main__":
    main()
