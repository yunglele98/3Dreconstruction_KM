#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Extract architectural elements from iPad LiDAR scans.

Segments scanned meshes into individual elements (cornices, windows, doors,
brackets, etc.) and saves them to the scanned-elements asset library.

Usage:
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

MESH_EXTENSIONS = {".ply", ".obj", ".usdz"}

# Element categories we attempt to segment from scans
ELEMENT_CATEGORIES = [
    "cornice", "bracket", "window_frame", "door_frame",
    "column", "baluster", "finial", "quoin", "voussoir",
    "lintel", "sill", "keystone", "pilaster",
]


def discover_meshes(input_dir: Path) -> list[Path]:
    """Find all mesh files in *input_dir*."""
    return sorted(
        p for p in input_dir.rglob("*") if p.suffix.lower() in MESH_EXTENSIONS
    )


def extract_elements(
    input_dir: Path, output_dir: Path, *, dry_run: bool = False
) -> list[dict]:
    """Extract elements from scanned meshes.

    In production this calls into trimesh / Open3D segmentation.
    Currently a stub that catalogues available meshes and prepares
    the output directory structure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    meshes = discover_meshes(input_dir)
    results = []

    for mesh_path in meshes:
        stem = mesh_path.stem
        element_dir = output_dir / stem
        entry = {
            "source_mesh": str(mesh_path),
            "element_dir": str(element_dir),
            "elements_found": [],
            "status": "would_extract" if dry_run else "pending_segmentation",
        }
        if not dry_run:
            element_dir.mkdir(parents=True, exist_ok=True)
            # Write a placeholder catalog for downstream scripts
            catalog = {
                "source": str(mesh_path),
                "elements": [],
                "note": "Segmentation pending — requires trimesh/Open3D pipeline",
            }
            (element_dir / "catalog.json").write_text(
                json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        results.append(entry)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract elements from LiDAR scans")
    parser.add_argument("--input", required=True, type=Path, help="iPad scan directory")
    parser.add_argument("--output", required=True, type=Path, help="Scanned elements output directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview without extracting")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"[ERROR] Input directory not found: {args.input}")
        sys.exit(1)

    results = extract_elements(args.input, args.output, dry_run=args.dry_run)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Processed {len(results)} meshes")
    for r in results:
        print(f"  {r['status']}: {r['source_mesh']}")


if __name__ == "__main__":
    main()
