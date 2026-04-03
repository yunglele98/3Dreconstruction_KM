#!/usr/bin/env python3
"""Stage 0c: Extract reusable architectural elements from iPad scans.

Reads ingested scan bundles from data/ipad_scans/, identifies element types
based on metadata classification, and organizes into the scanned element
library at assets/scanned_elements/.

Requires scan metadata to have scan_type and element_types populated
(done manually via /scan-imported Slack command or direct edit).

Usage:
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/
    python scripts/acquire/acquire_extract_elements.py --input data/ipad_scans/ --output assets/scanned_elements/ --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent

# Element categories matching create_* functions in generate_building.py
ELEMENT_CATEGORIES = {
    "cornices": "create_cornice_band",
    "string_courses": "create_string_courses",
    "voussoirs": "create_voussoirs",
    "brackets": "create_brackets",
    "bargeboards": "create_bargeboard",
    "quoins": "create_quoins",
    "bay_windows": "create_bay_window",
    "windows": "cut_windows",
    "doors": "cut_doors",
    "storefronts": "create_storefront",
    "porches": "create_porch",
    "railings": "create_step_handrails",
    "foundations": "create_foundation",
    "chimney_caps": "create_chimney_caps",
    "dormers": "create_dormer",
    "gable_shingles": "create_gable_shingles",
    "textures": None,
}

ERA_KEYS = ["pre1889", "victorian_1889", "edwardian_1904", "interwar_1914"]

MESH_EXTENSIONS = {".ply", ".obj", ".glb", ".gltf", ".fbx", ".stl"}
TEXTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def load_scan_metadata(scan_dir: Path) -> dict | None:
    """Load metadata.json from a scan directory."""
    meta_path = scan_dir / "metadata.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def extract_from_scan(scan_dir: Path, metadata: dict, output_dir: Path,
                      dry_run: bool = False) -> dict:
    """Extract and organize elements from a classified scan."""
    scan_type = metadata.get("scan_type")
    era = metadata.get("era")
    element_types = metadata.get("element_types", [])

    if not scan_type:
        return {"scan": scan_dir.name, "status": "unclassified"}

    results = {"scan": scan_dir.name, "scan_type": scan_type,
               "era": era, "extracted": []}

    mesh_files = [f for f in scan_dir.iterdir()
                  if f.suffix.lower() in MESH_EXTENSIONS]
    texture_files = [f for f in scan_dir.iterdir()
                     if f.suffix.lower() in TEXTURE_EXTENSIONS]

    if scan_type == "brick_closeup":
        # Textures go to textures/ directory
        dest_dir = output_dir / "textures"
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
        for tex in texture_files:
            dest = dest_dir / tex.name
            if dry_run:
                logger.info("  [DRY-RUN] %s → %s", tex.name, dest)
            else:
                shutil.copy2(tex, dest)
            results["extracted"].append({"file": tex.name, "category": "textures"})

    elif scan_type == "facade_element":
        # Elements organized by_era/<era>/ and by_type/<category>/
        for mesh in mesh_files:
            for element_type in element_types:
                category = element_type if element_type in ELEMENT_CATEGORIES else "misc"

                # by_era
                if era:
                    era_dir = output_dir / "by_era" / era
                    if not dry_run:
                        era_dir.mkdir(parents=True, exist_ok=True)
                    dest_era = era_dir / f"{category}_{mesh.stem}{mesh.suffix}"
                    if dry_run:
                        logger.info("  [DRY-RUN] %s → %s", mesh.name, dest_era)
                    else:
                        shutil.copy2(mesh, dest_era)

                # by_type
                type_dir = output_dir / "by_type" / category
                if not dry_run:
                    type_dir.mkdir(parents=True, exist_ok=True)
                dest_type = type_dir / f"{mesh.stem}_{era or 'unknown'}{mesh.suffix}"
                if dry_run:
                    logger.info("  [DRY-RUN] %s → %s", mesh.name, dest_type)
                else:
                    shutil.copy2(mesh, dest_type)

                results["extracted"].append({
                    "file": mesh.name,
                    "category": category,
                    "era": era,
                })

    elif scan_type in ("full_facade", "storefront", "streetscape", "urban_design"):
        # Copy entire bundle to category directory
        category_dir = output_dir / scan_type
        dest = category_dir / scan_dir.name
        if dry_run:
            logger.info("  [DRY-RUN] %s → %s", scan_dir.name, dest)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            for f in mesh_files + texture_files:
                shutil.copy2(f, dest / f.name)
        results["extracted"].append({
            "category": scan_type,
            "files": len(mesh_files) + len(texture_files),
        })

    return results


def build_catalog(output_dir: Path) -> dict:
    """Build element_catalog.json from extracted elements."""
    catalog = {"elements": [], "generated_at": datetime.now().isoformat()}

    for category_dir in sorted((output_dir / "by_type").iterdir()) if (output_dir / "by_type").exists() else []:
        if not category_dir.is_dir():
            continue
        for mesh_file in sorted(category_dir.iterdir()):
            if mesh_file.suffix.lower() not in MESH_EXTENSIONS:
                continue
            catalog["elements"].append({
                "file": str(mesh_file.relative_to(output_dir)),
                "category": category_dir.name,
                "generator_function": ELEMENT_CATEGORIES.get(category_dir.name),
                "source_scan": mesh_file.stem,
            })

    return catalog


def main():
    parser = argparse.ArgumentParser(description="Extract elements from iPad scans")
    parser.add_argument("--input", type=Path,
                        default=REPO_ROOT / "data" / "ipad_scans",
                        help="Ingested scans directory")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "assets" / "scanned_elements",
                        help="Element library output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.input.is_dir():
        logger.error("Input directory does not exist: %s", args.input)
        return

    scan_dirs = [d for d in sorted(args.input.iterdir())
                 if d.is_dir() and not d.name.startswith("_")]

    if not scan_dirs:
        logger.warning("No scan directories found in %s", args.input)
        return

    logger.info("Processing %d scan(s) from %s", len(scan_dirs), args.input)

    all_results = []
    classified = 0
    for scan_dir in scan_dirs:
        metadata = load_scan_metadata(scan_dir)
        if not metadata:
            logger.warning("  No metadata.json in %s — skipping", scan_dir.name)
            continue

        result = extract_from_scan(scan_dir, metadata, args.output,
                                   dry_run=args.dry_run)
        all_results.append(result)
        if result.get("status") != "unclassified":
            classified += 1
            logger.info("  %s: %d elements extracted", scan_dir.name,
                        len(result.get("extracted", [])))
        else:
            logger.info("  %s: unclassified — set scan_type in metadata.json",
                        scan_dir.name)

    # Build catalog
    if not args.dry_run:
        args.output.mkdir(parents=True, exist_ok=True)
        metadata_dir = args.output / "metadata"
        metadata_dir.mkdir(exist_ok=True)
        catalog = build_catalog(args.output)
        catalog_path = metadata_dir / "element_catalog.json"
        catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        logger.info("\nCatalog: %d elements → %s",
                    len(catalog["elements"]), catalog_path)

    logger.info("Done: %d/%d scans classified and extracted",
                classified, len(scan_dirs))


if __name__ == "__main__":
    main()
