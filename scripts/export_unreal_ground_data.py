#!/usr/bin/env python3
"""Export asphalt/concrete ground elements and detail props for Unreal."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86
STEP_ROAD = 18.0
STEP_ALLEY = 14.0


def main() -> int:
    out_dir = Path("outputs/ground")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            WITH s AS (
              SELECT ST_Transform(geometry, 2952) AS g
              FROM opendata.study_area
              LIMIT 1
            ),
            road_lines AS (
              SELECT
                r.gid::text AS src_id,
                d.geom AS geom
              FROM opendata.road_centerlines r, s
              CROSS JOIN LATERAL ST_Dump(r.geom) d
              WHERE ST_Intersects(r.geom, s.g)
                AND GeometryType(d.geom) = 'LINESTRING'
            ),
            road_pts AS (
              SELECT
                'road_asphalt'::text AS ground_key,
                src_id,
                i AS seq,
                ST_LineInterpolatePoint(geom, CASE WHEN ST_Length(geom)=0 THEN 0 ELSE LEAST(1.0, (i * %s) / ST_Length(geom)) END) AS p
              FROM road_lines
              CROSS JOIN LATERAL generate_series(0, GREATEST(0, FLOOR(ST_Length(geom)/%s)::int)) AS i
            ),
            alley_pts AS (
              SELECT
                'alley_asphalt'::text AS ground_key,
                a.id::text AS src_id,
                0 AS seq,
                ST_Transform(a.geom,2952) AS p
              FROM public.field_alleys a, s
              WHERE a.geom IS NOT NULL AND ST_Intersects(ST_Transform(a.geom,2952), s.g)
            ),
            sidewalk_pts AS (
              SELECT
                'sidewalk_concrete'::text AS ground_key,
                w.gid::text AS src_id,
                0 AS seq,
                ST_Centroid(w.geometry) AS p,
                GREATEST(ST_Area(w.geometry), 1.0) AS area
              FROM opendata.sidewalks w, s
              WHERE ST_Intersects(w.geometry, s.g)
            ),
            parking_pts AS (
              SELECT
                CASE
                  WHEN COALESCE(p.type_stationnement,'') ILIKE '%%public%%' THEN 'parking_public'
                  WHEN COALESCE(p.type_stationnement,'') ILIKE '%%priv%%' THEN 'parking_private'
                  ELSE 'parking_hardscape'
                END AS ground_key,
                p.id::text AS src_id,
                0 AS seq,
                ST_Transform(p.geom,2952) AS p
              FROM public.field_parking p, s
              WHERE p.geom IS NOT NULL AND ST_Intersects(ST_Transform(p.geom,2952), s.g)
            ),
            intersection_pts AS (
              SELECT
                'intersection_hardscape'::text AS ground_key,
                i.id::text AS src_id,
                0 AS seq,
                ST_Transform(i.geom,2952) AS p
              FROM public.field_intersections i, s
              WHERE i.geom IS NOT NULL AND ST_Intersects(ST_Transform(i.geom,2952), s.g)
            )
            SELECT ground_key, src_id, seq, ST_X(p) AS x, ST_Y(p) AS y, NULL::double precision AS aux
            FROM road_pts
            UNION ALL
            SELECT ground_key, src_id, seq, ST_X(p), ST_Y(p), NULL::double precision AS aux
            FROM alley_pts
            UNION ALL
            SELECT ground_key, src_id, seq, ST_X(p), ST_Y(p), area::double precision AS aux
            FROM sidewalk_pts
            UNION ALL
            SELECT ground_key, src_id, seq, ST_X(p), ST_Y(p), NULL::double precision AS aux
            FROM parking_pts
            UNION ALL
            SELECT ground_key, src_id, seq, ST_X(p), ST_Y(p), NULL::double precision AS aux
            FROM intersection_pts
            ORDER BY ground_key, src_id, seq
            """,
            (STEP_ROAD, STEP_ROAD),
        )
        base = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    rows = []
    idx = 0
    # Base ground rows.
    for r in base:
        idx += 1
        scale = 1.0
        if r["ground_key"] == "sidewalk_concrete" and r["aux"]:
            scale = min(2.4, max(0.8, (float(r["aux"]) ** 0.5) / 3.0))
        rows.append(
            {
                "instance_id": f"ground_{idx:05d}",
                "source_id": f"{r['ground_key']}:{r['src_id']}:{r['seq']}",
                "ground_key": r["ground_key"],
                "asset_path": f"/Game/Ground/SM_{r['ground_key']}_A_standard",
                "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                "z_cm": "0.0",
                "yaw_deg": "0.0",
                "uniform_scale": f"{scale:.3f}",
                "metadata_json": json.dumps({"aux": r["aux"]}),
            }
        )

    # Derived detail props from road/sidewalk distribution.
    detail_rows = []
    d = 0
    for i, row in enumerate(rows):
        gk = row["ground_key"]
        if gk == "road_asphalt":
            if i % 6 == 0:
                d += 1
                detail_rows.append(
                    {
                        **row,
                        "instance_id": f"ground_detail_{d:05d}",
                        "ground_key": "manhole_cover",
                        "asset_path": "/Game/Ground/SM_manhole_cover_A_standard",
                        "uniform_scale": "0.900",
                    }
                )
            elif i % 9 == 0:
                d += 1
                detail_rows.append(
                    {
                        **row,
                        "instance_id": f"ground_detail_{d:05d}",
                        "ground_key": "storm_drain",
                        "asset_path": "/Game/Ground/SM_storm_drain_A_standard",
                        "uniform_scale": "0.750",
                    }
                )
            elif i % 4 == 0:
                d += 1
                detail_rows.append(
                    {
                        **row,
                        "instance_id": f"ground_detail_{d:05d}",
                        "ground_key": "asphalt_patch_decal",
                        "asset_path": "/Game/Ground/SM_asphalt_patch_decal_A_standard",
                        "uniform_scale": "1.100",
                    }
                )
        if gk == "sidewalk_concrete" and i % 3 == 0:
            d += 1
            detail_rows.append(
                {
                    **row,
                    "instance_id": f"ground_detail_{d:05d}",
                    "ground_key": "concrete_patch_decal",
                    "asset_path": "/Game/Ground/SM_concrete_patch_decal_A_standard",
                    "uniform_scale": "0.950",
                }
            )
        if gk in {"sidewalk_concrete", "intersection_hardscape"} and i % 5 == 0:
            d += 1
            detail_rows.append(
                {
                    **row,
                    "instance_id": f"ground_detail_{d:05d}",
                    "ground_key": "curb_segment",
                    "asset_path": "/Game/Ground/SM_curb_segment_A_standard",
                    "uniform_scale": "1.000",
                }
            )

    all_rows = rows + detail_rows

    out_csv = out_dir / "ground_instances_unreal_cm.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fields = [
            "instance_id",
            "source_id",
            "ground_key",
            "asset_path",
            "x_cm",
            "y_cm",
            "z_cm",
            "yaw_deg",
            "uniform_scale",
            "metadata_json",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    counts = {}
    for r in all_rows:
        counts[r["ground_key"]] = counts.get(r["ground_key"], 0) + 1
    catalog = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_count": len(all_rows),
        "ground_types": [{"ground_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
    }
    (out_dir / "ground_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out_dir / 'ground_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

