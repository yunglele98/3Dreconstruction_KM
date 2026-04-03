#!/usr/bin/env python3
"""Stage 0 ACQUIRE: Download open datasets (GeoJSON/CSV) from known URLs.

Supports Overture Maps buildings, Toronto street trees, and Toronto 3D
massing data.  Skips downloads if files already exist locally.

Usage:
    python scripts/acquire_open_data.py --sources overture,toronto-trees,toronto-massing
    python scripts/acquire_open_data.py --sources overture --output data/open_data/
    python scripts/acquire_open_data.py --sources all
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Try requests, fall back to urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

SOURCES = {
    "overture": {
        "description": "Overture Maps Foundation building footprints (Kensington Market area)",
        "url": "https://overturemaps.org/download/buildings.geojson",
        "filename": "overture_buildings.geojson",
        "format": "geojson",
        "notes": (
            "Overture Maps does not yet offer a simple URL download. "
            "For production use, query via DuckDB or the Overture CLI: "
            "overturemaps download --bbox=-79.4045,43.6525,-79.3945,43.6590 "
            "-f geojson --type=building -o overture_buildings.geojson"
        ),
    },
    "toronto-trees": {
        "description": "City of Toronto street tree inventory",
        "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/street-tree-data/resource/5a138635-37c1-4638-8f2e-a81eba7a440e/download/Street%20Tree%20Data%20-%204326.geojson",
        "filename": "toronto_street_trees.geojson",
        "format": "geojson",
    },
    "toronto-massing": {
        "description": "City of Toronto 3D massing model (building outlines with heights)",
        "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/3d-massing/resource/8a38e834-a0b2-44a8-9b6e-3b0a41655f5a/download/3D%20Massing.geojson",
        "filename": "toronto_3d_massing.geojson",
        "format": "geojson",
    },
}


def download_file(url, dest):
    """Download a URL to a local file path."""
    print(f"  Downloading: {url}")
    print(f"  Destination: {dest}")

    if HAS_REQUESTS:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)
    else:
        urllib.request.urlretrieve(url, str(dest))

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  Downloaded {size_mb:.1f} MB")


def acquire_source(name, config, output_dir, dry_run=False):
    """Download a single data source. Returns (downloaded: bool, skipped: bool, error: str|None)."""
    dest = output_dir / config["filename"]

    if dest.exists():
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"[SKIP] {name}: {config['filename']} already exists ({size_mb:.1f} MB)")
        return False, True, None

    if dry_run:
        print(f"[DRY-RUN] Would download {name}: {config['url']}")
        return True, False, None

    output_dir.mkdir(parents=True, exist_ok=True)

    # Show notes if the URL is a placeholder
    if config.get("notes"):
        print(f"[NOTE] {name}: {config['notes']}")

    try:
        download_file(config["url"], dest)
        return True, False, None
    except Exception as e:
        error_msg = f"Failed to download {name}: {e}"
        print(f"[ERROR] {error_msg}")
        # Write a placeholder so the pipeline knows this source was attempted
        placeholder = dest.with_suffix(".placeholder.json")
        with open(placeholder, "w", encoding="utf-8") as f:
            json.dump({
                "source": name,
                "url": config["url"],
                "error": str(e),
                "attempted_at": datetime.now(timezone.utc).isoformat(),
                "instructions": config.get("notes", "Retry download or obtain data manually."),
            }, f, indent=2)
        return False, False, error_msg


def resolve_sources(sources_str):
    """Parse comma-separated source names. 'all' returns everything."""
    if sources_str.strip().lower() == "all":
        return list(SOURCES.keys())
    names = [s.strip().lower() for s in sources_str.split(",") if s.strip()]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        print(f"[ERROR] Unknown sources: {', '.join(unknown)}")
        print(f"[INFO] Available sources: {', '.join(sorted(SOURCES.keys()))}")
        sys.exit(1)
    return names


def main():
    parser = argparse.ArgumentParser(
        description="Download open datasets for the Kensington Market pipeline."
    )
    parser.add_argument(
        "--sources", type=str, default="overture,toronto-trees,toronto-massing",
        help="Comma-separated source names or 'all' (default: overture,toronto-trees,toronto-massing)",
    )
    parser.add_argument(
        "--output", type=str, default="data/open_data/",
        help="Output directory (default: data/open_data/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without downloading.",
    )
    args = parser.parse_args()

    output_dir = (REPO_ROOT / args.output).resolve()
    source_names = resolve_sources(args.sources)

    print(f"[ACQUIRE] Sources: {', '.join(source_names)}")
    print(f"[ACQUIRE] Output: {output_dir}")

    downloaded = 0
    skipped = 0
    errors = []

    for name in source_names:
        config = SOURCES[name]
        print(f"\n--- {name}: {config['description']} ---")
        dl, sk, err = acquire_source(name, config, output_dir, dry_run=args.dry_run)
        if dl:
            downloaded += 1
        if sk:
            skipped += 1
        if err:
            errors.append(err)

    # Write acquisition manifest
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "acquisition_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "sources_requested": source_names,
                "downloaded": downloaded,
                "skipped": skipped,
                "errors": errors,
            }, f, indent=2)

    print(f"\n[ACQUIRE] Done: downloaded {downloaded}, skipped {skipped}, errors {len(errors)}")


if __name__ == "__main__":
    main()
