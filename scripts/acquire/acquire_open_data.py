#!/usr/bin/env python3
"""Stage 0e: Download and standardize open data sources.

Fetches Overture Maps buildings/roads/places, Toronto Street Tree inventory,
and Toronto 3D Massing data. All outputs are GeoJSON in data/open_data/.

Usage:
    python scripts/acquire/acquire_open_data.py --sources overture,toronto-trees,toronto-massing
    python scripts/acquire/acquire_open_data.py --sources overture --dry-run
    python scripts/acquire/acquire_open_data.py --sources toronto-trees
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "open_data"

# Kensington Market bounding box (WGS84)
KENSINGTON_BBOX = {
    "west": -79.4050,
    "south": 43.6520,
    "east": -79.3900,
    "north": 43.6605,
}

# Toronto Open Data CKAN API
TORONTO_OPEN_DATA_URL = "https://ckan0.cf.opendata.inter.prod-p.tor.gov.on.ca"

TORONTO_DATASETS = {
    "toronto-trees": {
        "package_id": "street-tree-data",
        "description": "Street tree inventory: species, DBH, location",
        "output_file": "toronto_street_trees.geojson",
    },
    "toronto-massing": {
        "package_id": "3d-massing",
        "description": "Toronto 3D Massing (already in PostGIS, for validation)",
        "output_file": "toronto_massing.geojson",
    },
}

OVERTURE_THEMES = ["buildings", "places", "transportation"]


def fetch_toronto_dataset(dataset_key: str, output_dir: Path,
                          dry_run: bool = False) -> dict:
    """Download a Toronto Open Data dataset as GeoJSON."""
    try:
        import requests
    except ImportError:
        logger.error("requests not installed. Run: pip install requests")
        sys.exit(1)

    config = TORONTO_DATASETS[dataset_key]
    output_file = output_dir / config["output_file"]

    if output_file.exists():
        logger.info("  [SKIP] %s already exists", output_file.name)
        return {"source": dataset_key, "status": "skipped", "file": str(output_file)}

    if dry_run:
        logger.info("  [DRY-RUN] Would download %s", dataset_key)
        return {"source": dataset_key, "status": "dry_run"}

    logger.info("  Fetching package metadata for %s...", config["package_id"])
    resp = requests.get(
        f"{TORONTO_OPEN_DATA_URL}/api/3/action/package_show",
        params={"id": config["package_id"]},
        timeout=30,
    )
    resp.raise_for_status()
    package = resp.json()["result"]

    # Find GeoJSON resource
    geojson_resource = None
    for resource in package.get("resources", []):
        fmt = (resource.get("format") or "").lower()
        name = (resource.get("name") or "").lower()
        if fmt in ("geojson", "json") or "geojson" in name:
            geojson_resource = resource
            break

    if not geojson_resource:
        # Fall back to CSV/SHP if no GeoJSON
        for resource in package.get("resources", []):
            fmt = (resource.get("format") or "").lower()
            if fmt == "csv":
                geojson_resource = resource
                break

    if not geojson_resource:
        logger.warning("  No downloadable resource found for %s", dataset_key)
        return {"source": dataset_key, "status": "no_resource"}

    download_url = geojson_resource["url"]
    logger.info("  Downloading %s (%s)...", dataset_key, geojson_resource.get("format"))

    resp = requests.get(download_url, timeout=120)
    resp.raise_for_status()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(resp.content)

    size_mb = len(resp.content) / (1024 * 1024)
    logger.info("  Saved %s (%.1f MB)", output_file.name, size_mb)
    return {"source": dataset_key, "status": "downloaded",
            "file": str(output_file), "size_mb": round(size_mb, 1)}


def fetch_overture_data(output_dir: Path, bbox: dict,
                        dry_run: bool = False) -> dict:
    """Download Overture Maps data for the bounding box.

    Requires overturemaps-py: pip install overturemaps
    Falls back to DuckDB direct query if overturemaps not available.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for theme in OVERTURE_THEMES:
        output_file = output_dir / f"overture_{theme}.geojson"

        if output_file.exists():
            logger.info("  [SKIP] %s already exists", output_file.name)
            results.append({"theme": theme, "status": "skipped"})
            continue

        if dry_run:
            logger.info("  [DRY-RUN] Would download Overture %s", theme)
            results.append({"theme": theme, "status": "dry_run"})
            continue

        try:
            import overturemaps
            logger.info("  Downloading Overture %s via overturemaps-py...", theme)
            gdf = overturemaps.record_batch_reader(
                theme, bbox=(bbox["west"], bbox["south"], bbox["east"], bbox["north"])
            ).read_all().to_pandas()
            # Convert to GeoJSON via geopandas
            import geopandas as gpd
            gdf_geo = gpd.GeoDataFrame(gdf, geometry="geometry")
            gdf_geo.to_file(output_file, driver="GeoJSON")
            results.append({"theme": theme, "status": "downloaded",
                            "features": len(gdf_geo)})
            logger.info("  Saved %s (%d features)", output_file.name, len(gdf_geo))
        except ImportError:
            logger.info("  Trying DuckDB fallback for Overture %s...", theme)
            try:
                import duckdb
                conn = duckdb.connect()
                conn.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
                query = f"""
                    COPY (
                        SELECT * FROM read_parquet(
                            's3://overturemaps-us-west-2/release/2024-12-18.0/theme={theme}/type=*/*',
                            hive_partitioning=true
                        )
                        WHERE bbox.xmin >= {bbox['west']}
                          AND bbox.ymin >= {bbox['south']}
                          AND bbox.xmax <= {bbox['east']}
                          AND bbox.ymax <= {bbox['north']}
                    ) TO '{output_file}' WITH (FORMAT GDAL, DRIVER 'GeoJSON');
                """
                conn.execute(query)
                results.append({"theme": theme, "status": "downloaded"})
                logger.info("  Saved %s via DuckDB", output_file.name)
            except Exception as e:
                logger.warning("  Failed to fetch Overture %s: %s", theme, e)
                logger.info("  Install: pip install overturemaps  OR  pip install duckdb")
                results.append({"theme": theme, "status": "failed", "error": str(e)})

    return {"source": "overture", "themes": results}


def main():
    parser = argparse.ArgumentParser(description="Download open data sources")
    parser.add_argument("--sources", required=True,
                        help="Comma-separated: overture,toronto-trees,toronto-massing")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Output directory (default: data/open_data/)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    sources = [s.strip() for s in args.sources.split(",")]
    all_results = []

    for source in sources:
        logger.info("Processing: %s", source)
        if source == "overture":
            result = fetch_overture_data(args.output, KENSINGTON_BBOX,
                                         dry_run=args.dry_run)
            all_results.append(result)
        elif source in TORONTO_DATASETS:
            result = fetch_toronto_dataset(source, args.output,
                                           dry_run=args.dry_run)
            all_results.append(result)
        else:
            logger.warning("Unknown source: %s", source)

    # Write manifest
    if not args.dry_run:
        manifest = {
            "fetched_at": __import__("datetime").datetime.now().isoformat(),
            "sources": all_results,
        }
        manifest_path = args.output / "_manifest.json"
        args.output.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info("\nDone.")


if __name__ == "__main__":
    main()
