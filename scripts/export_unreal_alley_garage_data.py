#!/usr/bin/env python3
"""Export alley + garage instances for Unreal placement."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "alley_garages"
REF_CSV = OUT_DIR / "photo_reference_catalog.csv"
ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def fold(v: str) -> str:
    return unicodedata.normalize("NFKD", (v or "").lower()).encode("ascii", "ignore").decode("ascii")


def classify_alley(type_voie: str, revetement: str, verdissement: str, etat: str) -> str:
    t = fold(type_voie)
    r = fold(revetement)
    g = fold(verdissement)
    e = fold(etat)
    if "pietonne" in t:
        return "alley_pedestrian_cutthrough"
    if "prive" in t or "service" in t:
        return "alley_service_lane"
    if "partagee" in t and ("modere" in g or "vegetal" in g):
        return "alley_green_edge"
    if "partagee" in t:
        return "alley_shared_surface"
    if "critique" in e or "mauvais" in e:
        return "alley_degraded_patch"
    if "gravier" in r:
        return "alley_vehicle_gravel"
    if "beton" in r:
        return "alley_vehicle_concrete"
    return "alley_vehicle_asphalt"


def classify_photo_category(category: str, loc: str) -> str:
    c = fold(category)
    l = fold(loc)
    if "garage_structured_interior_marker" in c:
        return "garage_structured_interior_marker"
    if "garage_structured_entrance" in c:
        return "garage_structured_entrance"
    if "garage_row_rollup_tagged" in c:
        return "garage_row_rollup_tagged"
    if "garage_residential_pair" in c:
        return "garage_residential_pair"
    if "alley_hazard_segment" in c:
        return "alley_hazard_segment"
    if "alley_graffiti_wall" in c:
        return "alley_graffiti_wall"
    if "garage" in l:
        return "garage_single_modern"
    if "chain" in l or "fence" in l:
        return "alley_chainlink_edge"
    return "alley_service_corridor"


def scale_for_key(key: str) -> float:
    if key.startswith("garage_structured"):
        return 1.35
    if key.startswith("garage_row") or key.startswith("garage_residential"):
        return 1.2
    if key.startswith("garage_single"):
        return 1.1
    if key in {"alley_graffiti_wall", "alley_chainlink_edge", "alley_service_corridor"}:
        return 1.05
    return 1.0


def project_wgs84(cur, lon: float, lat: float):
    cur.execute(
        """
        SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952)),
               ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952))
        """,
        (lon, lat, lon, lat),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return float(row["st_x"]), float(row["st_y"])
    return float(row[0]), float(row[1])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            WITH s AS (
              SELECT ST_Transform(geometry,2952) AS g FROM opendata.study_area LIMIT 1
            )
            SELECT
              a.id::text AS source_id,
              COALESCE(a.nom_ruelle, '') AS nom_ruelle,
              COALESCE(a.type_voie, '') AS type_voie,
              COALESCE(a.revetement, '') AS revetement,
              COALESCE(a.verdissement, '') AS verdissement,
              COALESCE(a.collecte_ordures, '') AS collecte_ordures,
              COALESCE(a.etat, '') AS etat,
              ST_X(ST_Transform(a.geom,2952)) AS x,
              ST_Y(ST_Transform(a.geom,2952)) AS y
            FROM public.field_alleys a, s
            WHERE a.geom IS NOT NULL AND ST_Intersects(ST_Transform(a.geom,2952), s.g)
            ORDER BY a.id
            """
        )
        alley_rows = cur.fetchall()

        out_rows = []
        counts = {}
        i = 1

        for r in alley_rows:
            key = classify_alley(r["type_voie"], r["revetement"], r["verdissement"], r["etat"])
            counts[key] = counts.get(key, 0) + 1
            out_rows.append(
                {
                    "instance_id": f"ag_{i:04d}",
                    "source_table": "field_alleys",
                    "source_id": r["source_id"],
                    "alley_garage_key": key,
                    "asset_path": f"/Game/Street/AlleyGarage/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scale_for_key(key):.3f}",
                    "metadata_json": json.dumps(
                        {
                            "nom_ruelle": r["nom_ruelle"],
                            "type_voie": r["type_voie"],
                            "revetement": r["revetement"],
                            "verdissement": r["verdissement"],
                            "collecte_ordures": r["collecte_ordures"],
                            "etat": r["etat"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            i += 1

        # Add photo-driven garage/alley markers where coordinates exist in photo index text
        with REF_CSV.open("r", encoding="utf-8", newline="") as f:
            ref_rows = list(csv.DictReader(f))
        alley_xy = [(float(r["x"]), float(r["y"])) for r in alley_rows]
        coord_pat = re.compile(r"^-?\d+\.\d+$")
        for r in ref_rows:
            lat_s = (r.get("lat") or "").strip()
            lon_s = (r.get("lon") or "").strip()
            loc = r.get("address_or_location") or ""
            key = classify_photo_category(r.get("category") or "", loc)
            has_coord = coord_pat.match(lat_s) and coord_pat.match(lon_s)
            source_table = "photo_reference"
            if has_coord:
                lat = float(lat_s)
                lon = float(lon_s)
                x, y = project_wgs84(cur, lon, lat)
            else:
                # Promote garage-tagged references even without explicit coordinates by
                # anchoring to surveyed alley points with a small deterministic offset.
                if not key.startswith("garage_"):
                    continue
                if not alley_xy:
                    continue
                anchor = alley_xy[(i - 1) % len(alley_xy)]
                offset_x = ((i % 5) - 2) * 1.8
                offset_y = (((i // 5) % 5) - 2) * 1.2
                x = anchor[0] + offset_x
                y = anchor[1] + offset_y
                source_table = "photo_reference_inferred"
            counts[key] = counts.get(key, 0) + 1
            out_rows.append(
                {
                    "instance_id": f"ag_{i:04d}",
                    "source_table": source_table,
                    "source_id": r.get("filename") or "",
                    "alley_garage_key": key,
                    "asset_path": f"/Game/Street/AlleyGarage/SM_{key}_A_standard",
                    "x_cm": f"{(float(x) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(y) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scale_for_key(key):.3f}",
                    "metadata_json": json.dumps(
                        {
                            "location_text": loc,
                            "category": r.get("category") or "",
                            "photo_path": r.get("photo_path") or "",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            i += 1

        out_csv = OUT_DIR / "alley_garage_instances_unreal_cm.csv"
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
            w.writeheader()
            w.writerows(out_rows)

        (OUT_DIR / "alley_garage_catalog.json").write_text(
            json.dumps(
                {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "instance_count": len(out_rows),
                    "types": [{"alley_garage_key": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[OK] Wrote {out_csv}")
        print(f"[OK] Wrote {OUT_DIR / 'alley_garage_catalog.json'}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

