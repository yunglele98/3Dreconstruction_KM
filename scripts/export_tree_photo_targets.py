#!/usr/bin/env python3
"""Export tree-focused photo targets with nearest species candidates.

Reads PHOTOS KENSINGTON/csv/photo_address_index.csv and matches tree-related
rows to nearest species in opendata.street_trees via building_assessment.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from db_config import DB_CONFIG, get_connection

PHOTO_KEYWORDS = re.compile(
    r"\b(cedar|conifer|conifers|evergreen|spruce|pine|fir|tree|trees|shrub|hedge|bush|branches)\b",
    flags=re.IGNORECASE,
)
FALSE_POSITIVE_CONTEXT = re.compile(
    r"(tree'?s in the six|tree top african cafe|evergreen centre)",
    flags=re.IGNORECASE,
)


def parse_number_street(text: str) -> tuple[int | None, str]:
    text = (text or "").strip()
    m = re.search(
        r"(\d+)\s+([A-Za-z][A-Za-z\s]+?\s(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Terr|Terrace|Pl|Place|Sq|Square))\b",
        text,
    )
    if not m:
        return None, ""
    return int(m.group(1)), re.sub(r"\s+", " ", m.group(2)).strip()


def fetch_nearest_species(conn, street_no: int, street_name: str, radius_m: float, limit_n: int):
    query = """
        WITH b AS (
            SELECT ST_Transform(geom, 2952) AS g, "ADDRESS_FULL" AS address_full
            FROM public.building_assessment
            WHERE ba_street_number = %s
              AND ba_street ILIKE %s
            ORDER BY id
            LIMIT 1
        )
        SELECT
            b.address_full,
            t."COMMON_14" AS common_name,
            t."BOTANIC13" AS botanic_name,
            ROUND(ST_Distance(b.g, ST_Centroid(t.geometry))::numeric, 2) AS dist_m
        FROM b
        JOIN opendata.street_trees t
          ON ST_DWithin(b.g, ST_Centroid(t.geometry), %s)
        ORDER BY ST_Distance(b.g, ST_Centroid(t.geometry))
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (street_no, f"{street_name.split()[0]}%", radius_m, limit_n))
        return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export tree-photo species candidates.")
    parser.add_argument(
        "--photo-index",
        default="PHOTOS KENSINGTON/csv/photo_address_index.csv",
        help="Path to photo address index CSV",
    )
    parser.add_argument(
        "--output",
        default="outputs/trees/tree_photo_targets.csv",
        help="Output CSV path",
    )
    parser.add_argument("--radius-m", type=float, default=60.0, help="Search radius for nearest trees")
    parser.add_argument("--limit", type=int, default=3, help="Max nearest species rows per photo")
    args = parser.parse_args()

    photo_index = Path(args.photo_index)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with photo_index.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            addr = (r.get("address_or_location") or "")
            if not PHOTO_KEYWORDS.search(addr):
                continue
            if FALSE_POSITIVE_CONTEXT.search(addr):
                continue
            rows.append(r)

    conn = get_connection()
    try:
        output_rows = []
        for row in rows:
            address = (row.get("address_or_location") or "").strip()
            street_no, street_name = parse_number_street(address)
            if street_no is None or not street_name:
                output_rows.append(
                    {
                        "filename": row.get("filename", ""),
                        "address_or_location": address,
                        "photo_source": row.get("source", ""),
                        "matched_address": "",
                        "rank": "",
                        "dist_m": "",
                        "common_name": "",
                        "botanic_name": "",
                        "match_status": "no_address_parse",
                    }
                )
                continue

            matches = fetch_nearest_species(conn, street_no, street_name, args.radius_m, args.limit)
            if not matches:
                output_rows.append(
                    {
                        "filename": row.get("filename", ""),
                        "address_or_location": address,
                        "photo_source": row.get("source", ""),
                        "matched_address": "",
                        "rank": "",
                        "dist_m": "",
                        "common_name": "",
                        "botanic_name": "",
                        "match_status": "no_near_species",
                    }
                )
                continue

            for i, (matched_address, common_name, botanic_name, dist_m) in enumerate(matches, start=1):
                output_rows.append(
                    {
                        "filename": row.get("filename", ""),
                        "address_or_location": address,
                        "photo_source": row.get("source", ""),
                        "matched_address": matched_address or "",
                        "rank": i,
                        "dist_m": dist_m,
                        "common_name": common_name or "",
                        "botanic_name": botanic_name or "",
                        "match_status": "matched",
                    }
                )
    finally:
        conn.close()

    with out_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "filename",
            "address_or_location",
            "photo_source",
            "matched_address",
            "rank",
            "dist_m",
            "common_name",
            "botanic_name",
            "match_status",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"[OK] Wrote {out_path} ({len(output_rows)} rows)")
    print(f"      input tree-related photos: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

