#!/usr/bin/env python3
"""Download architectural PBR textures from Poly Haven (CC0).

Fetches textures matching heritage building categories: brick, stone, wood,
concrete, plaster, roofing, metal. Stores PBR map sets in assets/external/polyhaven/.

Usage:
    python scripts/acquire/download_polyhaven.py --categories "brick,stone,wood" --output assets/external/polyhaven/
    python scripts/acquire/download_polyhaven.py --list   # list available categories
    python scripts/acquire/download_polyhaven.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

POLYHAVEN_API = "https://api.polyhaven.com/assets"
POLYHAVEN_FILES_API = "https://api.polyhaven.com/files"

DEFAULT_CATEGORIES = ["brick", "stone", "wood", "concrete", "plaster", "roofing", "metal"]
DEFAULT_RESOLUTION = "2k"


def fetch_asset_list(categories: list[str]) -> list[dict]:
    """Fetch texture assets from Poly Haven API filtered by category tags."""
    try:
        import requests
    except ImportError:
        logger.error("requests not installed. Run: pip install requests")
        sys.exit(1)

    logger.info("Fetching Poly Haven texture catalog...")
    resp = requests.get(POLYHAVEN_API, params={"t": "textures"}, timeout=30)
    resp.raise_for_status()
    all_assets = resp.json()

    matched = []
    category_set = {c.lower() for c in categories}

    for asset_id, info in all_assets.items():
        tags = {t.lower() for t in info.get("tags", [])}
        matching_cats = tags & category_set
        if matching_cats:
            matched.append({
                "id": asset_id,
                "name": info.get("name", asset_id),
                "categories": list(matching_cats),
                "tags": info.get("tags", []),
            })

    logger.info("Found %d textures matching %s", len(matched), categories)
    return matched


def download_asset(asset_id: str, output_dir: Path,
                   resolution: str = DEFAULT_RESOLUTION) -> dict:
    """Download PBR map set for a single asset."""
    import requests

    dest = output_dir / asset_id
    if dest.exists() and any(dest.iterdir()):
        return {"id": asset_id, "status": "skipped"}

    # Get file URLs
    resp = requests.get(f"{POLYHAVEN_FILES_API}/{asset_id}", timeout=30)
    resp.raise_for_status()
    files_data = resp.json()

    # Navigate to the resolution we want
    textures = files_data.get("Diffuse", {}).get(resolution, {})
    if not textures:
        # Try alternative map names
        for map_key in ["Diffuse", "diffuse", "Color", "color"]:
            textures = files_data.get(map_key, {}).get(resolution, {})
            if textures:
                break

    dest.mkdir(parents=True, exist_ok=True)
    downloaded = []

    # Download all available maps at the requested resolution
    for map_type, resolutions in files_data.items():
        if not isinstance(resolutions, dict):
            continue
        res_data = resolutions.get(resolution, {})
        if not isinstance(res_data, dict):
            continue

        # Handle different API response structures
        url = None
        if "url" in res_data:
            url = res_data["url"]
        elif "png" in res_data:
            url = res_data["png"].get("url")
        elif "jpg" in res_data:
            url = res_data["jpg"].get("url")

        if not url:
            continue

        ext = Path(url).suffix or ".png"
        filename = f"{asset_id}_{map_type}{ext}"
        file_dest = dest / filename

        if file_dest.exists():
            downloaded.append(filename)
            continue

        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            file_dest.write_bytes(r.content)
            downloaded.append(filename)
        except Exception as e:
            logger.warning("  Failed %s/%s: %s", asset_id, map_type, e)

    return {"id": asset_id, "status": "downloaded", "files": downloaded}


def main():
    parser = argparse.ArgumentParser(description="Download Poly Haven textures")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES),
                        help="Comma-separated texture categories")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent.parent.parent / "assets" / "external" / "polyhaven")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                        choices=["1k", "2k", "4k"])
    parser.add_argument("--limit", type=int, default=0,
                        help="Max textures to download (0 = all)")
    parser.add_argument("--list", action="store_true",
                        help="List matching assets without downloading")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    categories = [c.strip() for c in args.categories.split(",")]
    assets = fetch_asset_list(categories)

    if args.limit > 0:
        assets = assets[:args.limit]

    if args.list or args.dry_run:
        for a in assets:
            logger.info("  %s — %s", a["id"], ", ".join(a["categories"]))
        logger.info("Total: %d assets", len(assets))
        return

    args.output.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for i, asset in enumerate(assets):
        result = download_asset(asset["id"], args.output, args.resolution)
        if result["status"] == "downloaded":
            downloaded += 1
        if (i + 1) % 10 == 0:
            logger.info("  Progress: %d/%d", i + 1, len(assets))
        time.sleep(0.3)

    logger.info("Done: %d/%d textures downloaded to %s", downloaded, len(assets), args.output)


if __name__ == "__main__":
    main()
