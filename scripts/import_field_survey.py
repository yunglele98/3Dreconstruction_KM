#!/usr/bin/env python3
"""Import field survey GeoJSON layers into the kensington PostGIS database.

Reads all field-mapped GeoJSON files and creates one table per layer
with proper geometry columns and indexes.

Usage:
    python import_field_survey.py
    python import_field_survey.py --dry-run
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG

DATA_DIR = Path("C:/Users/liam1/DOWNLOADS/MASTERLIST/DATA")

# Field survey layers to import (filename → table name)
LAYERS = {
    "arbres.geojson": "field_trees",
    "poteau.geojson": "field_poles",
    "supportvelo.geojson": "field_bike_racks",
    "panneaucirculation.geojson": "field_signs",
    "terrasse.geojson": "field_terraces",
    "ruelle.geojson": "field_alleys",
    "Stationnement_KM.geojson": "field_parking",
    "batimentvacant.geojson": "field_vacant_buildings",
    "etablissement.geojson": "field_establishments",
    "art.geojson": "field_public_art",
    "parc_installation_recreative.geojson": "field_parks",
    "intersection.geojson": "field_intersections",
    "abribus.geojson": "field_bus_shelters",
}

# Skip metadata fields from ArcGIS (keep OBJECTID for attachment linking)
SKIP_FIELDS = {"GlobalID", "CreationDate", "Creator", "EditDate", "Editor"}


def sanitize_column(name: str) -> str:
    """Convert French field names to safe SQL column names."""
    # Normalize accented characters
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a",
        "ù": "u", "û": "u",
        "ô": "o", "î": "i", "ï": "i",
        "ç": "c",
        "É": "E", "È": "E",
    }
    result = name
    for src, dst in replacements.items():
        result = result.replace(src, dst)
    # Lowercase and replace non-alnum with underscore
    result = re.sub(r"[^a-zA-Z0-9]", "_", result).lower()
    result = re.sub(r"_+", "_", result).strip("_")
    return result


def infer_sql_type(values: list) -> str:
    """Infer SQL column type from sample values."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "text"
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"
    if all(isinstance(v, int) for v in non_null):
        return "integer"
    if all(isinstance(v, (int, float)) for v in non_null):
        return "double precision"
    return "text"


def import_layer(conn, geojson_path: Path, table_name: str, dry_run: bool = False) -> int:
    """Import a single GeoJSON file into a PostGIS table."""
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features:
        print(f"  [SKIP] {geojson_path.name}: no features")
        return 0

    # Determine geometry type
    geom_type = features[0].get("geometry", {}).get("type", "Point")

    # Collect all property keys and sample values
    all_props = {}
    for feat in features:
        props = feat.get("properties", {})
        for key, val in props.items():
            if key in SKIP_FIELDS:
                continue
            col = sanitize_column(key)
            if col not in all_props:
                all_props[col] = {"original": key, "values": []}
            all_props[col]["values"].append(val)

    # Build CREATE TABLE
    columns = []
    col_map = {}  # sanitized → original
    for col, info in all_props.items():
        sql_type = infer_sql_type(info["values"])
        columns.append(f"    {col} {sql_type}")
        col_map[col] = info["original"]

    # Rename 'id' column if it conflicts with primary key
    renamed_columns = []
    for c in columns:
        if c.strip().startswith("id "):
            c = c.replace("id ", "feature_id ", 1)
            # Also fix col_map
            if "id" in col_map:
                col_map["feature_id"] = col_map.pop("id")
        renamed_columns.append(c)
    columns = renamed_columns

    create_sql = f"""
DROP TABLE IF EXISTS {table_name} CASCADE;
CREATE TABLE {table_name} (
    id serial PRIMARY KEY,
{',\n'.join(columns)},
    geom geometry({geom_type}, 4326)
);
CREATE INDEX idx_{table_name}_geom ON {table_name} USING gist (geom);
"""

    if dry_run:
        print(f"  [DRY RUN] {table_name}: {len(features)} features, {len(columns)} columns")
        return len(features)

    cur = conn.cursor()
    cur.execute(create_sql)

    # Insert features
    col_names = list(col_map.keys())
    placeholders = ", ".join(["%s"] * len(col_names)) + ", ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
    insert_sql = f"""
        INSERT INTO {table_name} ({', '.join(col_names)}, geom)
        VALUES ({placeholders})
    """

    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        values = []
        for col in col_names:
            orig_key = col_map[col]
            val = props.get(orig_key)
            # Convert non-string values for text columns
            if isinstance(val, (dict, list)):
                val = json.dumps(val)
            values.append(val)
        values.append(json.dumps(geom))

        cur.execute(insert_sql, values)

    conn.commit()
    cur.close()
    return len(features)


def main():
    parser = argparse.ArgumentParser(description="Import field survey GeoJSON to PostGIS")
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)

    print("=== Field Survey Import ===")
    print(f"Source: {DATA_DIR}")
    print()

    total = 0
    for filename, table_name in LAYERS.items():
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"  [MISSING] {filename}")
            continue

        count = import_layer(conn, filepath, table_name, args.dry_run)
        print(f"  [OK] {table_name}: {count} features from {filename}")
        total += count

    conn.close()
    print(f"\nTotal: {total} features across {len(LAYERS)} layers")


if __name__ == "__main__":
    main()
