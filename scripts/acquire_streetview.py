#!/usr/bin/env python3
"""Stage 0 ACQUIRE: Download street-level imagery from Mapillary.

Queries the Mapillary API for images within the Kensington Market bounding
box (or a custom bbox) and downloads them organized by street.

Usage:
    python scripts/acquire_streetview.py --source mapillary --bbox kensington
    python scripts/acquire_streetview.py --source mapillary --bbox kensington --output data/street_view/ --limit 500
    python scripts/acquire_streetview.py --source mapillary --bbox custom --west -79.405 --south 43.652 --east -79.395 --north 43.660
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Kensington Market bounding box (Dundas N / Spadina E / College S / Bathurst W)
KENSINGTON_BBOX = {
    "west": -79.4045,
    "south": 43.6525,
    "east": -79.3945,
    "north": 43.6590,
}

# Approximate street bounding boxes for organizing downloads
STREET_ZONES = {
    "Augusta Ave": {"west": -79.4020, "south": 43.6530, "east": -79.4000, "north": 43.6580},
    "Kensington Ave": {"west": -79.4005, "south": 43.6530, "east": -79.3985, "north": 43.6580},
    "Baldwin St": {"west": -79.4040, "south": 43.6545, "east": -79.3960, "north": 43.6560},
    "St Andrew St": {"west": -79.4040, "south": 43.6535, "east": -79.3960, "north": 43.6545},
    "Nassau St": {"west": -79.4040, "south": 43.6555, "east": -79.3960, "north": 43.6570},
    "Oxford St": {"west": -79.4040, "south": 43.6565, "east": -79.3960, "north": 43.6575},
    "Dundas St W": {"west": -79.4045, "south": 43.6525, "east": -79.3945, "north": 43.6535},
    "College St": {"west": -79.4045, "south": 43.6580, "east": -79.3945, "north": 43.6590},
    "Spadina Ave": {"west": -79.3955, "south": 43.6525, "east": -79.3945, "north": 43.6590},
    "Bathurst St": {"west": -79.4045, "south": 43.6525, "east": -79.4035, "north": 43.6590},
}

# Try requests, fall back to urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False


def get_api_key(cli_key=None):
    """Resolve Mapillary API key from CLI arg or environment."""
    key = cli_key or os.environ.get("MAPILLARY_API_KEY", "")
    return key.strip()


def fetch_json(url, headers=None):
    """Fetch JSON from a URL using requests or urllib."""
    if HAS_REQUESTS:
        resp = requests.get(url, headers=headers or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    else:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))


def download_file(url, dest, headers=None):
    """Download a file to dest path."""
    if HAS_REQUESTS:
        resp = requests.get(url, headers=headers or {}, timeout=60, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    else:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)


def assign_street(lon, lat):
    """Assign a street name based on coordinates falling within street zones."""
    for street, bbox in STREET_ZONES.items():
        if (bbox["west"] <= lon <= bbox["east"] and
                bbox["south"] <= lat <= bbox["north"]):
            return street
    return "other"


def query_mapillary(api_key, bbox, limit=200):
    """Query Mapillary API v4 for image metadata within bbox.

    Returns list of dicts with id, lon, lat, captured_at, thumb_url.
    """
    url = (
        f"https://graph.mapillary.com/images"
        f"?access_token={api_key}"
        f"&fields=id,geometry,captured_at,thumb_1024_url"
        f"&bbox={bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"
        f"&limit={min(limit, 2000)}"
    )
    try:
        data = fetch_json(url)
    except Exception as e:
        print(f"[ERROR] Mapillary API request failed: {e}")
        return []

    images = []
    for feat in data.get("data", []):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [None, None]) if geom else [None, None]
        images.append({
            "id": feat.get("id"),
            "lon": coords[0],
            "lat": coords[1],
            "captured_at": feat.get("captured_at"),
            "thumb_url": feat.get("thumb_1024_url"),
        })
    return images[:limit]


def download_images(images, output_dir, dry_run=False):
    """Download images organized by street. Returns (downloaded, skipped)."""
    downloaded = 0
    skipped = 0

    for img in images:
        if not img.get("thumb_url") or not img.get("id"):
            continue

        street = assign_street(img.get("lon", 0), img.get("lat", 0))
        street_dir = output_dir / street.replace(" ", "_")
        dest = street_dir / f"{img['id']}.jpg"

        if dest.exists():
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would download {img['id']} -> {street}/")
            downloaded += 1
            continue

        street_dir.mkdir(parents=True, exist_ok=True)
        try:
            download_file(img["thumb_url"], dest)
            downloaded += 1
        except Exception as e:
            print(f"  [WARN] Failed to download {img['id']}: {e}")

    return downloaded, skipped


def write_manifest(images, output_dir):
    """Write a manifest JSON with all image metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "streetview_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "source": "mapillary",
            "image_count": len(images),
            "images": images,
        }, f, indent=2)
    print(f"[ACQUIRE] Manifest written to {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download street-level imagery from Mapillary."
    )
    parser.add_argument(
        "--source", type=str, default="mapillary", choices=["mapillary"],
        help="Street view source (default: mapillary)",
    )
    parser.add_argument(
        "--bbox", type=str, default="kensington",
        help="Bounding box preset name or 'custom' (default: kensington)",
    )
    parser.add_argument("--west", type=float, help="Custom bbox west longitude")
    parser.add_argument("--south", type=float, help="Custom bbox south latitude")
    parser.add_argument("--east", type=float, help="Custom bbox east longitude")
    parser.add_argument("--north", type=float, help="Custom bbox north latitude")
    parser.add_argument(
        "--output", type=str, default="data/street_view/",
        help="Output directory (default: data/street_view/)",
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="Mapillary API key (or set MAPILLARY_API_KEY env var)",
    )
    parser.add_argument(
        "--limit", type=int, default=200,
        help="Max number of images to download (default: 200)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without downloading.",
    )
    args = parser.parse_args()

    output_dir = (REPO_ROOT / args.output).resolve()

    # Resolve bounding box
    if args.bbox == "custom":
        if not all([args.west, args.south, args.east, args.north]):
            print("[ERROR] Custom bbox requires --west --south --east --north")
            sys.exit(1)
        bbox = {"west": args.west, "south": args.south, "east": args.east, "north": args.north}
    else:
        bbox = KENSINGTON_BBOX

    print(f"[ACQUIRE] Bounding box: {bbox}")

    # Resolve API key
    api_key = get_api_key(args.api_key)
    if not api_key:
        print("[WARN] No Mapillary API key provided (set MAPILLARY_API_KEY or --api-key).")
        print("[WARN] Creating placeholder manifest with no images.")
        output_dir.mkdir(parents=True, exist_ok=True)
        write_manifest([], output_dir)
        sys.exit(0)

    # Query and download
    print(f"[ACQUIRE] Querying Mapillary for up to {args.limit} images...")
    images = query_mapillary(api_key, bbox, limit=args.limit)
    print(f"[ACQUIRE] API returned {len(images)} image(s)")

    if not images:
        print("[WARN] No images found in the specified bounding box.")
        write_manifest([], output_dir)
        sys.exit(0)

    downloaded, skipped = download_images(images, output_dir, dry_run=args.dry_run)
    print(f"[ACQUIRE] Downloaded {downloaded}, skipped {skipped} (already exist)")

    if not args.dry_run:
        write_manifest(images, output_dir)


if __name__ == "__main__":
    main()
