#!/usr/bin/env python3
"""Export urban sign instances + catalog for Unreal."""

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


def sign_key(type_panneau: str) -> str:
    t = fold(type_panneau)
    if "vitesse" in t or "speed" in t:
        return "speed_sign"
    if "interdiction" in t or "restriction" in t:
        return "restriction_sign"
    if "avertissement" in t or "warning" in t:
        return "warning_sign"
    if "sens unique" in t or "one way" in t:
        return "oneway_sign"
    if "information" in t or "direction" in t:
        return "info_sign"
    return "generic_sign"


def scale_for_key(key: str) -> float:
    if key in {"warning_sign", "speed_sign"}:
        return 1.05
    if key in {"restriction_sign", "oneway_sign"}:
        return 0.95
    return 1.0


def main() -> int:
    out = Path("outputs/signs")
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
              fs.id::text AS source_id,
              COALESCE(fs.type_panneau, '') AS type_panneau,
              COALESCE(fs.support, '') AS support,
              COALESCE(fs.etat_panneau, '') AS etat_panneau,
              COALESCE(fs.commentaires, '') AS commentaires,
              COALESCE(fs.adresse, '') AS adresse,
              ST_X(ST_Transform(fs.geom,2952)) AS x_2952,
              ST_Y(ST_Transform(fs.geom,2952)) AS y_2952,
              ST_X(fs.geom) AS lon,
              ST_Y(fs.geom) AS lat
            FROM public.field_signs fs, s
            WHERE fs.geom IS NOT NULL
              AND ST_Intersects(ST_Transform(fs.geom,2952), s.g)
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out_csv = out / "sign_instances_unreal_cm.csv"
    counts = {}
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_id",
                "sign_key",
                "type_panneau",
                "support",
                "etat_panneau",
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
            key = sign_key(r["type_panneau"])
            counts[key] = counts.get(key, 0) + 1
            w.writerow(
                {
                    "instance_id": f"sign_{i:04d}",
                    "source_id": r["source_id"],
                    "sign_key": key,
                    "type_panneau": r["type_panneau"],
                    "support": r["support"],
                    "etat_panneau": r["etat_panneau"],
                    "asset_path": f"/Game/Street/Signs/SM_{key}_A_standard",
                    "x_cm": f"{(float(r['x_2952']) - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(float(r['y_2952']) - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": f"{scale_for_key(key):.3f}",
                    "lon": f"{float(r['lon']):.8f}",
                    "lat": f"{float(r['lat']):.8f}",
                    "metadata_json": json.dumps({"adresse": r["adresse"], "commentaires": r["commentaires"]}, ensure_ascii=False),
                }
            )

    (out / "sign_catalog.json").write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance_count": len(rows),
                "sign_types": [{"sign_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_csv}")
    print(f"[OK] Wrote {out / 'sign_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

