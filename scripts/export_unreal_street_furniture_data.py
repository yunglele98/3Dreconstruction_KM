#!/usr/bin/env python3
"""Export unified street furniture instances (bus shelters, public art, terraces)."""

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


def classify_art(forme_art: str) -> str:
    f = fold(forme_art)
    if "mural" in f:
        return "public_art_mural"
    if "sculpt" in f or "statue" in f:
        return "public_art_sculpture"
    return "public_art_installation"


def classify_terrace(type_terrasse: str) -> str:
    t = fold(type_terrasse)
    if "platform" in t or "deck" in t:
        return "terrace_platform"
    if "patio" in t:
        return "terrace_patio"
    return "terrace_module"


def classify_shelter(type_abribus: str) -> str:
    t = fold(type_abribus)
    if "glass" in t or "vitre" in t:
        return "bus_shelter_glass"
    return "bus_shelter_standard"


def main() -> int:
    out = Path("outputs/street_furniture")
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
            ),
            shelters AS (
              SELECT
                'bus_shelter'::text AS source_type,
                b.id::text AS source_id,
                COALESCE(b.type_abribus, '') AS detail_a,
                COALESCE(b.statut, '') AS detail_b,
                COALESCE(b.etat, '') AS detail_c,
                COALESCE(b.commentaires, '') AS comments,
                ST_X(ST_Transform(b.geom,2952)) AS x,
                ST_Y(ST_Transform(b.geom,2952)) AS y
              FROM public.field_bus_shelters b, s
              WHERE b.geom IS NOT NULL AND ST_Intersects(ST_Transform(b.geom,2952), s.g)
            ),
            arts AS (
              SELECT
                'public_art'::text AS source_type,
                a.id::text AS source_id,
                COALESCE(a.forme_art, '') AS detail_a,
                COALESCE(a.titre_oeuvre, '') AS detail_b,
                COALESCE(a.etat, '') AS detail_c,
                COALESCE(a.commentaires, '') AS comments,
                ST_X(ST_Transform(a.geom,2952)) AS x,
                ST_Y(ST_Transform(a.geom,2952)) AS y
              FROM public.field_public_art a, s
              WHERE a.geom IS NOT NULL AND ST_Intersects(ST_Transform(a.geom,2952), s.g)
            ),
            terraces AS (
              SELECT
                'terrace'::text AS source_type,
                t.id::text AS source_id,
                COALESCE(t.type_terrasse, '') AS detail_a,
                COALESCE(t.nom_terrasse, '') AS detail_b,
                COALESCE(t.statut, '') AS detail_c,
                COALESCE(t.commentaires, '') AS comments,
                ST_X(ST_Transform(t.geom,2952)) AS x,
                ST_Y(ST_Transform(t.geom,2952)) AS y
              FROM public.field_terraces t, s
              WHERE t.geom IS NOT NULL AND ST_Intersects(ST_Transform(t.geom,2952), s.g)
            )
            SELECT * FROM shelters
            UNION ALL
            SELECT * FROM arts
            UNION ALL
            SELECT * FROM terraces
            ORDER BY source_type, source_id
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out / "street_furniture_instances_unreal_cm.csv"
    counts = {}
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_type",
                "source_id",
                "furniture_key",
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
            if r["source_type"] == "bus_shelter":
                key = classify_shelter(r["detail_a"])
                scale = 1.25
            elif r["source_type"] == "public_art":
                key = classify_art(r["detail_a"])
                scale = 1.1
            else:
                key = classify_terrace(r["detail_a"])
                scale = 1.2
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"sf_{i:04d}",
                    "source_type": r["source_type"],
                    "source_id": r["source_id"],
                    "furniture_key": key,
                    "asset_path": f"/Game/Street/Furniture/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scale:.3f}",
                    "metadata_json": json.dumps(
                        {
                            "detail_a": r["detail_a"],
                            "detail_b": r["detail_b"],
                            "detail_c": r["detail_c"],
                            "comments": r["comments"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    (out / "street_furniture_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "furniture_types": [{"furniture_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out / 'street_furniture_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

