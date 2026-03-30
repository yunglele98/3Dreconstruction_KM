#!/usr/bin/env python3
"""Export vertical hardscape instances for Unreal (foundations/curbs/stairs/loading edges)."""

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


def main() -> int:
    out_dir = Path("outputs/vertical_hardscape")
    out_dir.mkdir(parents=True, exist_ok=True)

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
            footprint_lines AS (
              SELECT
                b.gid::text AS src_id,
                ST_LineMerge(ST_Boundary(ST_CollectionExtract(b.geom, 3))) AS ln,
                COALESCE(b."ELEVATI4", 0) AS elev
              FROM opendata.building_footprints b, s
              WHERE ST_Intersects(b.geom, s.g)
            ),
            foundation_pts AS (
              SELECT
                CASE WHEN (row_number() OVER ()) % 7 = 0 THEN 'retaining_wall_segment' ELSE 'foundation_wall_segment' END AS hardscape_key,
                src_id,
                i AS seq,
                ST_LineInterpolatePoint(ln, CASE WHEN ST_Length(ln)=0 THEN 0 ELSE LEAST(1.0, (i*14.0)/ST_Length(ln)) END) AS p,
                elev
              FROM footprint_lines
              CROSS JOIN LATERAL generate_series(0, GREATEST(0, FLOOR(ST_Length(ln)/14.0)::int)) AS i
              WHERE ln IS NOT NULL AND GeometryType(ln) = 'LINESTRING'
            ),
            sidewalk_lines AS (
              SELECT
                w.gid::text AS src_id,
                d.geom AS ln
              FROM opendata.sidewalks w, s
              CROSS JOIN LATERAL ST_Dump(ST_Boundary(ST_CollectionExtract(w.geometry, 3))) d
              WHERE ST_Intersects(w.geometry, s.g)
                AND GeometryType(d.geom) = 'LINESTRING'
            ),
            curb_pts AS (
              SELECT
                'curb_vertical_segment'::text AS hardscape_key,
                src_id,
                i AS seq,
                ST_LineInterpolatePoint(ln, CASE WHEN ST_Length(ln)=0 THEN 0 ELSE LEAST(1.0, (i*18.0)/ST_Length(ln)) END) AS p,
                NULL::double precision AS elev
              FROM sidewalk_lines
              CROSS JOIN LATERAL generate_series(0, GREATEST(0, FLOOR(ST_Length(ln)/18.0)::int)) AS i
            ),
            stair_pts AS (
              SELECT
                'stair_module'::text AS hardscape_key,
                t.id::text AS src_id,
                0 AS seq,
                ST_Transform(t.geom,2952) AS p,
                NULL::double precision AS elev
              FROM public.field_terraces t, s
              WHERE t.geom IS NOT NULL AND ST_Intersects(ST_Transform(t.geom,2952), s.g)
            ),
            loading_pts AS (
              SELECT
                'loading_edge'::text AS hardscape_key,
                p.id::text AS src_id,
                0 AS seq,
                ST_Transform(p.geom,2952) AS p,
                NULL::double precision AS elev
              FROM public.field_parking p, s
              WHERE p.geom IS NOT NULL AND ST_Intersects(ST_Transform(p.geom,2952), s.g)
            )
            SELECT hardscape_key, src_id, seq, ST_X(p) AS x, ST_Y(p) AS y, elev
            FROM foundation_pts
            UNION ALL
            SELECT hardscape_key, src_id, seq, ST_X(p), ST_Y(p), elev
            FROM curb_pts
            UNION ALL
            SELECT hardscape_key, src_id, seq, ST_X(p), ST_Y(p), elev
            FROM stair_pts
            UNION ALL
            SELECT hardscape_key, src_id, seq, ST_X(p), ST_Y(p), elev
            FROM loading_pts
            ORDER BY hardscape_key, src_id, seq
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out_dir / "vertical_hardscape_instances_unreal_cm.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_id",
                "hardscape_key",
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
            scale = 1.0
            if r["hardscape_key"] == "retaining_wall_segment":
                scale = 1.15
            if r["hardscape_key"] == "stair_module":
                scale = 1.2
            w.writerow(
                {
                    "instance_id": f"vhard_{i:05d}",
                    "source_id": f"{r['hardscape_key']}:{r['src_id']}:{r['seq']}",
                    "hardscape_key": r["hardscape_key"],
                    "asset_path": f"/Game/Hardscape/Vertical/SM_{r['hardscape_key']}_A_standard",
                    "x_cm": f"{(float(r['x']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scale:.3f}",
                    "metadata_json": json.dumps({"elev": r["elev"]}),
                }
            )

    counts = {}
    for r in rows:
        counts[r["hardscape_key"]] = counts.get(r["hardscape_key"], 0) + 1
    (out_dir / "vertical_hardscape_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "hardscape_types": [{"hardscape_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out_dir / 'vertical_hardscape_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

