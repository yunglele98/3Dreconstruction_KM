#!/usr/bin/env python3
"""Stage 0 — ACQUIRE: Download open data layers for the study area.

Fetches GeoJSON from Toronto Open Data, Overture Maps, and other public
sources. Clips to Kensington Market bounding box.

Supported sources:
  overture          — Overture Maps buildings + places (via DuckDB/HTTP)
  toronto-trees     — City of Toronto street tree inventory
  toronto-massing   — City of Toronto 3D massing data
  toronto-footprints — City of Toronto building footprints
  toronto-heritage  — City of Toronto heritage register

Usage:
    python scripts/acquire/acquire_open_data.py --sources overture,toronto-trees,toronto-massing
    python scripts/acquire/acquire_open_data.py --sources toronto-footprints --output data/open_data/
    python scripts/acquire/acquire_open_data.py --sources overture --dry-run
    python scripts/acquire/acquire_open_data.py --list-sources
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "open_data"

KENSINGTON_BBOX = (-79.4050, 43.6530, -79.3940, 43.6590)

AVAILABLE_SOURCES = {
    "overture": {
        "description": "Overture Maps buildings + places",
        "formats": ["geojson"],
    },
    "toronto-trees": {
        "description": "City of Toronto street tree inventory",
        "formats": ["geojson"],
        "ckan_id": "street-tree-data",
    },
    "toronto-massing": {
        "description": "City of Toronto 3D massing data",
        "formats": ["geojson"],
        "ckan_id": "3d-massing",
    },
    "toronto-footprints": {
        "description": "City of Toronto building footprints",
        "formats": ["geojson"],
        "ckan_id": "building-outlines",
    },
    "toronto-heritage": {
        "description": "City of Toronto heritage register",
        "formats": ["geojson"],
        "ckan_id": "heritage-register",
    },
}

CKAN_BASE = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id="


def bbox_contains(bbox: tuple, lon: float, lat: float) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def clip_geojson_to_bbox(geojson: dict, bbox: tuple) -> dict:
    """Filter GeoJSON features to those within the bounding box."""
    features = geojson.get("features", [])
    clipped = []
    for feat in features:
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates")
        if not coords:
            continue
        gtype = geom.get("type", "")
        if gtype == "Point" and len(coords) >= 2:
            if bbox_contains(bbox, coords[0], coords[1]):
                clipped.append(feat)
        elif gtype in ("Polygon", "MultiPolygon"):
            ring = coords[0] if gtype == "Polygon" and coords else (
                coords[0][0] if gtype == "MultiPolygon" and coords and coords[0] else []
            )
            if ring:
                cx = sum(p[0] for p in ring) / len(ring)
                cy = sum(p[1] for p in ring) / len(ring)
                if bbox_contains(bbox, cx, cy):
                    clipped.append(feat)

    return {
        "type": "FeatureCollection",
        "features": clipped,
        "metadata": {"original_count": len(features), "clipped_count": len(clipped)},
    }


def download_json(url: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KM-3D-Pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def fetch_toronto_ckan(source_id: str, output_dir: Path) -> dict:
    """Fetch from Toronto Open Data CKAN API."""
    source = AVAILABLE_SOURCES[source_id]
    ckan_id = source.get("ckan_id")
    if not ckan_id:
        return {"status": "no_ckan_id"}

    pkg = download_json(f"{CKAN_BASE}{ckan_id}")
    if not pkg or not pkg.get("success"):
        return {"status": "api_unreachable", "url": f"{CKAN_BASE}{ckan_id}"}

    resources = pkg.get("result", {}).get("resources", [])
    geojson_url = None
    for r in resources:
        if (r.get("format") or "").lower() in ("geojson", "json") and r.get("url"):
            geojson_url = r["url"]
            break

    if not geojson_url:
        return {"status": "no_geojson_resource",
                "formats": [r.get("format") for r in resources]}

    geojson = download_json(geojson_url, timeout=60)
    if not geojson:
        return {"status": "download_failed", "url": geojson_url}

    clipped = clip_geojson_to_bbox(geojson, KENSINGTON_BBOX)
    output_path = output_dir / f"{source_id}.geojson"
    output_path.write_text(
        json.dumps(clipped, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "status": "downloaded",
        "features": clipped["metadata"]["clipped_count"],
        "original_features": clipped["metadata"]["original_count"],
        "output": str(output_path),
    }


def fetch_source(source_id: str, output_dir: Path, *, dry_run: bool = False) -> dict:
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
        return entry

    source_dir.mkdir(parents=True, exist_ok=True)

    if source.get("ckan_id"):
        fetch_result = fetch_toronto_ckan(source_id, source_dir)
        entry.update(fetch_result)
    elif source_id == "overture":
        entry["status"] = "requires_duckdb"
        entry["note"] = "Overture Maps download requires DuckDB with httpfs extension"
    else:
        entry["status"] = "unknown_fetch_method"

    return entry


def fetch_all(sources: list[str], output_dir: Path, *, dry_run: bool = False) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [fetch_source(s, output_dir, dry_run=dry_run) for s in sources]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download open data layers")
    parser.add_argument("--sources", default=None,
                        help=f"Comma-separated: {','.join(AVAILABLE_SOURCES)}")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-sources", action="store_true")
    args = parser.parse_args()

    if args.list_sources:
        for sid, info in AVAILABLE_SOURCES.items():
            print(f"  {sid:<25} {info['description']}")
        return

    if not args.sources:
        print("ERROR: --sources required (or use --list-sources)")
        sys.exit(1)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    manifest = fetch_all(sources, args.output, dry_run=args.dry_run)

    manifest_path = args.output / "open_data_manifest.json"
    if not args.dry_run:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    prefix = "[DRY RUN] " if args.dry_run else ""
    for entry in manifest:
        features = entry.get("features", "?")
        print(f"{prefix}{entry['source']}: {entry['status']} ({features} features)")


if __name__ == "__main__":
    main()
