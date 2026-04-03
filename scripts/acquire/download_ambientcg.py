#!/usr/bin/env python3
"""Download CC0 PBR textures from ambientCG.

2500+ free PBR texture sets. Filters by categories relevant to heritage
buildings: Bricks, Concrete, Wood, Plaster, Roofing, Metal.

Usage:
    python scripts/acquire/download_ambientcg.py --categories "Bricks,Concrete,Wood,Plaster,Roofing,Metal"
    python scripts/acquire/download_ambientcg.py --categories Bricks --limit 20
    python scripts/acquire/download_ambientcg.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

AMBIENTCG_API = "https://ambientcg.com/api/v2/full_json"

DEFAULT_CATEGORIES = ["Bricks", "Concrete", "Wood", "Plaster", "Roofing", "Metal"]


def fetch_asset_list(categories: list[str], limit: int = 0) -> list[dict]:
    """Fetch asset list from ambientCG API."""
    try:
        import requests
    except ImportError:
        logger.error("requests not installed. Run: pip install requests")
        sys.exit(1)

    all_assets = []
    for category in categories:
        logger.info("Fetching %s...", category)
        params = {
            "type": "Material",
            "category": category,
            "sort": "Popular",
            "limit": limit if limit > 0 else 100,
            "include": "downloadData",
        }
        resp = requests.get(AMBIENTCG_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for asset in data.get("foundAssets", []):
            asset_id = asset.get("assetId", "")
            downloads = asset.get("downloadFolders", {})

            # Find 2K PNG download
            download_url = None
            for folder in downloads.get("default", {}).get("downloadFiletypeCategories", {}).get("zip", {}).get("downloads", []):
                attr = folder.get("attribute", "")
                if "2K" in attr and "PNG" in attr:
                    download_url = folder.get("fullDownloadPath")
                    break

            # Fallback to 1K
            if not download_url:
                for folder in downloads.get("default", {}).get("downloadFiletypeCategories", {}).get("zip", {}).get("downloads", []):
                    attr = folder.get("attribute", "")
                    if "1K" in attr and "PNG" in attr:
                        download_url = folder.get("fullDownloadPath")
                        break

            if download_url:
                all_assets.append({
                    "id": asset_id,
                    "category": category,
                    "download_url": download_url,
                })

    logger.info("Found %d downloadable assets", len(all_assets))
    return all_assets


def download_and_extract(asset: dict, output_dir: Path) -> dict:
    """Download ZIP and extract PBR maps."""
    import requests

    asset_id = asset["id"]
    dest = output_dir / asset_id

    if dest.exists() and any(dest.iterdir()):
        return {"id": asset_id, "status": "skipped"}

    try:
        resp = requests.get(asset["download_url"], timeout=120)
        resp.raise_for_status()

        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            zf.extractall(dest)

        files = [f.name for f in dest.iterdir()]
        return {"id": asset_id, "status": "downloaded", "files": files}
    except Exception as e:
        logger.warning("  Failed %s: %s", asset_id, e)
        return {"id": asset_id, "status": "failed", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Download ambientCG PBR textures")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES),
                        help="Comma-separated categories")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent.parent.parent / "assets" / "external" / "ambientcg")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max assets per category (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    categories = [c.strip() for c in args.categories.split(",")]
    assets = fetch_asset_list(categories, limit=args.limit)

    if args.dry_run:
        for a in assets:
            logger.info("  %s (%s)", a["id"], a["category"])
        logger.info("Total: %d assets", len(assets))
        return

    args.output.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for i, asset in enumerate(assets):
        result = download_and_extract(asset, args.output)
        if result["status"] == "downloaded":
            downloaded += 1
        if (i + 1) % 10 == 0:
            logger.info("  Progress: %d/%d", i + 1, len(assets))
        time.sleep(0.5)

    logger.info("Done: %d/%d assets downloaded to %s",
                downloaded, len(assets), args.output)


if __name__ == "__main__":
    main()
