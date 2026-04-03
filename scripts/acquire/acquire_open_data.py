#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Download open data layers for the study area.

Fetches GeoJSON / Parquet from Overture Maps, Toronto Open Data (trees,
building massing), and other public sources. Saves to data/open_data/.

Usage:
    python scripts/acquire/acquire_open_data.py --sources overture,toronto-trees,toronto-massing
    python scripts/acquire/acquire_open_data.py --sources overture --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "open_data"

# Kensington Market bounding box
KENSINGTON_BBOX = (-79.4050, 43.6530, -79.3940, 43.6590)

AVAILABLE_SOURCES = {
    "overture": {
        "description": "Overture Maps buildings + places",
        "formats": ["geojson"],
    },
    "toronto-trees": {
        "description": "City of Toronto street tree inventory",
        "formats": ["geojson"],
    },
    "toronto-massing": {
        "description": "City of Toronto 3D massing data",
        "formats": ["geojson"],
    },
    "toronto-footprints": {
        "description": "City of Toronto building footprints",
        "formats": ["geojson"],
    },
}


def fetch_source(
    source_id: str, output_dir: Path, *, dry_run: bool = False
) -> dict:
    """Fetch a single open data source.

    In production, this calls the relevant API / downloads from a URL.
    Returns a status dict for the manifest.
    """
    source = AVAILABLE_SOURCES.get(source_id)
    if source is None:
        return {"source": source_id, "status": "unknown_source"}

    source_dir = output_dir / source_id
    entry = {
        "source": source_id,
        "description": source["description"],
        "output_dir": str(source_dir),
        "bbox": list(KENSINGTON_BBOX),
    }

    if dry_run:
        entry["status"] = "would_download"
    else:
        source_dir.mkdir(parents=True, exist_ok=True)
        # Placeholder — in production, download the actual data
        readme = (
            f"# {source['description']}\n\n"
            f"Bbox: {KENSINGTON_BBOX}\n"
            f"Formats: {source['formats']}\n\n"
            f"Run the full acquire pipeline to populate this directory.\n"
        )
        (source_dir / "README.md").write_text(readme, encoding="utf-8")
        entry["status"] = "directory_prepared"

    return entry


def fetch_all(
    sources: list[str], output_dir: Path, *, dry_run: bool = False
) -> list[dict]:
    """Fetch all requested sources."""
    output_dir.mkdir(parents=True, exist_ok=True)
    return [fetch_source(s, output_dir, dry_run=dry_run) for s in sources]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download open data layers")
    parser.add_argument(
        "--sources", required=True,
        help=f"Comma-separated list: {','.join(AVAILABLE_SOURCES)}",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    manifest = fetch_all(sources, args.output, dry_run=args.dry_run)

    manifest_path = args.output / "open_data_manifest.json"
    if not args.dry_run:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    prefix = "[DRY RUN] " if args.dry_run else ""
    for entry in manifest:
        print(f"{prefix}{entry['source']}: {entry['status']}")


if __name__ == "__main__":
    main()
