#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Download street-level imagery from Mapillary.

Queries the Mapillary API for images within the Kensington Market bounding
box and downloads them to data/street_view/.

Usage:
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox kensington
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox kensington --limit 100
    python scripts/acquire/acquire_streetview.py --source mapillary --bbox kensington --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Kensington Market bounding box (lon_min, lat_min, lon_max, lat_max)
KENSINGTON_BBOX = (-79.4050, 43.6530, -79.3940, 43.6590)

NAMED_BBOXES = {
    "kensington": KENSINGTON_BBOX,
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "street_view"


def fetch_mapillary_images(
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    *,
    limit: int = 0,
    dry_run: bool = False,
    api_token: str | None = None,
) -> list[dict]:
    """Query Mapillary for images within *bbox* and download them.

    Returns a manifest of downloaded (or would-download) images.
    Requires MAPILLARY_TOKEN env var or *api_token* parameter.
    """
    token = api_token or os.environ.get("MAPILLARY_TOKEN")
    if not token and not dry_run:
        print("[WARN] MAPILLARY_TOKEN not set — running in manifest-only mode")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    # In production, this calls the Mapillary v4 API:
    #   GET /images?bbox={bbox}&limit={limit}&fields=id,geometry,captured_at,compass_angle
    # For now, create the directory structure and return an empty manifest.
    entry = {
        "bbox": list(bbox),
        "source": "mapillary",
        "output_dir": str(output_dir),
        "images_found": 0,
        "images_downloaded": 0,
        "status": "would_download" if dry_run else "api_token_required",
    }
    manifest.append(entry)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Download street-level imagery")
    parser.add_argument("--source", default="mapillary", choices=["mapillary"])
    parser.add_argument(
        "--bbox", default="kensington",
        help="Named bbox (kensington) or 'lon_min,lat_min,lon_max,lat_max'",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Max images (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.bbox in NAMED_BBOXES:
        bbox = NAMED_BBOXES[args.bbox]
    else:
        try:
            bbox = tuple(float(x) for x in args.bbox.split(","))
            assert len(bbox) == 4
        except (ValueError, AssertionError):
            print(f"[ERROR] Invalid bbox: {args.bbox}")
            sys.exit(1)

    manifest = fetch_mapillary_images(
        bbox, args.output, limit=args.limit, dry_run=args.dry_run
    )

    manifest_path = args.output / "streetview_manifest.json"
    if not args.dry_run:
        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    prefix = "[DRY RUN] " if args.dry_run else ""
    for entry in manifest:
        print(f"{prefix}{entry['source']}: {entry['status']} ({entry['images_found']} images)")


if __name__ == "__main__":
    main()
