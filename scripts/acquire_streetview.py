#!/usr/bin/env python3
"""Acquire street-level imagery from Mapillary for Kensington Market.

Downloads geotagged street view images within the study area bounding box.

Usage:
    python scripts/acquire_streetview.py --source mapillary --bbox kensington
    python scripts/acquire_streetview.py --source mapillary --bbox "-79.406,43.652,-79.397,43.658"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Kensington Market bounding box (EPSG:4326)
KENSINGTON_BBOX = {
    "west": -79.4065,
    "south": 43.6520,
    "east": -79.3975,
    "north": 43.6580,
}

OUTPUT_DIR = REPO_ROOT / "data" / "street_view"


def fetch_mapillary(bbox: dict, output_dir: Path, limit: int = 500) -> dict:
    """Fetch images from Mapillary API within bounding box.

    Requires MAPILLARY_ACCESS_TOKEN environment variable.
    """
    token = os.environ.get("MAPILLARY_ACCESS_TOKEN")
    if not token:
        logger.warning("MAPILLARY_ACCESS_TOKEN not set. Set it to download images.")
        return {"error": "no_token", "downloaded": 0}

    try:
        import requests
    except ImportError:
        logger.error("requests library required: pip install requests")
        return {"error": "no_requests", "downloaded": 0}

    output_dir.mkdir(parents=True, exist_ok=True)
    bbox_str = f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"

    # Search for images
    url = "https://graph.mapillary.com/images"
    params = {
        "access_token": token,
        "fields": "id,geometry,captured_at,compass_angle,is_pano",
        "bbox": bbox_str,
        "limit": min(limit, 2000),
    }

    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return {"error": f"API error {resp.status_code}", "downloaded": 0}

    data = resp.json()
    images = data.get("data", [])

    # Save metadata index
    index_path = output_dir / "mapillary_index.json"
    index_path.write_text(json.dumps(images, indent=2), encoding="utf-8")

    # Download thumbnail images
    downloaded = 0
    for img in images[:limit]:
        img_id = img["id"]
        thumb_url = f"https://graph.mapillary.com/{img_id}?access_token={token}&fields=thumb_1024_url"
        try:
            thumb_resp = requests.get(thumb_url, timeout=15)
            thumb_data = thumb_resp.json()
            if "thumb_1024_url" in thumb_data:
                img_resp = requests.get(thumb_data["thumb_1024_url"], timeout=30)
                img_path = output_dir / f"mapillary_{img_id}.jpg"
                img_path.write_bytes(img_resp.content)
                downloaded += 1
        except Exception as e:
            logger.warning(f"Failed to download {img_id}: {e}")

    return {"images_found": len(images), "downloaded": downloaded}


def main():
    parser = argparse.ArgumentParser(description="Acquire street view imagery")
    parser.add_argument("--source", choices=["mapillary"], default="mapillary")
    parser.add_argument("--bbox", default="kensington",
                        help="'kensington' or 'west,south,east,north'")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.bbox == "kensington":
        bbox = KENSINGTON_BBOX
    else:
        parts = [float(x) for x in args.bbox.split(",")]
        bbox = {"west": parts[0], "south": parts[1], "east": parts[2], "north": parts[3]}

    stats = fetch_mapillary(bbox, args.output, args.limit)
    print(f"Street view acquisition: {stats}")


if __name__ == "__main__":
    main()
