#!/usr/bin/env python3
"""Export Unreal target surfaces for printable features (signs/shopfront/posters/walls)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import psycopg2
import psycopg2.extras

from db_config import DB_CONFIG, get_connection

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "printable_features"
OUT_CSV = OUT_DIR / "printable_targets_unreal_cm.csv"
OUT_JSON = OUT_DIR / "printable_targets_catalog.json"

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def classify_sign(type_panneau: str) -> str:
    t = (type_panneau or "").lower()
    if "limite" in t or "speed" in t or "sens unique" in t:
        return "street_sign_face"
    if "avert" in t:
        return "warning_sign_face"
    if "interdiction" in t or "restriction" in t:
        return "regulatory_sign_face"
    return "street_sign_face"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

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
            signs AS (
              SELECT
                'field_signs'::text AS src,
                fs.id::text AS src_id,
                COALESCE(fs.type_panneau,'') AS type_a,
                COALESCE(fs.etat_panneau,'') AS type_b,
                COALESCE(fs.support,'') AS type_c,
                COALESCE(fs.commentaires,'') AS comments,
                ST_X(ST_Transform(fs.geom,2952)) AS x,
                ST_Y(ST_Transform(fs.geom,2952)) AS y
              FROM public.field_signs fs, s
              WHERE fs.geom IS NOT NULL
                AND ST_Intersects(ST_Transform(fs.geom,2952), s.g)
            ),
            est AS (
              SELECT
                'field_establishments'::text AS src,
                fe.id::text AS src_id,
                COALESCE(fe.nom_etablissement,'') AS type_a,
                COALESCE(fe.type_etablissement,'') AS type_b,
                COALESCE(fe.etat,'') AS type_c,
                COALESCE(fe.commentaires,'') AS comments,
                ST_X(ST_Transform(fe.geom,2952)) AS x,
                ST_Y(ST_Transform(fe.geom,2952)) AS y
              FROM public.field_establishments fe, s
              WHERE fe.geom IS NOT NULL
                AND ST_Intersects(ST_Transform(fe.geom,2952), s.g)
            ),
            art AS (
              SELECT
                'field_public_art'::text AS src,
                fa.id::text AS src_id,
                COALESCE(fa.titre_oeuvre,'') AS type_a,
                COALESCE(fa.forme_art,'') AS type_b,
                COALESCE(fa.etat,'') AS type_c,
                COALESCE(fa.commentaires,'') AS comments,
                ST_X(ST_Transform(fa.geom,2952)) AS x,
                ST_Y(ST_Transform(fa.geom,2952)) AS y
              FROM public.field_public_art fa, s
              WHERE fa.geom IS NOT NULL
                AND ST_Intersects(ST_Transform(fa.geom,2952), s.g)
            )
            SELECT * FROM signs
            UNION ALL
            SELECT * FROM est
            UNION ALL
            SELECT * FROM art
            ORDER BY src, src_id
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    out = []
    cats = {}
    i = 1
    for r in rows:
        if r['src'] == 'field_signs':
            k = classify_sign(r['type_a'])
            scale = 1.0
        elif r['src'] == 'field_establishments':
            k = 'shop_sign_band'
            scale = 1.35
        else:
            k = 'mural_wall_panel'
            scale = 1.6
        cats[k] = cats.get(k, 0) + 1
        out.append({
            'target_id': f'pf_{i:04d}',
            'source_table': r['src'],
            'source_id': r['src_id'],
            'target_surface_key': k,
            'x_cm': f"{(float(r['x'])-ORIGIN_X)*100.0:.1f}",
            'y_cm': f"{(float(r['y'])-ORIGIN_Y)*100.0:.1f}",
            'z_cm': '130.0' if k.endswith('sign_face') else ('240.0' if k=='shop_sign_band' else '160.0'),
            'yaw_deg': '0.0',
            'uniform_scale': f'{scale:.3f}',
            'metadata_json': json.dumps({'type_a': r['type_a'], 'type_b': r['type_b'], 'type_c': r['type_c'], 'comments': r['comments']}, ensure_ascii=False),
        })
        i += 1

    with OUT_CSV.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [])
        w.writeheader(); w.writerows(out)

    OUT_JSON.write_text(json.dumps({'count': len(out), 'surface_types': [{'target_surface_key': k, 'count': n} for k, n in sorted(cats.items(), key=lambda kv: kv[1], reverse=True)]}, indent=2), encoding='utf-8')

    print(f'[OK] Wrote {OUT_CSV}')
    print(f'[OK] Wrote {OUT_JSON}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

