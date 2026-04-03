#!/usr/bin/env python3
"""Stage 2 — RECONSTRUCT: Extract architectural elements from per-building meshes.

Uses segmentation masks to identify and extract individual elements
(windows, doors, cornices) from photogrammetric meshes for the scanned
element library.

Usage:
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/
    python scripts/reconstruct/extract_elements.py --meshes meshes/per_building/ --segmentation segmentation/ --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MESHES = REPO_ROOT / "meshes" / "per_building"
DEFAULT_SEG = REPO_ROOT / "segmentation"
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "elements"


def extract_from_mesh(
    mesh_path: Path,
    segmentation_dir: Path,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Extract elements from a single building mesh.

    In production: loads mesh + segmentation masks, segments individual
    elements, saves to element library.
    """
    stem = mesh_path.stem
    element_dir = output_dir / stem

    result = {
        "mesh": str(mesh_path),
        "element_dir": str(element_dir),
        "elements_extracted": 0,
    }

    if dry_run:
        result["status"] = "would_extract"
    else:
        element_dir.mkdir(parents=True, exist_ok=True)
        catalog = {
            "source_mesh": str(mesh_path),
            "elements": [],
            "note": "Element extraction pending — requires mesh segmentation pipeline",
        }
        (element_dir / "catalog.json").write_text(
            json.dumps(catalog, indent=2), encoding="utf-8"
        )
        result["status"] = "workspace_prepared"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract elements from meshes")
    parser.add_argument("--meshes", type=Path, default=DEFAULT_MESHES)
    parser.add_argument("--segmentation", type=Path, default=DEFAULT_SEG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.meshes.is_dir():
        print(f"[ERROR] Meshes directory not found: {args.meshes}")
        sys.exit(1)

    prefix = "[DRY RUN] " if args.dry_run else ""
    meshes = list(args.meshes.glob("*.obj"))
    print(f"{prefix}Processing {len(meshes)} meshes")


if __name__ == "__main__":
    main()
