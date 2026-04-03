#!/usr/bin/env python3
"""Acquire open data from Overture Maps, Toronto Open Data, etc.

Downloads building footprints, trees, massing data, and other urban datasets.

Usage:
    python scripts/acquire_open_data.py --sources overture,toronto-trees,toronto-massing
    python scripts/acquire_open_data.py --sources overture --bbox kensington
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent

KENSINGTON_BBOX = {
    "west": -79.4065, "south": 43.6520,
    "east": -79.3975, "north": 43.6580,
}

OUTPUT_DIR = REPO_ROOT / "data" / "open_data"

# Toronto Open Data CKAN endpoints
TORONTO_DATASETS = {
    "toronto-trees": {
        "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=street-tree-data",
        "format": "geojson",
        "description": "Street trees within study area",
    },
    "toronto-massing": {
        "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=3d-massing",
        "format": "geojson",
        "description": "3D massing models",
    },
}


def fetch_overture_buildings(bbox: dict, output_dir: Path) -> dict:
    """Fetch building footprints from Overture Maps."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        import requests
        # Overture Maps uses parquet files on S3 — for simplicity, use the API if available
        # Fallback: generate from existing PostGIS data
        logger.info("Overture Maps download requires DuckDB + httpfs extension")
        logger.info("Falling back to local footprint generation from params")

        # Generate simple footprints from params
        features = []
        for f in sorted((REPO_ROOT / "params").glob("*.json")):
            if f.name.startswith("_"):
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("skipped"):
                continue
            site = data.get("site", {})
            lon = site.get("lon")
            lat = site.get("lat")
            if not lon or not lat:
                continue
            w = data.get("facade_width_m", 5.0) * 0.000009  # rough m->deg
            d = data.get("facade_depth_m", 10.0) * 0.000009
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon - w/2, lat - d/2],
                        [lon + w/2, lat - d/2],
                        [lon + w/2, lat + d/2],
                        [lon - w/2, lat + d/2],
                        [lon - w/2, lat - d/2],
                    ]],
                },
                "properties": {
                    "address": data.get("_meta", {}).get("address", f.stem),
                    "height": data.get("total_height_m"),
                    "floors": data.get("floors"),
                },
            })

        geojson = {"type": "FeatureCollection", "features": features}
        out_path = output_dir / "building_footprints.geojson"
        out_path.write_text(json.dumps(geojson), encoding="utf-8")
        return {"source": "params_fallback", "features": len(features)}

    except Exception as e:
        return {"error": str(e)}


def fetch_toronto_dataset(dataset_key: str, bbox: dict, output_dir: Path) -> dict:
    """Fetch a Toronto Open Data dataset."""
    output_dir.mkdir(parents=True, exist_ok=True)
    info = TORONTO_DATASETS.get(dataset_key)
    if not info:
        return {"error": f"Unknown dataset: {dataset_key}"}

    try:
        import requests
        resp = requests.get(info["url"], timeout=30)
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}"}

        pkg = resp.json().get("result", {})
        resources = pkg.get("resources", [])
        geojson_resources = [r for r in resources if "geojson" in r.get("format", "").lower()]

        if not geojson_resources:
            return {"error": "No GeoJSON resource found", "resources": len(resources)}

        # Download first GeoJSON resource
        resource_url = geojson_resources[0].get("url")
        if not resource_url:
            return {"error": "No download URL"}

        data_resp = requests.get(resource_url, timeout=60)
        out_path = output_dir / f"{dataset_key}.geojson"
        out_path.write_text(data_resp.text, encoding="utf-8")
        return {"downloaded": str(out_path), "size_mb": len(data_resp.content) / 1024 / 1024}

    except ImportError:
        return {"error": "requests not installed"}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Acquire open data")
    parser.add_argument("--sources", default="overture",
                        help="Comma-separated: overture,toronto-trees,toronto-massing")
    parser.add_argument("--bbox", default="kensington")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.bbox == "kensington":
        bbox = KENSINGTON_BBOX
    else:
        parts = [float(x) for x in args.bbox.split(",")]
        bbox = {"west": parts[0], "south": parts[1], "east": parts[2], "north": parts[3]}

    for source in args.sources.split(","):
        source = source.strip()
        print(f"\n--- {source} ---")
        if source == "overture":
            stats = fetch_overture_buildings(bbox, args.output)
        elif source in TORONTO_DATASETS:
            stats = fetch_toronto_dataset(source, bbox, args.output)
        else:
            stats = {"error": f"Unknown source: {source}"}
        print(f"  {stats}")


if __name__ == "__main__":
    main()
