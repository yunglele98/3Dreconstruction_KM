#!/usr/bin/env python3
"""Export pole catalog + Unreal placement CSV from PostGIS field_poles."""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


@dataclass
class PoleRow:
    source_id: str
    pole_key: str
    sous_type: str
    etat: str
    x_2952: float
    y_2952: float
    lon: float
    lat: float
    asset_path: str
    base_height_m: float
    base_radius_m: float
    meta: str


def fold_text(v: str) -> str:
    txt = (v or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return txt


def classify_pole(sous_type: str) -> tuple[str, float, float]:
    t = fold_text(sous_type)
    if "eclairage" in t:
        return "streetlight_pole", 7.5, 0.09
    if "signal" in t:
        return "sign_pole", 3.2, 0.04
    if "electrique" in t or "electri" in t:
        return "utility_pole", 9.0, 0.14
    return "generic_pole", 5.0, 0.06


def fetch_poles(conn) -> list[PoleRow]:
    query = """
        WITH study AS (
            SELECT ST_Transform(geometry, 2952) AS geom_2952
            FROM opendata.study_area
            LIMIT 1
        )
        SELECT
            p.id::text AS source_id,
            COALESCE(p.sous_type, '') AS sous_type,
            COALESCE(p.etat, '') AS etat,
            COALESCE(p.commentaires, '') AS commentaires,
            COALESCE(p.adresse, '') AS adresse,
            ST_X(ST_Transform(p.geom, 2952)) AS x_2952,
            ST_Y(ST_Transform(p.geom, 2952)) AS y_2952,
            ST_X(p.geom) AS lon,
            ST_Y(p.geom) AS lat
        FROM public.field_poles p
        JOIN study s
          ON ST_Intersects(ST_Transform(p.geom, 2952), s.geom_2952)
        WHERE p.geom IS NOT NULL
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()

    out: list[PoleRow] = []
    for r in rows:
        pole_key, h, rad = classify_pole(r["sous_type"])
        out.append(
            PoleRow(
                source_id=r["source_id"],
                pole_key=pole_key,
                sous_type=r["sous_type"],
                etat=r["etat"],
                x_2952=float(r["x_2952"]),
                y_2952=float(r["y_2952"]),
                lon=float(r["lon"]),
                lat=float(r["lat"]),
                asset_path=f"/Game/Street/Pole/SM_{pole_key}_A_standard",
                base_height_m=h,
                base_radius_m=rad,
                meta=json.dumps(
                    {"adresse": r["adresse"], "commentaires": r["commentaires"]},
                    ensure_ascii=False,
                ),
            )
        )
    return out


def main() -> int:
    out_dir = Path("outputs/poles")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        rows = fetch_poles(conn)
    finally:
        conn.close()

    instances = out_dir / "pole_instances_unreal_cm.csv"
    with instances.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance_id",
                "source_id",
                "pole_key",
                "sous_type",
                "etat",
                "asset_path",
                "x_cm",
                "y_cm",
                "z_cm",
                "yaw_deg",
                "uniform_scale",
                "height_m",
                "radius_m",
                "lon",
                "lat",
                "metadata_json",
            ],
        )
        writer.writeheader()
        for i, r in enumerate(rows, start=1):
            writer.writerow(
                {
                    "instance_id": f"pole_{i:04d}",
                    "source_id": r.source_id,
                    "pole_key": r.pole_key,
                    "sous_type": r.sous_type,
                    "etat": r.etat,
                    "asset_path": r.asset_path,
                    "x_cm": f"{(r.x_2952 - ORIGIN_X) * 100.0:.1f}",
                    "y_cm": f"{(r.y_2952 - ORIGIN_Y) * 100.0:.1f}",
                    "z_cm": "0.0",
                    "yaw_deg": "0.0",
                    "uniform_scale": "1.0",
                    "height_m": f"{r.base_height_m:.2f}",
                    "radius_m": f"{r.base_radius_m:.3f}",
                    "lon": f"{r.lon:.8f}",
                    "lat": f"{r.lat:.8f}",
                    "metadata_json": r.meta,
                }
            )

    counts = {}
    for r in rows:
        counts[r.pole_key] = counts.get(r.pole_key, 0) + 1
    catalog = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_count": len(rows),
        "pole_types": [{"pole_key": k, "count": n} for k, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)],
    }
    (out_dir / "pole_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    print(f"[OK] Wrote {instances}")
    print(f"[OK] Wrote {out_dir / 'pole_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

