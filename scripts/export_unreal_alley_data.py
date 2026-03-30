#!/usr/bin/env python3
"""Export alley infrastructure instances for Unreal placement."""

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


def classify_alley(type_voie: str, revetement: str, verdissement: str, etat: str) -> str:
    t = fold(type_voie)
    r = fold(revetement)
    g = fold(verdissement)
    e = fold(etat)

    if "pietonne" in t:
        return "alley_pedestrian"
    if "prive" in t or "service" in t:
        return "alley_service"
    if "partagee" in t:
        if "modere" in g or "vegetal" in g:
            return "alley_shared_green"
        return "alley_shared"
    if "vehiculaire" in t:
        if "gravier" in r:
            return "alley_vehicle_gravel"
        if "beton" in r:
            return "alley_vehicle_concrete"
        return "alley_vehicle_asphalt"
    if "critique" in e or "mauvais" in e:
        return "alley_degraded"
    return "alley_vehicle_asphalt"


def default_scale(key: str) -> float:
    if key in {"alley_service", "alley_pedestrian"}:
        return 0.95
    if key in {"alley_shared_green", "alley_shared"}:
        return 1.05
    if key == "alley_degraded":
        return 1.1
    return 1.0


def main() -> int:
    out = Path("outputs/alleys")
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
            WHERE a.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(a.geom,2952), s.g)
            ORDER BY a.id
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out / "alley_instances_unreal_cm.csv"
    counts = {}

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_table",
                "source_id",
                "alley_key",
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
            key = classify_alley(r["type_voie"], r["revetement"], r["verdissement"], r["etat"])
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"al_{i:04d}",
                    "source_table": "field_alleys",
                    "source_id": r["source_id"],
                    "alley_key": key,
                    "asset_path": f"/Game/Street/Alleys/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{default_scale(key):.3f}",
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

    (out / "alley_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "alley_types": [
                    {"alley_key": k, "count": n}
                    for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out / 'alley_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

