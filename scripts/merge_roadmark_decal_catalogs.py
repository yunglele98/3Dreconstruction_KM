#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_A = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_extracted.csv'
IN_B = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog_synthetic.csv'
OUT_CSV = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog.csv'
OUT_JSON = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog.json'


def read(p: Path):
    if not p.exists():
        return []
    return list(csv.DictReader(p.open('r', encoding='utf-8', newline='')))


def main() -> int:
    rows = []
    seen = set()
    for rec in read(IN_A) + read(IN_B):
        did = rec.get('decal_id') or ''
        if not did or did in seen:
            continue
        seen.add(did)
        rows.append(rec)

    with OUT_CSV.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['decal_id','category','source_filename','decal_texture_path','alpha_coverage','source_type'])
        w.writeheader()
        if rows:
            w.writerows(rows)

    OUT_JSON.write_text(json.dumps({'count': len(rows), 'items': rows}, indent=2), encoding='utf-8')
    print('[OK] Wrote', OUT_CSV)
    print('[INFO] merged=', len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
