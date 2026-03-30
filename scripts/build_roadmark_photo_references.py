#!/usr/bin/env python3
"""Extract road marking and pavement photos from photo index for reference.

Usage:
    python scripts/build_roadmark_photo_references.py

Reads: PHOTOS KENSINGTON/csv/photo_address_index.csv
Writes: outputs/road_markings/roadmark_photo_references.csv,
        outputs/road_markings/roadmark_photo_references.json
"""
from __future__ import annotations
import csv, json, re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / 'PHOTOS KENSINGTON' / 'csv' / 'photo_address_index.csv'
OUT = ROOT / 'outputs' / 'road_markings'
COORD = re.compile(r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)')

KEY_GROUPS = {
    'marking_crosswalk': ['crosswalk', 'zebra', 'pedestrian crossing', 'xing'],
    'marking_bikelane_text': ['bike lane', 'cycle lane', 'piste cyclable', 'do not pass open doors'],
    'marking_arrow': ['arrow', 'left turn', 'right turn', 'straight only'],
    'marking_stop_line': ['stop line', 'stop bar'],
    'marking_lane_text': ['lane marking', 'road marking', 'painted line', 'only lane', 'bus lane'],
}


def classify(text: str) -> str:
    t = (text or '').lower()
    for k, terms in KEY_GROUPS.items():
        if any(x in t for x in terms):
            return k
    if any(x in t for x in ['street', 'road', 'intersection', 'college st']):
        return 'marking_lane_text'
    return ''


def score(text: str) -> int:
    t = (text or '').lower()
    s = 0
    for terms in KEY_GROUPS.values():
        s += sum(1 for x in terms if x in t)
    if 'road' in t or 'street' in t or 'intersection' in t:
        s += 1
    if COORD.search(text or ''):
        s += 2
    return s


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    c = Counter()
    with_coords = 0

    for r in csv.DictReader(IDX.open('r', encoding='utf-8', newline='')):
        txt = r.get('address_or_location') or ''
        cat = classify(txt)
        if not cat:
            continue
        sc = score(txt)
        if sc < 1:
            continue
        m = COORD.search(txt)
        lat, lon = ('', '') if not m else (m.group(1), m.group(2))
        if m:
            with_coords += 1
        rows.append({
            'filename': r.get('filename') or '',
            'address_or_location': txt,
            'category': cat,
            'score': sc,
            'lat': lat,
            'lon': lon,
            'has_coords': 'yes' if m else 'no',
        })
        c[cat] += 1

    rows.sort(key=lambda x: x['score'], reverse=True)
    rows = rows[:220]

    out_csv = OUT / 'roadmark_photo_references.csv'
    with out_csv.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['filename','address_or_location','category','score','lat','lon','has_coords'])
        w.writeheader()
        if rows:
            w.writerows(rows)

    (OUT / 'roadmark_photo_references.json').write_text(
        json.dumps({'count': len(rows), 'with_coords': with_coords, 'categories': dict(c)}, indent=2),
        encoding='utf-8',
    )

    print('[OK] Wrote', out_csv)
    print('[INFO] refs=', len(rows), 'with_coords=', with_coords)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
