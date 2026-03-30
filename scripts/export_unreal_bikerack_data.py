#!/usr/bin/env python3
"""Export bike rack catalog + Unreal placement CSV from PostGIS field_bike_racks."""

from __future__ import annotations

import csv
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def fold(v: str) -> str:
    t = unicodedata.normalize("NFKD", (v or "").strip().lower()).encode("ascii", "ignore").decode("ascii")
    return t


def rack_key(type_support: str, nombre_velos: str) -> tuple[str, float]:
    t = fold(type_support)
    n = fold(nombre_velos)
    if "u" in t or "u-inverse" in t or "invers" in t:
        return "u_rack", 1.0
    if "spiral" in t:
        return "spiral_rack", 1.0
    if "ring" in t or "anneau" in t:
        return "ring_rack", 1.0
    if "6" in n or "8" in n:
        return "multi_rack", 1.15
    return "generic_rack", 1.0


def main() -> int:
    out_dir = Path("outputs/bikeracks")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            WITH study AS (
              SELECT ST_Transform(geometry, 2952) AS g
              FROM opendata.study_area
              LIMIT 1
            )
            SELECT
              b.id::text AS source_id,
              COALESCE(b.type_support, '') AS type_support,
              COALESCE(b.statut, '') AS statut,
              COALESCE(b.nombre_velos, '') AS nombre_velos,
              COALESCE(b.etat, '') AS etat,
              COALESCE(b.commentaires, '') AS commentaires,
              COALESCE(b.adresse, '') AS adresse,
              ST_X(ST_Transform(b.geom, 2952)) AS x_2952,
              ST_Y(ST_Transform(b.geom, 2952)) AS y_2952,
              ST_X(b.geom) AS lon,
              ST_Y(b.geom) AS lat
            FROM public.field_bike_racks b
            JOIN study s ON ST_Intersects(ST_Transform(b.geom, 2952), s.g)
            WHERE b.geom IS NOT NULL
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    instances = out_dir / "bikerack_instances_unreal_cm.csv"
    counts: dict[str, int] = {}
    with instances.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_id",
                "rack_key",
                "type_support",
                "statut",
                "nombre_velos",
                "etat",
                "asset_path",
                "x_cm",
                "y_cm",
                "z_cm",
                "yaw_deg",
                "uniform_scale",
                "lon",
                "lat",
                "metadata_json",
            ],
        )
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            key, scl = rack_key(r["type_support"], r["nombre_velos"])
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"bikerack_{i:04d}",
                    "source_id": r["source_id"],
                    "rack_key": key,
                    "type_support": r["type_support"],
                    "statut": r["statut"],
                    "nombre_velos": r["nombre_velos"],
                    "etat": r["etat"],
                    "asset_path": f"/Game/Street/BikeRack/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x_2952']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y_2952']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scl:.3f}",
                    "lon": f"{float(r['lon']):.8f}",
                    "lat": f"{float(r['lat']):.8f}",
                    "metadata_json": json.dumps(
                        {"adresse": r["adresse"], "commentaires": r["commentaires"]},
                        ensure_ascii=False,
                    ),
                }
            )

    (out_dir / "bikerack_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "rack_types": [{"rack_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {instances}")
    print(f"[OK] Wrote {out_dir / 'bikerack_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

