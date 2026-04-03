#!/usr/bin/env python3
"""Build unified search index across all asset libraries.

Scans assets/external/ and assets/scanned_elements/ to produce a single
asset_index.json for the generator fallback chain (scan → library → procedural).

Usage:
    python scripts/acquire/build_asset_index.py
    python scripts/acquire/build_asset_index.py --sources assets/external/ --output assets/asset_index.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent

MESH_EXTENSIONS = {".ply", ".obj", ".glb", ".gltf", ".fbx", ".stl"}
TEXTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr"}
PBR_MAP_KEYWORDS = {
    "albedo", "diffuse", "color", "colour", "basecolor",
    "normal", "nor",
    "roughness", "rough",
    "metallic", "metalness",
    "ao", "ambientocclusion", "occlusion",
    "displacement", "disp", "height",
    "opacity", "alpha",
}

# Map directory/tag names to element categories
ELEMENT_TYPE_MAP = {
    "brick": "brick_wall",
    "bricks": "brick_wall",
    "stone": "stone_wall",
    "concrete": "concrete",
    "wood": "wood_trim",
    "plaster": "plaster",
    "roofing": "roof",
    "metal": "metal",
    "cornice": "cornice",
    "window": "window",
    "door": "door",
    "bracket": "bracket",
    "voussoir": "voussoir",
    "column": "column",
    "railing": "railing",
}


def classify_pbr_maps(directory: Path) -> dict:
    """Identify PBR map files in a directory."""
    maps = {}
    for f in directory.iterdir():
        if f.suffix.lower() not in TEXTURE_EXTENSIONS:
            continue
        stem_lower = f.stem.lower()
        for keyword in PBR_MAP_KEYWORDS:
            if keyword in stem_lower:
                # Normalize to standard names
                if keyword in ("albedo", "diffuse", "color", "colour", "basecolor"):
                    maps["albedo"] = f.name
                elif keyword in ("normal", "nor"):
                    maps["normal"] = f.name
                elif keyword in ("roughness", "rough"):
                    maps["roughness"] = f.name
                elif keyword in ("metallic", "metalness"):
                    maps["metallic"] = f.name
                elif keyword in ("ao", "ambientocclusion", "occlusion"):
                    maps["ao"] = f.name
                elif keyword in ("displacement", "disp", "height"):
                    maps["displacement"] = f.name
                elif keyword in ("opacity", "alpha"):
                    maps["opacity"] = f.name
                break
    return maps


def infer_element_type(path: Path) -> str | None:
    """Guess element type from path components."""
    parts = str(path).lower().replace("\\", "/")
    for keyword, element in ELEMENT_TYPE_MAP.items():
        if keyword in parts:
            return element
    return None


def infer_source(path: Path) -> str:
    """Determine asset source from path."""
    parts = str(path).lower().replace("\\", "/")
    for source in ["megascans", "polyhaven", "ambientcg", "kenney",
                    "sketchfab", "blendswap", "kitbash3d"]:
        if source in parts:
            return source
    if "scanned_elements" in parts:
        return "scanned"
    return "unknown"


def scan_directory(base_dir: Path, assets_root: Path) -> list[dict]:
    """Recursively scan a directory for assets."""
    entries = []

    if not base_dir.exists():
        return entries

    for item in sorted(base_dir.rglob("*")):
        if not item.is_dir():
            continue

        meshes = [f for f in item.iterdir()
                  if f.suffix.lower() in MESH_EXTENSIONS]
        pbr_maps = classify_pbr_maps(item)

        if not meshes and not pbr_maps:
            continue

        rel_path = str(item.relative_to(assets_root))
        source = infer_source(item)
        element = infer_element_type(item)

        asset_type = "mesh" if meshes else "surface"
        if meshes and pbr_maps:
            asset_type = "mesh+surface"

        entry = {
            "id": f"{source}_{item.name}",
            "source": source,
            "type": asset_type,
            "element": element,
            "path": rel_path,
        }

        if meshes:
            entry["mesh_files"] = [m.name for m in meshes]
        if pbr_maps:
            entry["has_normal"] = "normal" in pbr_maps
            entry["has_roughness"] = "roughness" in pbr_maps
            entry["has_ao"] = "ao" in pbr_maps
            entry["has_displacement"] = "displacement" in pbr_maps
            entry["files"] = pbr_maps

        entries.append(entry)

    return entries


def main():
    parser = argparse.ArgumentParser(description="Build unified asset search index")
    parser.add_argument("--sources", type=Path, default=REPO_ROOT / "assets",
                        help="Root assets directory to scan")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "assets" / "asset_index.json",
                        help="Output index file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Scanning %s for assets...", args.sources)

    all_assets = []

    # Scan external libraries
    external_dir = args.sources / "external"
    if external_dir.exists():
        for lib_dir in sorted(external_dir.iterdir()):
            if lib_dir.is_dir():
                entries = scan_directory(lib_dir, args.sources)
                logger.info("  %s: %d assets", lib_dir.name, len(entries))
                all_assets.extend(entries)

    # Scan scanned elements
    scanned_dir = args.sources / "scanned_elements"
    if scanned_dir.exists():
        entries = scan_directory(scanned_dir, args.sources)
        logger.info("  scanned_elements: %d assets", len(entries))
        all_assets.extend(entries)

    # Build index
    index = {
        "generated_at": datetime.now().isoformat(),
        "total_assets": len(all_assets),
        "sources": {},
        "assets": all_assets,
    }

    # Summary by source
    for asset in all_assets:
        src = asset["source"]
        index["sources"][src] = index["sources"].get(src, 0) + 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2), encoding="utf-8")
    logger.info("\nIndex: %d assets → %s", len(all_assets), args.output)
    for src, count in sorted(index["sources"].items()):
        logger.info("  %s: %d", src, count)


if __name__ == "__main__":
    main()
