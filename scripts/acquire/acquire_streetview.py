#!/usr/bin/env python3
"""Stage 0d: Download street-level imagery from Mapillary.

Supplements field photos with additional angles. Uses Mapillary's free
CC-BY-SA API to fetch images within the Kensington Market bounding box.

Usage:
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox kensington
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox kensington --limit 500 --dry-run
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox custom --west -79.405 --south 43.652 --east -79.390 --north 43.660
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Kensington Market bounding box (WGS84)
KENSINGTON_BBOX = {
    "west": -79.4050,
    "south": 43.6520,
    "east": -79.3900,
    "north": 43.6605,
}

MAPILLARY_API_URL = "https://graph.mapillary.com/images"


def fetch_mapillary_image_ids(bbox: dict, access_token: str,
                               limit: int = 2000) -> list[dict]:
    """Query Mapillary API for image metadata within bounding box."""
    try:
        import requests
    except ImportError:
        logger.error("requests not installed. Run: pip install requests")
        sys.exit(1)

    bbox_str = f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"

    images = []
    url = MAPILLARY_API_URL
    params = {
        "access_token": access_token,
        "fields": "id,captured_at,compass_angle,geometry,thumb_1024_url,thumb_2048_url",
        "bbox": bbox_str,
        "limit": min(limit, 2000),
    }

    while url and len(images) < limit:
        logger.info("  Fetching page (%d images so far)...", len(images))
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("data", []):
            images.append({
                "id": item["id"],
                "captured_at": item.get("captured_at"),
                "compass_angle": item.get("compass_angle"),
                "lon": item["geometry"]["coordinates"][0],
                "lat": item["geometry"]["coordinates"][1],
                "thumb_url": item.get("thumb_2048_url") or item.get("thumb_1024_url"),
            })
            if len(images) >= limit:
                break

        # Pagination
        url = data.get("paging", {}).get("next")
        params = {}  # Next URL includes params
        if url:
            time.sleep(0.5)  # Rate limit courtesy

    return images


def download_images(images: list[dict], output_dir: Path,
                    dry_run: bool = False) -> dict:
    """Download images to output directory."""
    try:
        import requests
    except ImportError:
        logger.error("requests not installed. Run: pip install requests")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    failed = 0

    for img in images:
        filename = f"mapillary_{img['id']}.jpg"
        dest = output_dir / filename

        if dest.exists():
            skipped += 1
            continue

        if dry_run:
            logger.info("  [DRY-RUN] Would download %s", filename)
            continue

        if not img.get("thumb_url"):
            failed += 1
            continue

        try:
            resp = requests.get(img["thumb_url"], timeout=30)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            downloaded += 1
            if downloaded % 50 == 0:
                logger.info("  Downloaded %d/%d", downloaded, len(images))
            time.sleep(0.2)  # Rate limit
        except Exception as e:
            logger.warning("  Failed to download %s: %s", img["id"], e)
            failed += 1

    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Download street-level imagery")
    parser.add_argument("--source", default="mapillary", choices=["mapillary"],
                        help="Imagery source (default: mapillary)")
    parser.add_argument("--bbox", default="kensington",
                        help="Bounding box preset or 'custom'")
    parser.add_argument("--west", type=float, help="Custom bbox west")
    parser.add_argument("--south", type=float, help="Custom bbox south")
    parser.add_argument("--east", type=float, help="Custom bbox east")
    parser.add_argument("--north", type=float, help="Custom bbox north")
    parser.add_argument("--limit", type=int, default=2000,
                        help="Max images to fetch (default: 2000)")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent.parent.parent / "data" / "street_view",
                        help="Output directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Resolve bounding box
    if args.bbox == "kensington":
        bbox = KENSINGTON_BBOX
    elif args.bbox == "custom":
        if not all([args.west, args.south, args.east, args.north]):
            logger.error("Custom bbox requires --west --south --east --north")
            return
        bbox = {"west": args.west, "south": args.south,
                "east": args.east, "north": args.north}
    else:
        logger.error("Unknown bbox preset: %s", args.bbox)
        return

    # Get API token
    access_token = os.environ.get("MAPILLARY_ACCESS_TOKEN")
    if not access_token:
        logger.error("Set MAPILLARY_ACCESS_TOKEN environment variable")
        logger.error("Get a free token at https://www.mapillary.com/developer")
        return

    logger.info("Fetching Mapillary images for bbox: %s", bbox)
    images = fetch_mapillary_image_ids(bbox, access_token, limit=args.limit)
    logger.info("Found %d images", len(images))

    if not images:
        return

    # Save metadata
    meta_path = args.output / "metadata.json"
    args.output.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({
        "source": args.source,
        "bbox": bbox,
        "fetched_at": __import__("datetime").datetime.now().isoformat(),
        "image_count": len(images),
        "images": images,
    }, indent=2), encoding="utf-8")
    logger.info("Metadata saved to %s", meta_path)

    # Download
    logger.info("Downloading images to %s ...", args.output)
    stats = download_images(images, args.output, dry_run=args.dry_run)
    logger.info("Done: %d downloaded, %d skipped, %d failed",
                stats["downloaded"], stats["skipped"], stats["failed"])


if __name__ == "__main__":
    main()
