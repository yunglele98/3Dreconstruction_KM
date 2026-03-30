#!/usr/bin/env python3
"""Export parking infrastructure instances for Unreal placement."""

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
    return unicodedata.normalize("NFKD", (v or "").lower()).encode("ascii", "ignore").decode("ascii")


def classify_parking(type_stationnement: str, tarification: str, accessibilite: str, commentaires: str) -> str:
    t = fold(type_stationnement)
    pay = fold(tarification)
    acc = fold(accessibilite)
    c = fold(commentaires)
    if "access" in c or acc == "oui":
        if "public" in t or "payant" in pay:
            return "parking_accessible_bay"
    if "hors rue" in t or "lot" in t or "parking" in c:
        if "payant" in pay:
            return "parking_lot_paid"
        return "parking_lot"
    if "public" in t:
        if "payant" in pay:
            return "parking_meter"
        return "parking_surface_public"
    if "prive" in t:
        return "parking_private_pad"
    if "payant" in pay:
        return "parking_meter"
    return "parking_surface_public"


def default_scale(key: str) -> float:
    if key in {"parking_meter", "parking_accessible_bay"}:
        return 1.0
    if key in {"parking_lot_paid", "parking_lot"}:
        return 1.25
    return 1.1


def main() -> int:
    out = Path("outputs/parking")
    out.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            WITH s AS (
              SELECT ST_Transform(geometry,2952) AS g
              FROM opendata.study_area
              LIMIT 1
            )
            SELECT
              p.id::text AS source_id,
              COALESCE(p.type_stationnement, '') AS type_stationnement,
              COALESCE(p.reglementation_duree, '') AS reglementation_duree,
              COALESCE(p.accessibilite, '') AS accessibilite,
              COALESCE(p.nombre_places::text, '') AS nombre_places,
              COALESCE(p.tarification, '') AS tarification,
              COALESCE(p.commentaires, '') AS commentaires,
              ST_X(ST_Transform(p.geom,2952)) AS x,
              ST_Y(ST_Transform(p.geom,2952)) AS y
            FROM public.field_parking p, s
            WHERE p.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(p.geom,2952), s.g)
            ORDER BY p.id
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out / "parking_instances_unreal_cm.csv"
    counts = {}

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_table",
                "source_id",
                "parking_key",
                "asset_path",
                "x_cm",
                "y_cm",
                "z_cm",
                "yaw_deg",
                "uniform_scale",
                "metadata_json",
            ],
        )
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            key = classify_parking(
                r["type_stationnement"],
                r["tarification"],
                r["accessibilite"],
                r["commentaires"],
            )
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"pk_{i:04d}",
                    "source_table": "field_parking",
                    "source_id": r["source_id"],
                    "parking_key": key,
                    "asset_path": f"/Game/Street/Parking/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{default_scale(key):.3f}",
                    "metadata_json": json.dumps(
                        {
                            "type_stationnement": r["type_stationnement"],
                            "reglementation_duree": r["reglementation_duree"],
                            "accessibilite": r["accessibilite"],
                            "nombre_places": r["nombre_places"],
                            "tarification": r["tarification"],
                            "commentaires": r["commentaires"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    (out / "parking_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "parking_types": [
                    {"parking_key": k, "count": n}
                    for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out / 'parking_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

