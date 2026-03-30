#!/usr/bin/env python3
"""Generate procedural road marking decal placements for Unreal Engine.

Usage:
    python scripts/build_unreal_roadmark_decal_placements.py

Reads: outputs/road_markings/roadmark_decal_catalog.csv,
       outputs/road_markings/roadmark_targets_unreal_cm.csv
Writes: outputs/road_markings/unreal_roadmark_decal_placements.csv
"""
from __future__ import annotations
import csv, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEC = ROOT / 'outputs' / 'road_markings' / 'roadmark_decal_catalog.csv'
TGT = ROOT / 'outputs' / 'road_markings' / 'roadmark_targets_unreal_cm.csv'
OUT = ROOT / 'outputs' / 'road_markings' / 'unreal_roadmark_decal_placements.csv'


def u(s: str) -> float:
    h = hashlib.sha1(s.encode('utf-8')).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def main() -> int:
    dec = list(csv.DictReader(DEC.open('r', encoding='utf-8', newline='')))
    tgt = list(csv.DictReader(TGT.open('r', encoding='utf-8', newline='')))
    by = {}
    for d in dec:
        by.setdefault(d['category'], []).append(d)

    out = []
    for t in tgt:
        key = t['marking_key']
        pool = by.get(key) or by.get('marking_lane_text') or dec
        if not pool:
            continue

        # Intersections get denser layered markings.
        layers = 2 if t['source_table'] == 'intersection' else 1
        if key == 'marking_crosswalk':
            layers = 2

        for i in range(layers):
            pick = pool[int(u(t['target_id'] + str(i)) * len(pool)) % len(pool)]
            out.append({
                'target_id': t['target_id'],
                'marking_key': key,
                'decal_layer': i + 1,
                'decal_id': pick['decal_id'],
                'source_type': pick.get('source_type', ''),
                'decal_texture_path': pick['decal_texture_path'],
                'decal_material': '/Game/Street/Decals/MI_decal_roadmark_projection',
                'x_cm': f"{float(t['x_cm']) + (u(t['target_id']+str(i)+'x')-0.5)*55:.1f}",
                'y_cm': f"{float(t['y_cm']) + (u(t['target_id']+str(i)+'y')-0.5)*45:.1f}",
                'z_cm': t['z_cm'],
                'yaw_deg': f"{u(t['target_id']+str(i)+'yaw')*360:.1f}",
                'uniform_scale': f"{0.85 + u(t['target_id']+str(i)+'s')*0.75:.3f}",
                'opacity': f"{0.62 + u(t['target_id']+str(i)+'o')*0.32:.3f}",
            })

    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [])
        w.writeheader()
        if out:
            w.writerows(out)

    print('[OK] Wrote', OUT)
    print('[INFO] placements=', len(out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
