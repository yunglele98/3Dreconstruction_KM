#!/usr/bin/env python3
"""Export intersection infrastructure instances for Unreal placement."""

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


def classify_intersection(type_intersection: str, has_signal: str, safety: str) -> str:
    t = fold(type_intersection)
    s = fold(has_signal)
    q = fold(safety)

    if "oui" in s:
        return "intersection_signalized"
    if "3 branches" in t or "t" in t:
        if "tres faible" in q or "faible" in q:
            return "intersection_t_dangerous"
        return "intersection_t_standard"
    if "4" in t or "cross" in t:
        return "intersection_cross"
    return "intersection_t_standard"


def default_scale(key: str) -> float:
    if key == "intersection_signalized":
        return 1.2
    if key == "intersection_t_dangerous":
        return 1.1
    return 1.0


def main() -> int:
    out = Path("outputs/intersections")
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
              i.id::text AS source_id,
              COALESCE(i.nom_rue1, '') AS nom_rue1,
              COALESCE(i.nom_rue2, '') AS nom_rue2,
              COALESCE(i.type_intersection, '') AS type_intersection,
              COALESCE(i.presence_feuxcirculation, '') AS presence_feuxcirculation,
              COALESCE(i.piste_cyclable, '') AS piste_cyclable,
              COALESCE(i.securite, '') AS securite,
              COALESCE(i.commentaires, '') AS commentaires,
              ST_X(ST_Transform(i.geom,2952)) AS x,
              ST_Y(ST_Transform(i.geom,2952)) AS y
            FROM public.field_intersections i, s
            WHERE i.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(i.geom,2952), s.g)
            ORDER BY i.id
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out / "intersection_instances_unreal_cm.csv"
    counts = {}

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_table",
                "source_id",
                "intersection_key",
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
            key = classify_intersection(
                r["type_intersection"],
                r["presence_feuxcirculation"],
                r["securite"],
            )
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"ix_{i:04d}",
                    "source_table": "field_intersections",
                    "source_id": r["source_id"],
                    "intersection_key": key,
                    "asset_path": f"/Game/Street/Intersections/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{default_scale(key):.3f}",
                    "metadata_json": json.dumps(
                        {
                            "nom_rue1": r["nom_rue1"],
                            "nom_rue2": r["nom_rue2"],
                            "type_intersection": r["type_intersection"],
                            "presence_feuxcirculation": r["presence_feuxcirculation"],
                            "piste_cyclable": r["piste_cyclable"],
                            "securite": r["securite"],
                            "commentaires": r["commentaires"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    (out / "intersection_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "intersection_types": [
                    {"intersection_key": k, "count": n}
                    for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out / 'intersection_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

