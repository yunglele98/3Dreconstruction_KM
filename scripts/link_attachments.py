#!/usr/bin/env python3
"""Link field survey photo attachments to PostGIS tables.

Scans the attachments directory structure (layer/OBJECTID/photo.jpg)
and adds photo_path columns to the corresponding field_* tables.

Usage:
    python link_attachments.py
"""

import json
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG

ATTACHMENTS_DIR = Path("C:/Users/liam1/DOWNLOADS/MASTERLIST/DATA/attachments")

# Attachment subfolder → DB table + the GeoJSON OBJECTID field name
LAYER_MAP = {
    "arbres": "field_trees",
    "poteau": "field_poles",
    "supportvelo": "field_bike_racks",
    "panneaucirculation": "field_signs",
    "terrasse": "field_terraces",
    "ruelle": "field_alleys",
    "stationnement": "field_parking",
    "batimentvacant": "field_vacant_buildings",
    "etablissement": "field_establishments",
    "art": "field_public_art",
    "parc": "field_parks",
    "intersection": "field_intersections",
    "abribus": "field_bus_shelters",
}

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}


def scan_attachments(layer_dir: Path) -> dict[int, list[str]]:
    """Scan OBJECTID subfolders and return {objectid: [photo_paths]}."""
    results = {}
    if not layer_dir.exists():
        return results

    for subfolder in sorted(layer_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        try:
            oid = int(subfolder.name)
        except ValueError:
            continue

        photos = []
        for f in sorted(subfolder.iterdir()):
            if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS:
                photos.append(str(f.resolve()))
        if photos:
            results[oid] = photos

    return results


def link_layer(conn, layer_name: str, table_name: str, attachments: dict[int, list[str]]) -> int:
    """Add photo columns and update rows for one layer."""
    cur = conn.cursor()

    # Add columns if they don't exist
    cur.execute(f"""
        ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS photo_path text;
        ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS photo_paths text[];
        ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS photo_count integer DEFAULT 0;
    """)

    # Check which column to match OBJECTIDs on (objectid from import, or fallback to id)
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND column_name IN ('objectid', 'feature_id', 'id')
    """, (table_name,))
    available_cols = {r[0] for r in cur.fetchall()}

    if "objectid" in available_cols:
        match_col = "objectid"
    elif "feature_id" in available_cols:
        match_col = "feature_id"
    else:
        match_col = "id"

    updated = 0
    for oid, photos in attachments.items():
        primary_photo = photos[0]
        cur.execute(f"""
            UPDATE {table_name}
            SET photo_path = %s,
                photo_paths = %s::text[],
                photo_count = %s
            WHERE {match_col} = %s
        """, (primary_photo, photos, len(photos), oid))

        if cur.rowcount > 0:
            updated += 1

    conn.commit()
    cur.close()
    return updated


def main():
    conn = psycopg2.connect(**DB_CONFIG)

    print("=== Link Attachments to PostGIS ===")
    print(f"Source: {ATTACHMENTS_DIR}")
    print()

    total_photos = 0
    total_linked = 0

    for layer_name, table_name in LAYER_MAP.items():
        layer_dir = ATTACHMENTS_DIR / layer_name
        attachments = scan_attachments(layer_dir)
        photo_count = sum(len(p) for p in attachments.values())

        if not attachments:
            print(f"  [SKIP] {layer_name}: no attachments found")
            continue

        linked = link_layer(conn, layer_name, table_name, attachments)
        total_photos += photo_count
        total_linked += linked
        print(f"  [OK] {table_name}: {linked}/{len(attachments)} features linked, {photo_count} photos")

    conn.close()
    print(f"\nTotal: {total_linked} features linked, {total_photos} photos")


if __name__ == "__main__":
    main()
